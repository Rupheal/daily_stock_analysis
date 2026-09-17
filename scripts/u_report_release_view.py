"""Narrow U factual-language corrections in a separate, traceable release view.

Raw U model output and all decisions remain unchanged. Never applies to O.
Only date-label, current histogram/transition and demonstrably false oversold
wording are eligible; anything else remains isolated. No model/network call.
"""
from copy import deepcopy
import hashlib,json
from run_u_bounded_member_review import validate_member

VERSION='U_REPORT_FACT_RELEASE_v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def build_release(raw,source):
    before=deepcopy(raw);view=deepcopy(raw);changes=[]
    if source.get('status')!='BOUNDED_FACT_REPORT_VERIFIED' or raw.get('decision') not in ('OBSERVE','AVOID'):
        raise ValueError('U_RELEASE_SOURCE_OR_DECISION_INVALID')
    facts=source['facts']
    for field in ('thesis','counterpoint'):
        text=view[field]
        replacements=[]
        if '现价' in text:
            if not source.get('data_session') or facts['close']<=0:raise ValueError('U_RELEASE_DATE_UNPROVEN')
            replacements.append(('现价','所列数据日收盘价','COMPLETED_DAILY_PRICE_LABEL'))
        if '动能柱转正' in text:
            if facts.get('macd') is None or facts['macd']['histogram_2x']<=0:raise ValueError('U_RELEASE_POSITIVE_HISTOGRAM_UNPROVEN')
            replacements.append(('动能柱转正','动能柱为正','CURRENT_SIGN_NOT_UNPROVEN_TRANSITION'))
        if '超卖修复可能' in text and 30<=facts['rsi14']<50:
            replacements.append(('超卖修复可能','弱势修复可能','RSI_NOT_IN_OVERSOLD_RANGE'))
        for old,new,reason in replacements:
            text=text.replace(old,new);changes.append({'field':field,'from':old,'to':new,'reason':reason})
        view[field]=text
    validate_member(view,source)
    if any(view[k]!=raw[k] for k in raw if k not in ('thesis','counterpoint')):raise AssertionError('U_RELEASE_DECISION_CHANGED')
    assert raw==before
    receipt={'version':VERSION,'code':raw['code'],'raw_sha256':digest(raw),'release_sha256':digest(view),
        'source_facts_sha256':digest(facts),'source_data_session':source['data_session'],
        'changes':changes,'decision_unchanged':True,'raw_preserved':True,
        'formal_BUY_accepted':False,'model_calls':0,'status':'PASS_BOUNDED_RELEASE_REVIEW'}
    return view,receipt
