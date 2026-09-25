import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dsa_natural_parallel_receipt_resolver_v1 import resolve_runtime_receipt

SESSION = "2026-09-21"
SEALED = "2026-09-21T09:22:00+08:00"


def write(path: Path, payload: dict):
    path.write_text(json.dumps(payload), encoding="utf-8")


def receipt(finished="2026-09-21T10:01:00+08:00"):
    return {
        "session": SESSION,
        "shadow_simulation_only": True,
        "real_orders": 0,
        "finished_at": finished,
        "run_id": "TRI-DSA-SHADOW-20260921",
        "authority_commit": "a" * 40,
    }


def test_unique_same_session_receipt_passes(tmp_path):
    write(tmp_path / "ok.json", receipt())
    write(tmp_path / "other.json", {**receipt(), "session": "2026-09-18"})
    r = resolve_runtime_receipt(tmp_path, SESSION, SEALED)
    assert r["status"] == "PASS_UNIQUE_RUNTIME_RECEIPT"
    assert r["match_count"] == 1
    assert r["selected"]["path"].endswith("ok.json")


def test_missing_receipt_waits(tmp_path):
    r = resolve_runtime_receipt(tmp_path, SESSION, SEALED)
    assert r["status"] == "WAIT_RUNTIME_RECEIPT"
    assert r["selected"] is None


def test_ambiguous_receipts_fail_closed(tmp_path):
    write(tmp_path / "a.json", receipt("2026-09-21T10:01:00+08:00"))
    write(tmp_path / "b.json", receipt("2026-09-21T10:02:00+08:00"))
    r = resolve_runtime_receipt(tmp_path, SESSION, SEALED)
    assert r["status"] == "BLOCKED_AMBIGUOUS_RUNTIME_RECEIPTS"
    assert r["match_count"] == 2


def test_preseal_receipt_is_rejected(tmp_path):
    write(tmp_path / "old.json", receipt("2026-09-21T09:00:00+08:00"))
    r = resolve_runtime_receipt(tmp_path, SESSION, SEALED)
    assert r["status"] == "WAIT_RUNTIME_RECEIPT"


def test_non_shadow_or_real_order_receipts_are_rejected(tmp_path):
    a = receipt()
    a["shadow_simulation_only"] = False
    b = receipt()
    b["real_orders"] = 1
    write(tmp_path / "a.json", a)
    write(tmp_path / "b.json", b)
    r = resolve_runtime_receipt(tmp_path, SESSION, SEALED)
    assert r["status"] == "WAIT_RUNTIME_RECEIPT"
