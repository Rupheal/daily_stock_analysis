import sys
from pathlib import Path
from types import ModuleType
import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from o_frozen_native_history_adapter import patched_frozen_native_history

def preflight():
    rows=[]
    for i in range(1,22):
        rows.append({'date':f'2026-08-{i:02}','open':10.0,'high':11.0,'low':9.0,'close':10.0,
                     'volume':1000+i,'amount':None,'pct_chg':None,'ma5':None,'ma10':None,'ma20':None,
                     'volume_ratio':None,'data_source':'frozen'})
    return {'symbol':'HK00001','target':'2026-08-21','validated_native_history':rows,
            'native_history_window':{'first':'2026-08-01','last':'2026-08-21','count':21}}

def test_adapter_only_replaces_bound_symbol(monkeypatch):
    pkg=ModuleType('data_provider');base=ModuleType('data_provider.base')
    class Manager:
        def get_daily_data(self,code,*args,**kwargs):
            return 'ORIGINAL','Original'
    base.DataFetcherManager=Manager
    monkeypatch.setitem(sys.modules,'data_provider',pkg)
    monkeypatch.setitem(sys.modules,'data_provider.base',base)
    p=preflight()
    with patched_frozen_native_history(p) as receipt:
        df,source=Manager().get_daily_data('HK00001',days=30)
        assert source=='FrozenNativeHistoryAdapter'
        assert len(df)==21 and str(df.iloc[-1]['date'].date())=='2026-08-21'
        assert receipt['count']==1 and receipt['rows']==21 and len(receipt['history_sha256'])==64
        assert Manager().get_daily_data('HK00002')[0]=='ORIGINAL'
    assert Manager().get_daily_data('HK00001')[0]=='ORIGINAL'

def test_adapter_rejects_unbound_window():
    p=preflight();p['native_history_window']['count']=20
    with pytest.raises(ValueError,match='FROZEN_NATIVE_HISTORY_WINDOW_UNBOUND'):
        with patched_frozen_native_history(p):
            pass
