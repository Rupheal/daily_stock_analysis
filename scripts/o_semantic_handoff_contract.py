"""Deterministic native-output semantics and a versioned evidence-input bridge.

v2 keeps native news-count semantics unchanged, replaces full Python-object
context hashing with a stable identity/session/window projection, and appends a
separately versioned deterministic session-fact anchor sourced from preflight.
No model, market, filesystem-write or broker calls occur in this module.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import inspect
import json
import re
from urllib.parse import urlparse

from o_session_fact_anchor import build_session_fact_anchor_from_preflight

CONTRACT_VERSION = 'O_SEMANTIC_NEWS_HANDOFF_v2'
CONTEXT_BINDING_VERSION = 'O_NATIVE_CONTEXT_BINDING_v1'
FROZEN_UPSTREAM = '089d9d26d68f8b839ea5a74a3784e4402925f8b7'
NATIVE_COUNT_SEMANTICS = 'native_089d9_known_field_tristate'

class ContractError(ValueError):
    pass

def canonical_hash(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def aware(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.utcoffset() is None:raise ValueError()
        return dt.astimezone(timezone.utc)
    except (ValueError,TypeError):raise ContractError('TIMESTAMP_MUST_BE_AWARE') from None

def number(value):
    if value is None or isinstance(value,bool):return None
    try:x=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):return None
    return x if x.is_finite() else None

def walk_text(value,path='$'):
    if isinstance(value,dict):
        for k,v in value.items():yield from walk_text(v,path+'.'+str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from walk_text(v,f'{path}[{i}]')
    elif isinstance(value,str):yield path,value

_CLAIMS={'UP':r'高开|(?:开盘[^。；，,\n]{0,30})?高于前收|gap(?:ped)?\s+up|open(?:ed)?\s+higher',
         'DOWN':r'低开|(?:开盘[^。；，,\n]{0,30})?低于前收|gap(?:ped)?\s+down|open(?:ed)?\s+lower',
         'FLAT':r'平开|开盘[^。；，,\n]{0,30}(?:等于|持平于)前收|open(?:ed)?\s+flat'}
_NONCURRENT=re.compile(r'昨日|昨天|前日|此前|上周|明日|明天|未来|若|如果|假如|可能|预计|有望|等待|需确认|\b(?:if|yesterday|tomorrow|might|may|could)\b',re.I)
_NEGATED=re.compile(r'(?:不是|并非|并未|未见|不构成|not|no)\s*$',re.I)

def opening_check(original_input,result):
    ctx=original_input.get('context') or {};today=ctx.get('today') or {};prev=ctx.get('yesterday') or {}
    op,pc=number(today.get('open')),number(prev.get('close'))
    findings=[];claims=[];skipped=[]
    if op is None or pc is None or op<=0 or pc<=0:
        return {'status':'BLOCK','facts':None,'findings':[{'code':'OPEN_GAP_UNVERIFIABLE','severity':'BLOCK','paths':['context.today.open','context.yesterday.close']}],'claims':[],'unassessed':[]}
    direction='UP' if op>pc else 'DOWN' if op<pc else 'FLAT'
    facts={'open':str(op),'previous_close':str(pc),'difference':str(op-pc),'gap_pct':str((op/pc-1)*100),
           'direction':direction,'label':{'UP':'高开','DOWN':'低开','FLAT':'平开'}[direction],
           'basis':'native_input_same_price_basis','not_model_output':True}
    for path,text in walk_text(result):
        for clause in re.split(r'[。；;\n]',text):
            for segment in re.split(r'[，,]',clause):
                for claimed,pattern in _CLAIMS.items():
                    for m in re.finditer(pattern,segment,re.I):
                        prefix=segment[:m.start()]
                        if _NONCURRENT.search(prefix) or _NEGATED.search(prefix) or _NONCURRENT.search(clause[:clause.find(segment)]):
                            skipped.append({'path':path,'reason':'NONCURRENT_OR_NEGATED','claim':claimed});continue
                        claims.append({'path':path,'claimed':claimed})
                        if claimed!=direction:
                            findings.append({'code':'OPEN_GAP_DIRECTION_CONTRADICTION','severity':'BLOCK','paths':[path,'context.today.open','context.yesterday.close']})
                for name,actual,pattern in [
                    ('open',op,r'开盘(?:价)?\s*(?:约为|为|约|[:：])?\s*(\d+(?:\.\d+)?)(?![\d.:：]|\s*(?:分钟|时|秒|点))'),
                    ('previous_close',pc,r'前收(?:盘价)?\s*(?:约为|为|约|[:：])?\s*(\d+(?:\.\d+)?)(?![\d.:：]|\s*(?:分钟|时|秒|点))')]:
                    for m in re.finditer(pattern,segment):
                        if _NONCURRENT.search(segment[:m.start()]):continue
                        stated=Decimal(m[1]);quantum=Decimal(1).scaleb(stated.as_tuple().exponent)
                        if actual.quantize(quantum,rounding=ROUND_HALF_UP)!=stated:
                            findings.append({'code':'OPEN_GAP_STATED_NUMBER_MISMATCH','severity':'BLOCK','paths':[path,'context.'+name]})
    unique={canonical_hash(f):f for f in findings}
    return {'status':'BLOCK' if findings else 'NO_CONTRADICTION_IN_RECOGNIZED_CLAIMS','facts':facts,
            'findings':list(unique.values()),'claims':claims,'unassessed':skipped}

def news_count_state(result,*,semantics=NATIVE_COUNT_SEMANTICS):
    known=result.get('news_result_count_known')
    present='news_result_count' in result
    count=result.get('news_result_count');findings=[]
    if semantics!=NATIVE_COUNT_SEMANTICS:
        return {'state':'SEMANTICS_UNKNOWN','count':None,'numeric_count_known':False,'findings':[{'code':'NEWS_COUNT_SEMANTICS_UNKNOWN','severity':'BLOCK','paths':['news_result_count_known']}]}
    if known is not None and not isinstance(known,bool):
        findings.append({'code':'NEWS_KNOWN_FLAG_NOT_BOOLEAN','severity':'BLOCK','paths':['news_result_count_known']})
    if known is False or not present:
        state='LEGACY_UNKNOWN';value=None
    elif count is None:
        state='NOT_SEARCHED';value=None
    elif isinstance(count,bool) or not isinstance(count,int) or count<0:
        state='INVALID_COUNT';value=None
        findings.append({'code':'NEWS_COUNT_KNOWN_WITHOUT_VALID_TRISTATE','severity':'BLOCK','paths':['news_result_count']})
    else:state='SEARCHED_ZERO' if count==0 else 'SEARCHED_HITS';value=count
    if known is True and not present:
        findings.append({'code':'NEWS_KNOWN_FLAG_WITH_MISSING_FIELD','severity':'BLOCK','paths':['news_result_count_known','news_result_count']})
    return {'semantics':semantics,'state':state,'native_field_state_known':known is not False and present,
            'numeric_count_known':value is not None,'count':value,'findings':findings,
            'native_search_flag_not_proof_of_http':True,'native_fields_mutated':False}

def _url(value):
    if not isinstance(value,str):raise ContractError('INVALID_SOURCE_URL')
    p=urlparse(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ContractError('INVALID_SOURCE_URL')
    return value


def context_binding_projection(context):
    if not isinstance(context,dict):raise ContractError('CONTEXT_BINDING_NOT_MAPPING')
    window=context.get('news_window_days')
    if isinstance(window,bool) or not isinstance(window,int) or window<=0:raise ContractError('NEWS_WINDOW_UNKNOWN')
    today=context.get('today') or {};yesterday=context.get('yesterday') or {}
    projection={
        'version':CONTEXT_BINDING_VERSION,
        'code':str(context.get('code','')).upper(),
        'date':str(context.get('date','')),
        'today_date':str(today.get('date','')),
        'yesterday_date':str(yesterday.get('date','')),
        'news_window_days':window,
    }
    if not projection['code'] or not projection['date'] or not projection['today_date']:
        raise ContractError('CONTEXT_BINDING_IDENTITY_MISSING')
    return projection


def context_binding_hash(context):
    return canonical_hash(context_binding_projection(context))


def build_news_handoff(preflight,context,*,expected_preflight_hash,decision_at,policy_version=CONTRACT_VERSION):
    if policy_version!=CONTRACT_VERSION:raise ContractError('UNKNOWN_HANDOFF_VERSION')
    if canonical_hash(preflight)!=expected_preflight_hash:raise ContractError('PREFLIGHT_HASH_MISMATCH')
    if preflight.get('passed') is not True or preflight.get('prices_passed') is not True:raise ContractError('PREFLIGHT_NOT_PASSED')
    prepared,cutoff=aware(preflight.get('prepared_at')),aware(decision_at)
    if prepared>cutoff:raise ContractError('PREFLIGHT_NOT_AVAILABLE_AT_DECISION')
    symbol=str(preflight.get('symbol','')).upper();target=str(preflight.get('target',''))
    if not symbol or str(context.get('code','')).upper()!=symbol:raise ContractError('SYMBOL_MISMATCH')
    if target!=str(context.get('date')) or target!=str((context.get('today') or {}).get('date')):raise ContractError('TARGET_SESSION_MISMATCH')
    status=(preflight.get('component_status') or {}).get('news')
    if status not in ('passed_limited_coverage','passed'):raise ContractError('NEWS_PREFLIGHT_UNAVAILABLE')
    window=context.get('news_window_days')
    if isinstance(window,bool) or not isinstance(window,int) or window<=0:raise ContractError('NEWS_WINDOW_UNKNOWN')
    allowed=preflight.get('allowed_news_urls');events=preflight.get('company_news_evidence')
    if not isinstance(allowed,list) or not isinstance(events,list):raise ContractError('NEWS_LIST_MISSING')
    allowed=set(_url(u) for u in allowed)
    reported=preflight.get('news_count')
    if isinstance(reported,bool) or not isinstance(reported,int) or reported<0 or reported!=len(allowed):raise ContractError('PREFLIGHT_COUNT_DENOMINATOR_MISMATCH')
    unique={};seen_urls=set();rejected=[]
    for event in events:
        e=deepcopy(event);eid=e.get('event_id');urls=e.get('source_urls')
        if not isinstance(eid,str) or not eid or not isinstance(urls,list) or not urls:raise ContractError('NEWS_PROVENANCE_MISSING')
        if any(_url(u) not in allowed for u in urls):raise ContractError('UNAPPROVED_NEWS_URL')
        if not all(isinstance(e.get(k),str) and e[k].strip() for k in ('title','summary','source','published_at','evidence_kind')):raise ContractError('NEWS_FIELDS_MISSING')
        if any(any(c in e[k] for c in ('```','~~~','\x00','<script','</script')) for k in ('title','summary','source')):raise ContractError('UNSAFE_NEWS_DELIMITER')
        records=e.get('source_records')
        if not isinstance(records,list) or not records or any(not isinstance(r,dict) or not r.get('source') or r.get('url') not in urls for r in records):raise ContractError('NEWS_SOURCE_RECORD_MISMATCH')
        if set(r['url'] for r in records)!=set(urls):raise ContractError('NEWS_SOURCE_RECORD_MISMATCH')
        if eid in unique:
            if canonical_hash(unique[eid])!=canonical_hash(e):raise ContractError('CONFLICTING_DUPLICATE_EVENT')
            continue
        try:publication=datetime.fromisoformat(e['published_at'].replace('Z','+00:00'))
        except ValueError:raise ContractError('PUBLICATION_DATE_UNKNOWN') from None
        if publication.tzinfo is not None:
            pt=publication.astimezone(timezone.utc)
            if pt>prepared or pt>cutoff:raise ContractError('FUTURE_NEWS')
            recent=cutoff-timedelta(days=window)<=pt
        else:
            if publication.date()>prepared.date():raise ContractError('FUTURE_NEWS_DATE')
            recent=(cutoff-timedelta(days=window-1)).date()<=publication.date()<=prepared.date()
        if not recent:
            rejected.append({'event_id':eid,'reason':'OUTSIDE_CONSERVATIVE_NATIVE_WINDOW'});continue
        unique[eid]=e;seen_urls.update(urls)
    if events and not unique:raise ContractError('NO_RECENT_NEWS_ADMITTED')
    items=list(unique.values())
    ctx_blob={'version':CONTRACT_VERSION,'source_symbol':symbol,'target_session':target,
      'preflight_observed_at':preflight['prepared_at'],'decision_at':decision_at,
      'coverage':'有限媒体摘要；不是完整公告或完整搜索；不能据此排除未报道风险',
      'publication_note':'原始发布时间保留；无时区字符串不补写时区。观测时间不是首次公开时间。',
      'items':items}
    news_text='' if not items else 'DSA-PREFLIGHT-NEWS '+canonical_hash(ctx_blob)+'\n'+json.dumps(ctx_blob,ensure_ascii=False,sort_keys=True,indent=2)
    try:
        session_anchor=build_session_fact_anchor_from_preflight(preflight)
    except Exception as exc:
        raise ContractError('SESSION_FACT_ANCHOR_BUILD_FAILED:'+str(exc)) from None
    context_text=(news_text+'\n\n'+session_anchor['text']).strip() if news_text else session_anchor['text']
    risk=(preflight.get('hk_report_contract') or {}).get('required_risk_ids') or []
    binding_hash=context_binding_hash(context)
    return {'version':CONTRACT_VERSION,'preflight_hash':expected_preflight_hash,
            'native_context_hash':binding_hash,'native_context_binding_version':CONTEXT_BINDING_VERSION,
            'decision_at':decision_at,'target_session':target,'symbol':symbol,'news_context':context_text,
            'news_context_sha256':sha256(context_text.encode()).hexdigest(),
            'session_fact_anchor':session_anchor,
            'admitted_event_ids':list(unique),'admitted_evidence_count':len(items),'admitted_source_record_count':len(seen_urls),
            'upstream_reported_source_count':reported,'excluded_items':rejected,
            'publication_timezone_inferred':False,'full_coverage':False,'first_publication_verified':False,
            'unresolved_risk_ids_preserved_outside_native_news_window':risk,
            'unresolved_risk_handoff_complete':not bool(risk),
            'original_search_result_count_changed':False,'model_http_requests':0}

def bind_news_argument(native_callable,instance,context,args,kwargs,handoff):
    if context_binding_hash(context)!=handoff['native_context_hash']:raise ContractError('CONTEXT_CHANGED_AFTER_HANDOFF')
    bound=inspect.signature(native_callable).bind(instance,context,*args,**kwargs)
    if 'news_context' not in inspect.signature(native_callable).parameters:raise ContractError('NATIVE_NEWS_PARAMETER_MISSING')
    current=bound.arguments.get('news_context');new=handoff['news_context']
    if current not in (None,'',new):raise ContractError('EXISTING_NATIVE_NEWS_CONFLICT')
    bound.arguments['news_context']=new or None
    return bound.args,bound.kwargs

def prove_prompt_consumption(prompt,handoff):
    text=handoff['news_context'];present=bool(text) and prompt.count(text)==1
    if text and not present:raise ContractError('NATIVE_PROMPT_DROPPED_OR_DUPLICATED_NEWS')
    if text and ('未搜索到该股票近期的相关新闻。' in prompt or 'news_context_missing' in prompt):raise ContractError('NATIVE_PROMPT_FALSE_NO_NEWS_BRANCH')
    return {'version':CONTRACT_VERSION,'prompt_sha256':sha256(prompt.encode()).hexdigest(),
      'news_context_sha256':handoff['news_context_sha256'],'native_prompt_evidence_consumed':present,
      'session_fact_anchor_sha256':(handoff.get('session_fact_anchor') or {}).get('sha256'),
      'admitted_evidence_count':handoff['admitted_evidence_count'],'provider_request_sent':False,
      'meaning':'Native formatter consumed the exact evidence block including versioned session facts; this does not prove model understanding.'}
