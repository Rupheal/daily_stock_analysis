import json
from argparse import Namespace
from pathlib import Path

from scripts.run005_predict_anchor import execute
from src.services.dsa_prediction_ledger import canonical_hash, load_frozen_prediction


def make_input(tmp_path):
    inp=tmp_path/'input'; inp.mkdir()
    members=[{"code":"00100","english_name":"A"},{"code":"02475","english_name":"B"}]
    cohort={"anchor_id":"A1","decision_at":"2025-03-10T09:00:00+08:00","original_additions_denominator":2,"members":members}
    (inp/'cohort.json').write_text(json.dumps(cohort))
    coverage={"anchor_id":"A1","denominator":2,"eligible_count":1,"isolated_count":1,"eligible_codes":["00100"],"isolated":[{"code":"02475","reason":"INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS","valid_bar_count":5,"required_bar_count":21}]}
    (inp/'coverage.json').write_text(json.dumps(coverage))
    row={"code":"00100","as_of":"2025-03-07","close":100.0,"return_1d_pct":1.0,"return_5d_pct":2.0,"return_10d_pct":3.0,"return_20d_pct":4.0,"ma5":99.0,"ma10":98.0,"ma20":97.0,"bias_ma5_pct":1.01,"bias_ma20_pct":3.09,"volume_ratio":1.2,"realized_vol20_ann_pct":30.0,"position_in_20d_range":0.7,"source":"HKEX Main Board Daily Quotations"}
    row['feature_sha256']=canonical_hash(row)
    features={"anchor_id":"A1","decision_at":"2025-03-10T09:00:00+08:00","input_cutoff":"2025-03-10T08:00:00+08:00","original_denominator":2,"eligible_count":1,"isolated_count":1,"features":[row]}
    features['input_sha256']=canonical_hash(features)
    (inp/'pit-features.json').write_text(json.dumps(features))
    receipt={"decision_at":"2025-03-10T09:00:00+08:00","universe_id":"A1","model_version":"RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1","config_sha256":"b"*64,"evidence_ids":["Q"],"pit_input_admissible":True,"prediction_generated":False,"manifest_sha256":"a"*64}
    (inp/'pit-manifest-receipt.json').write_text(json.dumps(receipt))
    package={"anchor_id":"A1","decision_at":"2025-03-10T09:00:00+08:00","original_denominator":2,"eligible_count":1,"isolated_count":1,"prediction_generated":False,"outcome_data_fetched":False,"pit_input_admissible":True,"input_sha256":features['input_sha256'],"manifest_sha256":"a"*64}
    (inp/'package-manifest.json').write_text(json.dumps(package))
    config={"config_id":"RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1","frozen_before_prediction":True,"model_contract":{"requested_model":"deepseek-v4-flash"}}
    cfg=tmp_path/'config.json'; cfg.write_text(json.dumps(config))
    return inp,cfg


def test_predictor_preserves_input_isolation_and_freezes_ledger(tmp_path, monkeypatch):
    inp,cfg=make_input(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    def fake_post(url,body,key):
        result={"score":77,"stance":"positive","confidence":"medium","reason_codes":["positive_momentum"],"extra":"discard"}
        return {"model":"deepseek-flash","choices":[{"message":{"content":json.dumps(result)}}],"usage":{"prompt_tokens":20,"completion_tokens":6,"total_tokens":26}}
    out=tmp_path/'out'
    args=Namespace(input_dir=str(inp),config=str(cfg),output=str(out),run_id='TRI-DSA-VAL-TEST-A1',max_requests=1,max_cny=1.0,dry_run=False)
    result=execute(args,post_json=fake_post)
    assert result['original_denominator']==2
    assert result['ranked_count']==1 and result['isolated_count']==1
    assert result['isolated'][0]['code']=='HK02475'
    assert result['isolated'][0]['source_stage']=='PIT_INPUT'
    assert result['model_http_requests']==1 and result['outcome_data_read'] is False
    assert result['ranking_envelope']['denominator']==2
    assert result['ranking_envelope']['complete'] is True
    text=(out/'historical-pit-prediction.json').read_text()
    assert '"extra"' not in text
    ledgers=list((out/'prediction-ledger').glob('*.prediction.json'))
    assert len(ledgers)==1
    record,digest=load_frozen_prediction(ledgers[0])
    assert record['as_of']=='2025-03-10T09:00:00+08:00'
    assert ledgers[0].name==f'{digest}.prediction.json'


def test_predictor_budget_guard_keeps_denominator(tmp_path, monkeypatch):
    inp,cfg=make_input(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    out=tmp_path/'out'
    args=Namespace(input_dir=str(inp),config=str(cfg),output=str(out),run_id='TRI-DSA-VAL-TEST-A2',max_requests=1,max_cny=0.0,dry_run=False)
    result=execute(args,post_json=lambda *x: (_ for _ in ()).throw(AssertionError('must not call')))
    assert result['ranked_count']==0 and result['isolated_count']==2
    assert result['model_http_requests']==0
    assert result['ranking_envelope']['denominator']==2 and result['ranking_envelope']['complete'] is True
