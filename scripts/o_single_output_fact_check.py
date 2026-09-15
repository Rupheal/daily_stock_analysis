"""Offline deterministic O-native saved-output acceptance guards.

Consumes preserved evidence only. Never edits native input/output and never calls
any model, broker, market API, or search provider. Execution integrity and output
semantics are separate gates; a model-execution PASS does not imply full-pool,
Top3, Shadow, or runtime promotion.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re

from o_semantic_handoff_contract import opening_check, news_count_state

GUARD_VERSION = 'O_POST_OUTPUT_SEMANTIC_GUARDS_v1.1'


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def _walk(value, path='$'):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f'{path}[{index}]')
    elif isinstance(value, str):
        yield path, value


def _get(value, *parts):
    cur=value
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur=cur.get(part)
    return cur


def _evidence_text(preflight, original_input):
    return '\n'.join(text for _, text in [*_walk(preflight), *_walk(original_input)])


def _semantic_guards(preflight, original_input, result):
    findings=[]
    ctx=original_input.get('context') or {}

    # SEM-001: a completed-session close must not be relabeled as live/current
    # when the native input has no realtime quote.
    realtime_missing = result.get('current_price') is None
    source_chain=((ctx.get('fundamental_context') or {}).get('source_chain') or [])
    realtime_missing = realtime_missing or any(
        row.get('provider')=='realtime_quote' and row.get('result') in ('not_supported','missing','unavailable')
        for row in source_chain if isinstance(row,dict)
    )
    if realtime_missing:
        dashboard_price=_get(result,'dashboard','data_perspective','price_position','current_price')
        if numeric(dashboard_price) is not None:
            findings.append({'code':'SEM001_LIVE_PRICE_FIELD_WITHOUT_REALTIME_QUOTE','guard_id':'SEM-001','severity':'CONDITION',
                             'paths':['dashboard.data_perspective.price_position.current_price','current_price']})
        safe_hints=('现价缺失','无法获取现价','实时行情缺失','实时价格缺失','无实时行情','上一交易日','最新可复用完整日线')
        live_claim=re.compile(r'现价\s*(?:为|约|对|[:：]?\s*)?\d|现价对|现价高于|现价低于')
        for path,text in _walk(result):
            if '现价' in text and not any(h in text for h in safe_hints) and live_claim.search(text):
                findings.append({'code':'SEM001_LIVE_PRICE_LABEL_WITHOUT_REALTIME_QUOTE','guard_id':'SEM-001','severity':'CONDITION','paths':[path]})

    # SEM-002: missing native news context cannot justify an absence-of-bad-news claim.
    news_missing = original_input.get('news_context') in (None,'') and not ctx.get('company_news_evidence')
    if news_missing:
        absence_patterns=(
            re.compile(r'未见.{0,16}(?:利空|重大利空|负面|处罚|减持|公告)'),
            re.compile(r'未发现.{0,16}(?:利空|重大利空|负面|处罚|减持|公告)'),
            re.compile(r'没有.{0,12}(?:利空|重大利空|负面|处罚|减持|公告)'),
            re.compile(r'暂无.{0,12}(?:利空|重大利空|负面|处罚|减持|公告)'),
        )
        for path,text in _walk(result):
            if any(pattern.search(text) for pattern in absence_patterns):
                findings.append({'code':'SEM002_ADVERSE_NEWS_ABSENCE_CLAIM_WITH_MISSING_CONTEXT','guard_id':'SEM-002','severity':'CONDITION','paths':[path,'news_context']})

    # SEM-003: when search was not performed, do not add index-membership/weight
    # facts that are absent from the frozen evidence.
    if result.get('search_performed') is False:
        evidence=_evidence_text(preflight, original_input)
        evidence_has_hst='恒生科技指数' in evidence and any(term in evidence for term in ('权重股','成份股','成分股'))
        if not evidence_has_hst:
            index_patterns=(
                re.compile(r'恒生科技指数.{0,12}(?:权重股|成份股|成分股)'),
                re.compile(r'(?:权重股|成份股|成分股).{0,12}恒生科技指数'),
            )
            for path,text in _walk(result):
                if any(pattern.search(text) for pattern in index_patterns):
                    findings.append({'code':'SEM003_UNSUPPORTED_INDEX_FACT_WITHOUT_SEARCH','guard_id':'SEM-003','severity':'CONDITION','paths':[path,'search_performed']})
    return findings


def check_saved_output(preflight, original_input, result):
    ctx = original_input.get('context') or {}
    today, yesterday = ctx.get('today') or {}, ctx.get('yesterday') or {}
    findings, passed = [], []
    target = str(preflight.get('target'))
    if str(ctx.get('date')) != target or str(today.get('date')) != target:
        findings.append({'code':'INPUT_TARGET_MISMATCH','severity':'BLOCK','paths':['context.date','context.today.date']})
    else:
        passed.append('TARGET_MATCH')
    opening = opening_check(original_input, result)
    findings.extend(opening['findings'])
    if not opening['findings']:
        passed.append('OPEN_GAP_NOT_CONTRADICTED_IN_RECOGNIZED_CLAIMS')
    news_state = news_count_state(result)
    findings.extend(news_state['findings'])
    if not news_state['findings']:
        passed.append('NATIVE_NEWS_TRISTATE_CONSISTENT')
    count=numeric(preflight.get('news_count'))
    if count is not None and count>0 and original_input.get('news_context') in (None,'') and not ctx.get('company_news_evidence'):
        findings.append({'code':'PREFLIGHT_NEWS_NOT_DELIVERED_TO_NATIVE_INPUT','severity':'INTEGRATION_GAP','paths':['preflight.news_count','original_input.news_context','context.company_news_evidence']})
    finance=(((ctx.get('fundamental_context') or {}).get('earnings') or {}).get('data') or {}).get('financial_report') or {}
    if finance and not all(finance.get(k) for k in ('period_start','period_end','period_type','source_evidence_id')):
        findings.append({'code':'FINANCIAL_PERIOD_PRIMARY_LINEAGE_INCOMPLETE','severity':'LIMITATION','paths':['context.fundamental_context.earnings.data.financial_report']})
    native_action=result.get('action')
    if native_action in ('watch','hold','wait','sell'):
        passed.append('NATIVE_NONBUY_PRESERVED')

    findings.extend(_semantic_guards(preflight, original_input, result))
    triggered_guards=sorted({f.get('guard_id') for f in findings if f.get('guard_id')})
    blocked=any(f['severity']=='BLOCK' for f in findings)
    conditioned=any(f['severity'] in ('CONDITION','INTEGRATION_GAP','LIMITATION') for f in findings)
    verdict='NO_GO' if blocked else ('PASS_WITH_CONDITIONS' if conditioned else 'NO_BLOCK_IN_CHECKED_SCOPE')
    return {'schema_version':2,'guard_version':GUARD_VERSION,
            'check_scope':'SAVED_OUTPUT_NARROW_SEMANTIC_AND_EVIDENCE_HANDOFF',
            'semantic_verdict':verdict,'checks_passed':passed,'findings':findings,
            'triggered_semantic_guards':triggered_guards,
            'new_model_requests':0,'native_data_mutated':False,
            'opening_facts_sidecar':opening['facts'],'news_state_sidecar':news_state,
            'opening_claims_unassessed':opening['unassessed'],
            'o_full_pool_accepted':False,'runtime_activated':False}
