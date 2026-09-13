import json
from argparse import Namespace
from pathlib import Path

from scripts.run005_score_anchor_outcomes import execute
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction


def make_case(tmp_path):
    input_dir=tmp_path/'input'; input_dir.mkdir()
    members=[
        {"code":"00100","english_name":"A"},
        {"code":"02475","english_name":"B"},
        {"code":"06951","english_name":"C"},
    ]
    cohort={"anchor_id":"A1","decision_at":"2026-09-07T09:00:00+08:00","members":members}
    (input_dir/'cohort.json').write_text(json.dumps(cohort))
    coverage={"anchor_id":"A1","denominator":3,"eligible_count":2,"isolated_count":1,"eligible_codes":["00100","02475"],"isolated":[{"code":"06951","reason":"INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS"}]}
    (input_dir/'coverage.json').write_text(json.dumps(coverage))
    features=[]
    for code,close,ret in [("00100",100.0,10.0),("02475",50.0,-5.0)]:
        row={"code":code,"as_of":"2026-09-04","close":close,"return_20d_pct":ret}
        row['feature_sha256']=canonical_hash(row)
        features.append(row)
    fp={"anchor_id":"A1","decision_at":"2026-09-07T09:00:00+08:00","features":features}
    fp['input_sha256']=canonical_hash(fp)
    (input_dir/'pit-features.json').write_text(json.dumps(fp))
    (input_dir/'package-manifest.json').write_text(json.dumps({"prediction_generated":False,"outcome_data_fetched":False}))

    ranked=[
        {"code":"HK00100","score":80,"rank":1,"stance":"positive","confidence":"high","reason_codes":["positive_momentum"],"result_sha256":"1"*64},
        {"code":"HK02475","score":60,"rank":2,"stance":"neutral","confidence":"medium","reason_codes":["mixed_ma_structure"],"result_sha256":"2"*64},
    ]
    isolated=[{"code":"HK06951","reason":"input_gate:INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS"}]
    ranking_sha=canonical_hash([{"code":r['code'],"rank":r['rank'],"score":r['score'],"result_sha256":r['result_sha256']} for r in ranked])
    payload_sha=canonical_hash({"ranked":ranked,"isolated":isolated,"ranking_envelope":{"denominator":3}})
    pred={"status":"HISTORICAL_PIT_REPLAY_FROZEN","outcome_data_read":False,"anchor_id":"A1","decision_at":"2026-09-07T09:00:00+08:00","original_denominator":3,"ranked":ranked,"isolated":isolated,"hashes":{"ranking_sha256":ranking_sha,"prediction_payload_sha256":payload_sha}}
    pred_path=tmp_path/'pred.json'; pred_path.write_text(json.dumps(pred))
    ledger_dir=tmp_path/'ledger'
    ledger_record={"run_id":"TRI-DSA-VAL-TEST-PRED","generated_at":"2026-09-13T20:00:00+00:00","as_of":"2026-09-07T09:00:00+08:00","universe_sha256":"a"*64,"input_sha256":fp['input_sha256'],"model_version":"deepseek-v4-flash","config_sha256":"b"*64,"prediction_payload_sha256":payload_sha,"ranking_sha256":ranking_sha,"status":"HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ"}
    ledger_path=freeze_prediction(ledger_dir,ledger_record)
    return input_dir,pred_path,ledger_path


def write_page(path, body):
    path.write_text('<pre>PRV.CLO./\n'+body+'\nSALES RECORD</pre>')


def test_outcome_harness_keeps_suspension_and_input_isolation(tmp_path):
    input_dir,pred,ledger=make_case(tmp_path)
    quotes=tmp_path/'quotes'; quotes.mkdir()
    write_page(quotes/'d260907e.htm', '  100 A HKD 99.00 101.00 105.00 1000\n                              102.00 101.00 98.00 100000\n 2475 B HKD TRADING SUSPENDED')
    out=tmp_path/'out'
    args=Namespace(prediction=str(pred),ledger=str(ledger),input_dir=str(input_dir),quote_dir=str(quotes),horizons='1=2026-09-07',wait_horizons='3,5,10,20',output=str(out),run_id='TRI-DSA-VAL-TEST-OUTCOME',outcome_id='H1',metric_contract='TEST')
    result=execute(args)
    h=result['horizon_results']['1']
    assert h['metrics']['original_matured_denominator']==3
    assert h['metrics']['comparable_ranked_count']==1
    assert h['metrics']['status_counts']['VALID_COMPARABLE']==1
    assert h['metrics']['status_counts']['SUSPENDED_OR_NO_OFFICIAL_CLOSE']==1
    assert h['metrics']['status_counts']['OUTCOME_QUOTE_NOT_PRESENT']==1
    by={r['code']:r for r in h['rows']}
    assert by['HK06951']['prediction_state']=='ISOLATED'
    assert by['HK06951']['prediction_isolation_reason']=='input_gate:INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS'
    assert by['HK06951']['reference_close'] is None
    assert by['HK06951']['forward_return_pct'] is None
    assert result['wait_maturity_horizons']==[3,5,10,20]


def test_missing_outcome_page_is_explicit_not_dropped(tmp_path):
    input_dir,pred,ledger=make_case(tmp_path)
    quotes=tmp_path/'quotes'; quotes.mkdir()
    out=tmp_path/'out'
    args=Namespace(prediction=str(pred),ledger=str(ledger),input_dir=str(input_dir),quote_dir=str(quotes),horizons='1=2026-09-07',wait_horizons='3,5,10,20',output=str(out),run_id='TRI-DSA-VAL-TEST-OUTCOME2',outcome_id='H1MISS',metric_contract='TEST')
    result=execute(args)
    h=result['horizon_results']['1']
    assert h['metrics']['original_matured_denominator']==3
    assert h['metrics']['comparable_ranked_count']==0
    assert h['metrics']['status_counts']=={'SOURCE_PAGE_MISSING':3}


def test_horizon_partition_must_be_complete(tmp_path):
    input_dir,pred,ledger=make_case(tmp_path)
    quotes=tmp_path/'quotes'; quotes.mkdir()
    args=Namespace(prediction=str(pred),ledger=str(ledger),input_dir=str(input_dir),quote_dir=str(quotes),horizons='1=2026-09-07',wait_horizons='3,5,10',output=str(tmp_path/'out'),run_id='TRI-DSA-VAL-TEST-OUTCOME3',outcome_id='BAD',metric_contract='TEST')
    try:
        execute(args)
    except ValueError as exc:
        assert str(exc)=='horizon_partition_must_cover_1_3_5_10_20'
    else:
        raise AssertionError('incomplete horizon partition accepted')
