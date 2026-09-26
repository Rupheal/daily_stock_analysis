"""Synthetic timing evidence; no natural cycle or Authority acceptance."""
import hashlib
import json
import subprocess
import sys
import pytest

from scripts.dsa_formal_timing_seal_v1 import seal, write_candidate
from scripts.dsa_production_orchestrator_v1 import orchestrate
from scripts.dsa_formal_receipt_resolver_v1 import resolve

NOW = "2026-09-21T17:30:00+08:00"

def inputs(account):
    receipt = ({"status": "ACCEPTED_O_FORMAL_TOP3", "official_O_denominator": 662,
                "operational_O_denominator": 659, "missing_count": 0,
                "qualified_buy_in_Top3": 0, "Top3": []} if account == "O" else
               {"state": "PASS_FORMAL_U_DECISION_WAIT_NO_BUY", "denominator": 45,
                "formal_valid_rows": 44, "qualified_BUY": 0, "rows": [], "Top3": []})
    receipt["target_session"] = "2026-09-21"
    raw = json.dumps(receipt).encode()
    timing = {"cutoff": "2026-09-21T16:00:00+08:00",
              "available_at": "2026-09-21T17:29:00+08:00",
              "valid_until": "2026-09-22T10:00:00+08:00",
              "next_session": "2026-09-22"}
    evidence = {"account": account, "target_session": receipt["target_session"],
                "receipt_sha256": hashlib.sha256(raw).hexdigest(),
                "signal_timing": timing,
                "field_evidence": {k: {"source": "synthetic-fixture", "sha256": "a"*64} for k in timing}}
    return raw, evidence

def test_both_producers_reach_real_resolver_and_orchestrator(tmp_path):
    root = tmp_path/"docs/runtime"
    root.mkdir(parents=True)
    paths = {}
    for account in ("O", "U"):
        raw, ev = inputs(account)
        paths[account] = root/(account+"_PRODUCTION_FORMAL_LATEST.json")
        paths[account].write_bytes(seal(raw, ev, NOW))
    assert resolve(tmp_path, "2026-09-21")["state"] == "READY"
    result = orchestrate(*(json.loads(paths[k].read_bytes()) for k in ("O", "U")),
                         "2026-09-21", NOW, "2026-09-22", paths["O"], paths["U"])
    assert result["state"] == "WAIT_NO_BUY"
    assert len(result["commands"]) == 2
    assert all(x["kind"] == "SIGNAL" and x["at"] == "2026-09-21T17:29:00+08:00" for x in result["commands"])

@pytest.mark.parametrize("change", ["hash", "session", "account", "field_ref", "missing_time", "naive", "expired", "next"])
def test_invalid_evidence_fails_closed(change):
    raw, ev = inputs("O")
    if change == "hash": raw += b" "
    if change == "session": ev["target_session"] = "2026-09-22"
    if change == "account": ev["account"] = "U"
    if change == "field_ref": del ev["field_evidence"]["available_at"]
    if change == "missing_time": del ev["signal_timing"]["available_at"]
    if change == "naive": ev["signal_timing"]["cutoff"] = "2026-09-21T16:00:00"
    if change == "expired": ev["signal_timing"]["valid_until"] = "2026-09-21T17:29:01+08:00"
    if change == "next": ev["signal_timing"]["next_session"] = None
    with pytest.raises((ValueError, KeyError)):
        seal(raw, ev, NOW)

def test_output_and_retry_preserve_original_bytes(tmp_path):
    raw, ev = inputs("O")
    source, evidence, out = (tmp_path/x for x in ("raw.json", "evidence.json", "candidate.json"))
    source.write_bytes(raw)
    evidence.write_text(json.dumps(ev))
    first = write_candidate(source, evidence, out, NOW)
    assert write_candidate(source, evidence, out, "2026-09-21T17:31:00+08:00") == first
    assert source.read_bytes() == raw
    before = out.read_bytes()
    ev["signal_timing"]["valid_until"] = "2026-09-22T09:59:00+08:00"
    evidence.write_text(json.dumps(ev))
    with pytest.raises(ValueError, match="OUTPUT_CONFLICT"):
        write_candidate(source, evidence, out, NOW)
    assert out.read_bytes() == before
    with pytest.raises(ValueError, match="MUST_BE_SEPARATE"):
        write_candidate(source, evidence, source, NOW)

def test_cli_missing_evidence_never_creates_output(tmp_path):
    raw, ev = inputs("U")
    del ev["field_evidence"]["valid_until"]
    source, evidence, out = (tmp_path/x for x in ("raw.json", "ev.json", "out.json"))
    source.write_bytes(raw); evidence.write_text(json.dumps(ev))
    result = subprocess.run([sys.executable, "scripts/dsa_formal_timing_seal_v1.py",
        "--receipt", str(source), "--timing-evidence", str(evidence),
        "--now", NOW, "--out", str(out)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["state"] == "BLOCKED"
    assert not out.exists()

def test_cannot_reseal_existing_receipt():
    raw, ev = inputs("O")
    sealed = seal(raw, ev, NOW)
    ev["receipt_sha256"] = hashlib.sha256(sealed).hexdigest()
    with pytest.raises(ValueError, match="ALREADY_SEALED"):
        seal(sealed, ev, NOW)
