from copy import deepcopy
from types import SimpleNamespace
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from xiaomi_yahoo_payload_trace import summarize_payload, observe_parser

def data():
    return {'meta':{'exchangeTimezoneName':'Asia/Hong_Kong','symbol':'1810.HK'},'timestamp':[1757903400],
      'indicators':{'quote':[{'open':[27.1],'high':[27.4],'low':[26.5],'close':[None],'volume':[700]}],
                    'adjclose':[{'adjclose':[None]}]}}

def test_null_close_visible_before_parser_without_replacement():
    d=data();before=deepcopy(d);r=summarize_payload(d)
    assert d==before and r['last_rows'][0]['close']=={'type':'NoneType','value_repr':'None'}
    assert r['last_rows'][0]['adj_close']=={'type':'NoneType','value_repr':'None'}
    assert not r['hash_is_raw_HTTP_bytes']

def test_missing_array_not_called_null():
    d=data();d['indicators']['quote'][0].pop('close')
    assert summarize_payload(d)['last_rows'][0]['close']['value_repr']=="'MISSING_ARRAY_ELEMENT'"

def test_observer_returns_identical_object_and_restores_function():
    result=object();original=lambda d:result;m=SimpleNamespace(parse_quotes=original);records=[]
    with observe_parser(m,records):assert m.parse_quotes(data()) is result
    assert m.parse_quotes is original and records[0]['parser_returned']

def test_real_parser_failure_still_raises_and_restores():
    def original(d):raise ValueError('synthetic')
    m=SimpleNamespace(parse_quotes=original);records=[]
    with pytest.raises(ValueError):
        with observe_parser(m,records):m.parse_quotes(data())
    assert m.parse_quotes is original and len(records)==1 and 'parser_returned' not in records[0]
