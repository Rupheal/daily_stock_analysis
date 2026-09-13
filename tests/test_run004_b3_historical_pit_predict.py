import json
from argparse import Namespace
from pathlib import Path

from scripts.run004_b3_historical_pit_predict import execute
from src.services.dsa_prediction_ledger import canonical_hash, load_frozen_prediction


def write_inputs(tmp_path):
    cohort = {
        "decision_at": "2026-09-03T09:00:00+08:00",
        "members": [
            {"code": "00100", "english_name": "MINIMAX-W"},
            {"code": "02475", "english_name": "LUXSHARE ICT"},
            {"code": "06951", "english_name": "CCTC"},
        ],
    }
    config = {
        "config_id": "RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1",
        "frozen_before_prediction": True,
        "prediction_executed_by_this_file": False,
        "decision_at": "2026-09-03T09:00:00+08:00",
        "model_contract": {"requested_model": "deepseek-v4-flash"},
        "outcome_policy": {"outcome_data_must_not_be_fetched_before_prediction_freeze": True},
    }
    rows = []
    for code, close in [("00100", 100.0), ("02475", 50.0), ("06951", 25.0)]:
        row = {
            "code": code, "as_of": "2026-09-02", "close": close,
            "return_1d_pct": 1.0, "return_5d_pct": 2.0, "return_10d_pct": 3.0, "return_20d_pct": 4.0,
            "ma5": close - 1, "ma10": close - 2, "ma20": close - 3,
            "bias_ma5_pct": 1.0, "bias_ma20_pct": 3.0, "volume_ratio": 1.2,
            "realized_vol20_ann_pct": 30.0, "position_in_20d_range": 0.7,
            "source": "HKEX Main Board Daily Quotations",
        }
        row["feature_sha256"] = canonical_hash(row)
        rows.append(row)
    features = {"decision_at": "2026-09-03T09:00:00+08:00", "input_cutoff": "2026-09-02T23:59:59+08:00", "features": rows}
    features["input_sha256"] = canonical_hash(features)
    receipt = {
        "decision_at": "2026-09-03T09:00:00+08:00",
        "pit_input_admissible": True,
        "prediction_generated": False,
        "manifest_sha256": "a" * 64,
    }
    paths = {}
    for name, obj in [("cohort", cohort), ("config", config), ("features", features), ("receipt", receipt)]:
        p = tmp_path / f"{name}.json"; p.write_text(json.dumps(obj)); paths[name] = p
    return paths


def test_historical_pit_prediction_is_outcome_blind_and_append_only(tmp_path, monkeypatch):
    paths = write_inputs(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    scores = iter([61, 80, 40])
    def fake_post(url, body, api_key):
        score = next(scores)
        payload = {"score": score, "stance": "neutral", "confidence": "medium", "reason_codes": ["mixed_ma_structure"], "discard_me": "never persist"}
        return {"model": "deepseek-flash", "choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    out = tmp_path / "out"
    args = Namespace(features=str(paths["features"]), receipt=str(paths["receipt"]), cohort=str(paths["cohort"]), config=str(paths["config"]), output=str(out), run_id="TRI-DSA-DEV-20260913-004-B3-PRED-TEST", max_requests=3, max_cny=1.0, dry_run=False)
    package = execute(args, post_json=fake_post)
    assert package["outcome_data_read"] is False
    assert package["denominator"] == 3 and package["ranked_count"] == 3 and package["isolated_count"] == 0
    assert package["model_http_requests"] == 3
    assert [r["code"] for r in package["ranked"]] == ["HK02475", "HK00100", "HK06951"]
    text = (out / "b3-historical-pit-prediction.json").read_text()
    assert "discard_me" not in text and "prompt" not in text and "reasoning" not in text
    ledgers = list((out / "prediction-ledger").glob("*.prediction.json"))
    assert len(ledgers) == 1
    record, digest = load_frozen_prediction(ledgers[0])
    assert record["as_of"] == "2026-09-03T09:00:00+08:00"
    assert record["status"] == "HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ"
    assert ledgers[0].name == f"{digest}.prediction.json"


def test_rejects_nonadmissible_receipt(tmp_path):
    paths = write_inputs(tmp_path)
    receipt = json.loads(paths["receipt"].read_text()); receipt["pit_input_admissible"] = False; paths["receipt"].write_text(json.dumps(receipt))
    args = Namespace(features=str(paths["features"]), receipt=str(paths["receipt"]), cohort=str(paths["cohort"]), config=str(paths["config"]), output=str(tmp_path / "out"), run_id="TRI-DSA-DEV-20260913-004-B3-PRED-TEST2", max_requests=3, max_cny=1.0, dry_run=True)
    try:
        execute(args)
    except ValueError as exc:
        assert str(exc) == "pit_input_receipt_not_admissible"
    else:
        raise AssertionError("non-admissible PIT receipt was accepted")
