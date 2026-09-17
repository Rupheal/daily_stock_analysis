import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

from prepare_hk_pool_rollout_preflight import (
    build_preflight, compare_independent, LATEST_VOLUME_MAX_RELATIVE_DEVIATION
)


def rows(n=22):
    start=date(2026,8,27)
    out=[]
    for i in range(n):
        d=(start+timedelta(days=i)).isoformat()
        px=10+i*0.1
        out.append({
            'date':d,'open':px,'high':px+0.3,'low':px-0.2,'close':px+0.1,
            'volume':100000+i*100,'amount':None,'pct_chg':None,
            'ma5':px,'ma10':px,'ma20':px,'volume_ratio':1.0,'data_source':'Yahoo'
        })
    return out


def test_pool_preflight_accepts_zero_admitted_news_without_claiming_search():
    native=rows()
    independent=[{k:r[k] for k in ('date','open','high','low','close','volume')} for r in native]
    target=native[-1]['date']
    universe={'full_union_verified':True,'_sha256':'u','members':[{'code':'00001','official_name':'TEST','channels':['SSE']}]}
    cache={'target_session':target,'_sha256':'c','histories':{'hk00001':native}}
    source={'provider':'Tencent HK qfq daily','url':'https://example.com','retrieved_at':'2026-09-18T00:00:00+00:00','sha256':'x'}
    p=build_preflight('00001',target,universe,cache,independent,source)
    assert p['passed'] is True and p['prices_passed'] is True
    assert p['symbol']=='HK00001'
    assert p['news_count']==0 and p['news_search_performed'] is False
    assert p['company_news_evidence']==[] and p['allowed_news_urls']==[]
    assert 'not evidence that no negative news exists' in p['limitation']
    assert p['validated_native_history']==native
    v=p['price_reconciliation']['volume']
    assert v['calibration_run_id']==34983641578
    assert v['latest_session_max_relative_deviation']==LATEST_VOLUME_MAX_RELATIVE_DEVIATION


def test_latest_volume_outside_calibrated_bound_fails():
    native=rows()
    independent=[{k:r[k] for k in ('date','open','high','low','close','volume')} for r in native]
    independent[-1]['volume']*=1.02
    with pytest.raises(ValueError,match='LATEST_VOLUME_OUTSIDE'):
        compare_independent(native,independent,native[-1]['date'])


def test_any_ohlc_conflict_in_overlap_fails():
    native=rows()
    independent=[{k:r[k] for k in ('date','open','high','low','close','volume')} for r in native]
    independent[3]['close']+=0.02
    with pytest.raises(ValueError,match='INDEPENDENT_OHLC'):
        compare_independent(native,independent,native[-1]['date'])
