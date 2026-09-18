from copy import deepcopy
from hashlib import sha256
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

from o_news_coverage_limitation import VERSION,LIMITATION_TEXT,apply_coverage_limitation,CoverageLimitationError
from o_semantic_handoff_contract import build_news_handoff,canonical_hash,prove_prompt_consumption


def preflight():
    return {
      'passed':True,'prices_passed':True,'symbol':'HK00005','target':'2026-09-17',
      'prepared_at':'2026-09-18T02:00:00+00:00',
      'component_status':{'news':'passed_limited_coverage'},
      'execution_contract':{'version':'O_GATE_A_EXECUTION_CONTRACT_v2','target_session':'2026-09-17',
                            'realtime_quote_available':False,'session_fact_anchor_required':True},
      'today':{'date':'2026-09-17','open':10,'close':10},'yesterday':{'date':'2026-09-16','close':9.9},
      'news_count':0,'allowed_news_urls':[],'company_news_evidence':[],
      'risk_review_complete':False,'hk_report_contract':{'required_risk_ids':[]}
    }

def context():
    return {'code':'HK00005','date':'2026-09-17','today':{'date':'2026-09-17'},
            'yesterday':{'date':'2026-09-16'},'news_window_days':3}


def test_zero_news_handoff_gets_explicit_coverage_limitation_without_fake_news():
    p=preflight();h=build_news_handoff(p,context(),expected_preflight_hash=canonical_hash(p),decision_at='2026-09-18T02:01:00+00:00')
    old=deepcopy(h);a=apply_coverage_limitation(h,p)
    assert h==old
    assert a['coverage_limitation_adapter']['version']==VERSION
    assert a['coverage_limitation_adapter']['applied'] is True
    assert a['coverage_limitation_adapter']['news_items_added']==0
    assert a['coverage_limitation_adapter']['search_performed_changed'] is False
    assert a['admitted_evidence_count']==0
    assert 'DSA-PREFLIGHT-NEWS ' not in a['news_context']
    assert 'DSA-SESSION-FACT-ANCHOR ' in a['news_context']
    assert LIMITATION_TEXT in a['news_context']
    assert a['news_context_sha256']==sha256(a['news_context'].encode()).hexdigest()


def test_prompt_consumption_proves_exact_adapted_block():
    p=preflight();h=build_news_handoff(p,context(),expected_preflight_hash=canonical_hash(p),decision_at='2026-09-18T02:01:00+00:00')
    a=apply_coverage_limitation(h,p)
    r=prove_prompt_consumption('header\n'+a['news_context']+'\nfooter',a)
    assert r['native_prompt_evidence_consumed'] is True
    assert r['news_context_sha256']==a['news_context_sha256']


def test_adapter_is_deterministic_and_duplicate_application_fails_closed():
    p=preflight();h=build_news_handoff(p,context(),expected_preflight_hash=canonical_hash(p),decision_at='2026-09-18T02:01:00+00:00')
    a=apply_coverage_limitation(h,p);b=apply_coverage_limitation(h,p)
    assert a==b
    try:
        apply_coverage_limitation(a,p)
    except CoverageLimitationError as exc:
        assert str(exc)=='COVERAGE_LIMITATION_DUPLICATED'
    else:
        raise AssertionError('duplicate adapter must fail closed')


def test_complete_review_does_not_invent_limitation():
    p=preflight();h=build_news_handoff(p,context(),expected_preflight_hash=canonical_hash(p),decision_at='2026-09-18T02:01:00+00:00')
    p2=deepcopy(p);p2['risk_review_complete']=True
    h2=deepcopy(h);h2['full_coverage']=True
    out=apply_coverage_limitation(h2,p2)
    assert out['coverage_limitation_adapter']['applied'] is False
    assert out['news_context']==h2['news_context']
