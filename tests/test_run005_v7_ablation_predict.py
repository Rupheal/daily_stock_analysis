import json
from argparse import Namespace
from pathlib import Path

from scripts.run005_v7_ablation_predict import VARIANTS, execute
from src.services.dsa_prediction_ledger import canonical_hash, load_frozen_prediction


def write_input(tmp_path, n=54):
    root=tmp_path/'input'; root.mkdir()
    members=[]; rows=[]
    for i in range(n):
        code=str(1000+i).zfill(5); members.append({'code':code,'english_name':f'S{i}'})
        row={
            'code':code,'as_of':'2026-09-04','close':100+i,
            'return_1d_pct':1.0,'return_5d_pct':2.0,'return_10d_pct':3.0,'return_20d_pct':4.0,
            'ma5':99.0,'ma10':98.0,'ma20':97.0,'bias_ma5_pct':1.0,'bias_ma20_pct':3.0,
            'volume_ratio':1.2,'realized_vol20_ann_pct':30.0,'position_in_20d_range':0.7,
            'source':'HKEX Main Board Daily Quotations'
        }
        row['feature_sha256']=canonical_hash(row); rows.append(row)
    cohort={'anchor_id':'SSE_REBAL_20260904_EFFECTIVE_20260907','decision_at':'2026-09-07T09:00:00+08:00','members':members}
    coverage={'anchor_id':cohort['anchor_id'],'denominator':n,'eligible_codes':[m['code'] for m in members],'isolated':[]}
    features={'anchor_id':cohort['anchor_id'],'decision_at':cohort['decision_at'],'input_cutoff':'2026-09-04T23:59:59+08:00','features':rows}
    features['input_sha256']=canonical_hash(features)
    receipt={'decision_at':cohort['decision_at'],'pit_input_admissible':True,'prediction_generated':False,'manifest_sha256':'a'*64}
    package={'anchor_id':cohort['anchor_id'],'decision_at':cohort['decision_at'],'original_denominator':n,'eligible_count':n,'isolated_count':0,'prediction_generated':False,'outcome_data_fetched':False,'pit_input_admissible':True,'input_sha256':features['input_sha256'],'manifest_sha256':receipt['manifest_sha256']}
    for name,obj in [('cohort',cohort),('coverage',coverage),('pit-features',features),('pit-manifest-receipt',receipt),('package-manifest',package)]:
        (root/f'{name}.json').write_text(json.dumps(obj))
    config={'config_id':'RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1','frozen_before_prediction':True,'model_contract':{'requested_model':'deepseek-v4-flash'}}
    cp=tmp_path/'config.json'; cp.write_text(json.dumps(config))
    return root,cp,features


def test_five_variants_omit_only_frozen_families_and_freeze_ledgers(tmp_path,monkeypatch):
    inp,cfg,features=write_input(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    calls=[]
    def fake(url,body,key):
        facts=json.loads(body['messages'][1]['content'])['facts']; calls.append(facts)
        return {'model':'deepseek-flash','choices':[{'message':{'content':json.dumps({'score':55,'stance':'neutral','confidence':'medium','reason_codes':['mixed_ma_structure'],'extra':'drop'})}}], 'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}
    out=tmp_path/'out'
    args=Namespace(input_dir=str(inp),config=str(cfg),output=str(out),run_id='TRI-DSA-VAL-20260913-005-V7-TEST',max_requests=270,max_cny=5.0,dry_run=False)
    pkg=execute(args,post_json=fake)
    assert pkg['original_denominator']==54 and pkg['outcome_data_read'] is False
    assert pkg['model_http_requests']==270 and len(calls)==270
    assert set(pkg['variants'])==set(VARIANTS)
    for idx,(variant,omitted) in enumerate(VARIANTS.items()):
        v=pkg['variants'][variant]
        assert v['ranked_count']==54 and v['isolated_count']==0 and v['model_http_requests']==54
        group=calls[idx*54:(idx+1)*54]
        assert len(group)==54
        for facts in group:
            assert not (set(facts)&omitted)
            original=set(k for k in features['features'][0] if k!='feature_sha256')
            assert set(facts)==original-omitted
    ledgers=list((out/'prediction-ledger').glob('*.prediction.json'))
    assert len(ledgers)==5
    for p in ledgers: load_frozen_prediction(p)
    text=(out/'v7-ablation-predictions.json').read_text()
    for forbidden in ('"raw_response"','"provider_response"','"messages"','"reasoning"','"analysis"','"explanation"'):
        assert forbidden not in text


def test_model_failure_and_budget_guard_preserve_denominator(tmp_path,monkeypatch):
    inp,cfg,_=write_input(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    count={'n':0}
    def flaky(url,body,key):
        count['n']+=1
        if count['n']==1: raise RuntimeError('synthetic')
        return {'model':'deepseek-flash','choices':[{'message':{'content':json.dumps({'score':50,'stance':'neutral','confidence':'low','reason_codes':['insufficient_edge']})}}], 'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    args=Namespace(input_dir=str(inp),config=str(cfg),output=str(tmp_path/'out'),run_id='TRI-DSA-VAL-20260913-005-V7-TEST2',max_requests=10,max_cny=5.0,dry_run=False)
    pkg=execute(args,post_json=flaky)
    assert pkg['model_http_requests']==10
    for v in pkg['variants'].values():
        assert v['ranked_count']+v['isolated_count']==54
    assert sum(v['isolated_count'] for v in pkg['variants'].values()) > 0
