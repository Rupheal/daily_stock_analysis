"""Offline narrow O-native acceptance checks. Never edit native input/output.

Consumes saved evidence, not a market API. A model execution PASS is distinct from
output semantics and full-pool/Shadow promotion. No model or broker dependency.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def check_saved_output(preflight, original_input, result):
    ctx = original_input.get('context') or {}
    today, yesterday = ctx.get('today') or {}, ctx.get('yesterday') or {}
    findings, passed = [], []
    target = str(preflight.get('target'))
    if str(ctx.get('date')) != target or str(today.get('date')) != target:
        findings.append({'code':'INPUT_TARGET_MISMATCH','severity':'BLOCK','paths':['context.date','context.today.date']})
    else:
        passed.append('TARGET_MATCH')
    o, prev = numeric(today.get('open')), numeric(yesterday.get('close'))
    text = str(result.get('pattern_analysis') or '')
    up_claim = bool(re.search(r'高开|开盘[^。；\n]{0,50}高于前收', text))
    down_claim = bool(re.search(r'低开|开盘[^。；\n]{0,50}低于前收', text))
    if o is None or prev is None:
        findings.append({'code':'OPEN_GAP_UNVERIFIABLE','severity':'BLOCK','paths':['context.today.open','context.yesterday.close']})
    elif (up_claim and o <= prev) or (down_claim and o >= prev):
        findings.append({'code':'OPEN_GAP_DIRECTION_CONTRADICTION','severity':'BLOCK','paths':['pattern_analysis','context.today.open','context.yesterday.close']})
    else:
        passed.append('OPEN_GAP_NOT_CONTRADICTED')
    if result.get('news_result_count_known') is True:
        count=result.get('news_result_count')
        if isinstance(count,bool) or not isinstance(count,int) or count<0:
            findings.append({'code':'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER','severity':'BLOCK','paths':['news_result_count_known','news_result_count']})
        else:
            passed.append('NEWS_COUNT_METADATA_CONSISTENT')
    count=numeric(preflight.get('news_count'))
    if count is not None and count>0 and original_input.get('news_context') in (None,'') and not ctx.get('company_news_evidence'):
        findings.append({'code':'PREFLIGHT_NEWS_NOT_DELIVERED_TO_NATIVE_INPUT','severity':'INTEGRATION_GAP','paths':['preflight.news_count','original_input.news_context','context.company_news_evidence']})
    finance=(((ctx.get('fundamental_context') or {}).get('earnings') or {}).get('data') or {}).get('financial_report') or {}
    if finance and not all(finance.get(k) for k in ('period_start','period_end','period_type','source_evidence_id')):
        findings.append({'code':'FINANCIAL_PERIOD_PRIMARY_LINEAGE_INCOMPLETE','severity':'LIMITATION','paths':['context.fundamental_context.earnings.data.financial_report']})
    native_action=result.get('action')
    if native_action in ('watch','hold','wait','sell'):
        passed.append('NATIVE_NONBUY_PRESERVED')
    blocked=any(f['severity']=='BLOCK' for f in findings)
    return {'schema_version':1,'check_scope':'SAVED_OUTPUT_NARROW_SEMANTIC_AND_EVIDENCE_HANDOFF',
            'semantic_verdict':'NO_GO' if blocked else 'NO_BLOCK_IN_CHECKED_SCOPE',
            'checks_passed':passed,'findings':findings,
            'new_model_requests':0,'native_data_mutated':False,
            'o_full_pool_accepted':False,'runtime_activated':False}
