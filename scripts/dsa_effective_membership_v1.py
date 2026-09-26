"""Reconcile normalized, source-bound exchange amendments for isolated review.

Content hashes establish provenance, not semantic correctness of extraction or
completeness of an announcement search. Output remains a nonformal candidate.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def sha(raw): return hashlib.sha256(raw).hexdigest()
def day(value): return date.fromisoformat(value).isoformat()
def dt(value):
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('NAIVE_SOURCE_TIME')
    return d

def reference(ref,root,cutoff):
    p=(Path(root)/ref['file']).resolve()
    if not p.is_relative_to(Path(root).resolve()):raise ValueError('SOURCE_OUTSIDE_ARCHIVE')
    if sha(p.read_bytes())!=ref['sha256']:raise ValueError('SOURCE_BYTES_DRIFT')
    if dt(ref['observed_at'])>dt(cutoff):raise ValueError('SOURCE_AFTER_CUTOFF')
    if not ref.get('url','').startswith('https://'):raise ValueError('SOURCE_URL_REQUIRED')


def reconcile(sse,szse,root,target,proof):
    target=day(target);cutoff=proof['cutoff'];dt(cutoff)
    if proof.get('target_session')!=target:raise ValueError('EFFECTIVE_TARGET_MISMATCH')
    if set(proof.get('channels',{}))!={'SSE','SZSE'}:raise ValueError('BOTH_CHANNELS_REQUIRED')
    rows={'SSE':{r['SECURITY_CODE']:copy.deepcopy(r) for r in sse},
          'SZSE':{str(r[0]).zfill(5):list(r) for r in szse[1:]}}
    if len(rows['SSE'])!=len(sse) or len(rows['SZSE'])!=len(szse)-1:raise ValueError('DUPLICATE_CODE')
    audit=[];excluded=[]
    for channel,contract in proof['channels'].items():
        base=day(contract['base_effective_session'])
        if base>target or contract.get('covered_through_session')!=target:
            raise ValueError(channel+'_ANNOUNCEMENT_INTERVAL_INCOMPLETE')
        reference(contract['baseline_evidence'],root,cutoff)
        reference(contract['coverage_evidence'],root,cutoff)
        calendar=contract['service_calendar'];reference(calendar['source'],root,cutoff)
        days=calendar['sessions']
        if days!=sorted(set(days)) or base not in days or target not in days:
            raise ValueError(channel+'_SERVICE_CALENDAR_INCOMPLETE')
        if calendar['covered_from']>base or calendar['covered_through']<target:
            raise ValueError(channel+'_SERVICE_CALENDAR_INTERVAL')
        previous=None;seen=set()
        for event in contract['amendments']:
            reference(event['source'],root,cutoff)
            effective=day(event['effective_session']);published=dt(event['published_at'])
            if published>dt(event['source']['observed_at']):raise ValueError('ANNOUNCEMENT_TIME_ORDER')
            if event['id'] in seen:raise ValueError('DUPLICATE_AMENDMENT')
            seen.add(event['id'])
            if previous and effective<previous:raise ValueError('AMENDMENT_ORDER')
            previous=effective
            if event.get('effective_rule') not in ('NEXT_SERVICE_DAY','EXPLICIT_DATE'):raise ValueError('UNKNOWN_EFFECTIVE_RULE')
            if event.get('effective_rule')=='NEXT_SERVICE_DAY':
                after=[d for d in days if d>published.astimezone(ZoneInfo('Asia/Hong_Kong')).date().isoformat()]
                if not after or effective!=after[0]:raise ValueError('WRONG_NEXT_SERVICE_DAY')
            if not base<effective<=target:raise ValueError('AMENDMENT_OUTSIDE_INTERVAL')
            if effective not in days:raise ValueError('EFFECTIVE_DAY_NOT_SERVICE_DAY')
            touched=set()
            for change in event['changes']:
                code=change['code'];action=change['action']
                if not re.fullmatch(r'\d{5}',code) or code in touched:raise ValueError('CHANGE_IDENTITY_CONFLICT')
                touched.add(code);old=rows[channel].get(code)
                if action=='ADD':
                    if old is not None:raise ValueError('ADD_ALREADY_PRESENT')
                    new=copy.deepcopy(change['row'])
                    if channel=='SSE':
                        if new.get('SECURITY_CODE')!=code or new.get('TRADE_FLAG')!='1':raise ValueError('ADD_ROW_INVALID')
                    elif str(new[0]).zfill(5)!=code:raise ValueError('ADD_ROW_INVALID')
                    rows[channel][code]=new
                elif action in ('REMOVE','SELL_ONLY'):
                    if old is None:raise ValueError('REMOVAL_NOT_PRESENT')
                    if action=='SELL_ONLY' and channel=='SSE':old['TRADE_FLAG']='2'
                    else:del rows[channel][code]
                    excluded.append({'channel':channel,'code':code,'action':action,'effective_session':effective})
                elif action=='REPLACE_IDENTITY':
                    if old is None or change.get('before')!=old:raise ValueError('IDENTITY_BEFORE_MISMATCH')
                    new=copy.deepcopy(change['row'])
                    key=new.get('SECURITY_CODE') if channel=='SSE' else str(new[0]).zfill(5)
                    if key!=code:raise ValueError('IDENTITY_CODE_CHANGED')
                    rows[channel][code]=new
                else:raise ValueError('UNKNOWN_CHANGE_ACTION')
                audit.append({'channel':channel,'event_id':event['id'],'code':code,'action':action,'effective_session':effective,'source_sha256':event['source']['sha256']})
    if any(r.get('TRADE_FLAG') not in ('1','2') for r in rows['SSE'].values()):raise ValueError('UNKNOWN_TRADE_FLAG')
    return list(rows['SSE'].values()),[szse[0]]+list(rows['SZSE'].values()),{
        'state':'EFFECTIVE_MEMBERSHIP_CANDIDATE','target_session':target,'cutoff':cutoff,
        'amendments':audit,'excluded_or_sell_only':excluded,
        'normalization_semantics_independently_verified':False,
        'announcement_search_completeness_independently_verified':False,
        'formal_acceptance':False,'proof_sha256':sha(json.dumps(proof,sort_keys=True,ensure_ascii=False).encode())}
