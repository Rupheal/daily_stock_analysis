import json
from argparse import Namespace
from pathlib import Path

import scripts.run005_o660_a3_challenger as c


def patch_inputs(monkeypatch, members=None):
    members=members or ['HK00001','HK00002','HK00003']
    coverage={m:{'status':'passed_21_observed_daily_bars'} for m in members}
    monkeypatch.setattr(c.base,'load_inputs',lambda *a,**k: ({'universe_id':'U'}, {}, members, coverage, 'd'*64))
    monkeypatch.setattr(c.base,'file_sha256',lambda p:'a'*64 if 'universe' in str(p) else 'b'*64)
    def feat(db,code,target):
        return {'code':code,'as_of':target,'close':10.0,'return_1d_pct':1.0,'return_5d_pct':2.0,'return_10d_pct':3.0,'return_20d_pct':4.0,'ma5':9.0,'ma10':8.0,'ma20':7.0,'bias_ma5_pct':1.0,'bias_ma20_pct':2.0,'volume_ratio':1.1,'realized_vol20_ann_pct':55.0,'position_in_20d_range':0.7,'source':'HKEX'}
    monkeypatch.setattr(c.base,'technical_features',feat)
    return members


def test_a3_omits_only_volatility_and_freezes(tmp_path,monkeypatch):
    members=patch_inputs(monkeypatch)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    seen=[]
    def fake(url,body,key):
        facts=json.loads(body['messages'][1]['content'])['facts']; seen.append(facts)
        return {'model':'deepseek-flash','choices':[{'message':{'content':json.dumps({'score':60,'stance':'positive','confidence':'medium','reason_codes':['positive_momentum'],'extra':'drop'})}}], 'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}
    u=tmp_path/'universe.json'; i=tmp_path/'integrity.json'; u.write_text('{}'); i.write_text('{}')
    args=Namespace(db='db',universe=str(u),integrity=str(i),output=str(tmp_path/'out'),target='2026-09-11',track='O',model='deepseek-v4-flash',run_id='TRI-DSA-VAL-20260913-005-A3-OOS-TEST',max_requests=3,max_cny=3.0,dry_run=False)
    pkg=c.execute(args,post_json=fake)
    assert pkg['denominator']==3 and pkg['ranked_count']==3 and pkg['isolated_count']==0
    assert pkg['model_http_requests']==3 and pkg['champion_replaced'] is False and pkg['outcome_data_read'] is False
    assert pkg['omitted_fields']==['realized_vol20_ann_pct']
    assert all('realized_vol20_ann_pct' not in f for f in seen)
    assert all('volume_ratio' in f and 'return_20d_pct' in f and 'ma20' in f for f in seen)
    assert len(list((tmp_path/'out'/'prediction-ledger').glob('*.prediction.json')))==1
    text=(tmp_path/'out'/'a3-o660-challenger.json').read_text()
    for forbidden in ('"raw_response"','"provider_response"','"messages"','"reasoning"','"analysis"','"explanation"'):
        assert forbidden not in text


def test_failure_preserves_denominator(tmp_path,monkeypatch):
    patch_inputs(monkeypatch)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    n={'x':0}
    def fake(url,body,key):
        n['x']+=1
        if n['x']==1: raise RuntimeError('synthetic')
        return {'model':'deepseek-flash','choices':[{'message':{'content':json.dumps({'score':50,'stance':'neutral','confidence':'low','reason_codes':['insufficient_edge']})}}], 'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    u=tmp_path/'universe.json'; i=tmp_path/'integrity.json'; u.write_text('{}'); i.write_text('{}')
    args=Namespace(db='db',universe=str(u),integrity=str(i),output=str(tmp_path/'out'),target='2026-09-11',track='O',model='deepseek-v4-flash',run_id='TRI-DSA-VAL-20260913-005-A3-OOS-TEST2',max_requests=3,max_cny=3.0,dry_run=False)
    pkg=c.execute(args,post_json=fake)
    assert pkg['ranked_count']+pkg['isolated_count']==3
    assert pkg['isolated_count']==1
