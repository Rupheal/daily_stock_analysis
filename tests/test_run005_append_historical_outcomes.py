import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from scripts.run005_append_historical_outcomes import execute, pairwise_accuracy, spearman
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction, load_frozen_prediction


def quote_page(rows):
    text = "PRV.CLO./\n"
    for code, name, prev, close in rows:
        text += f" {int(code):5d} {name:<16} HKD {prev:.2f} {close+0.1:.2f} {max(prev,close)+0.5:.2f} 1,000\n"
        text += f"                               {close:.2f} {close-0.1:.2f} {min(prev,close)-0.5:.2f} 100,000\n"
    text += "SALES RECORD\n"
    return text


def make_fixture(tmp_path):
    cohort={"members":[{"code":"00100","english_name":"MINIMAX-W"},{"code":"02475","english_name":"LUXSHARE ICT"},{"code":"06951","english_name":"CCTC"}]}
    cohort_path=tmp_path/'cohort.json'; cohort_path.write_text(json.dumps(cohort))
    features=[]
    for code,close,mom in [("00100",100.0,10.0),("02475",50.0,5.0),("06951",25.0,-5.0)]:
        row={"code":code,"close":close,"return_20d_pct":mom}
        row["feature_sha256"]=canonical_hash(row)
        features.append(row)
    fobj={"decision_at":"2026-09-03T09:00:00+08:00","input_cutoff":"2026-09-02T23:59:59+08:00","features":features}
    fobj["input_sha256"]=canonical_hash(fobj)
    features_path=tmp_path/'features.json'; features_path.write_text(json.dumps(fobj))
    ranked=[]
    for rank,(code,score) in enumerate([("HK00100",72),("HK02475",62),("HK06951",38)],1):
        r={"code":code,"score":score,"rank":rank,"stance":"neutral","confidence":"medium","reason_codes":["mixed_ma_structure"],"feature_sha256":"b"*64,"model":"deepseek-flash"}
        r["result_sha256"]=canonical_hash({k:r[k] for k in ("code","score","stance","confidence","reason_codes","feature_sha256","model")})
        ranked.append(r)
    ranking_sha=canonical_hash([{"code":r["code"],"rank":r["rank"],"score":r["score"],"result_sha256":r["result_sha256"]} for r in ranked])
    pred={"status":"HISTORICAL_PIT_REPLAY_FROZEN","outcome_data_read":False,"decision_at":"2026-09-03T09:00:00+08:00","ranked":ranked,"isolated":[],"hashes":{"ranking_sha256":ranking_sha,"prediction_payload_sha256":"c"*64}}
    prediction_path=tmp_path/'prediction.json'; prediction_path.write_text(json.dumps(pred))
    now=datetime.now(timezone.utc).isoformat()
    ledger_record={"run_id":"TRI-TEST","generated_at":now,"as_of":"2026-09-03T09:00:00+08:00","universe_sha256":"d"*64,"input_sha256":fobj["input_sha256"],"model_version":"deepseek-v4-flash","config_sha256":"e"*64,"prediction_payload_sha256":"c"*64,"ranking_sha256":ranking_sha,"status":"HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ"}
    ledger_path=freeze_prediction(tmp_path/'ledger',ledger_record)
    qdir=tmp_path/'quotes'; qdir.mkdir()
    base=[("00100","MINIMAX-W",100,110),("02475","LUXSHARE ICT",50,52),("06951","CCTC",25,24)]
    (qdir/'d260903e.htm').write_text(quote_page(base))
    base3=[("00100","MINIMAX-W",110,105),("02475","LUXSHARE ICT",52,55),("06951","CCTC",24,23)]
    (qdir/'d260907e.htm').write_text(quote_page(base3))
    return prediction_path,ledger_path,features_path,cohort_path,qdir


def test_metrics_direction():
    assert spearman([3,2,1],[30,20,10]) == 1.0
    assert pairwise_accuracy([3,2,1],[30,10,20])["accuracy"] == 2/3


def test_append_only_outcome_seed(tmp_path):
    prediction,ledger,features,cohort,qdir=make_fixture(tmp_path)
    args=Namespace(prediction=str(prediction),ledger=str(ledger),features=str(features),cohort=str(cohort),quote_dir=str(qdir),horizons="1=2026-09-03,3=2026-09-07",output=str(tmp_path/'out'),run_id="TRI-DSA-VAL-TEST",anchor_id="A1",outcome_id="H1_H3",metric_contract="TEST-CONTRACT")
    before=ledger.read_bytes()
    package=execute(args)
    assert ledger.read_bytes()==before
    assert package["mature_horizons"]==[1,3]
    assert package["wait_maturity_horizons"]==[5,10,20]
    assert package["horizon_results"]["1"]["metrics"]["dsa_pairwise"]["accuracy"]==1.0
    outcomes=list((tmp_path/'out').glob('*.outcome.*.json'))
    assert len(outcomes)==1
    linked=json.loads(outcomes[0].read_text())
    _,digest=load_frozen_prediction(ledger)
    assert linked["prediction_sha256"]==digest
    assert linked["status"]=="PARTIAL_HORIZON_MATURITY"
