import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dsa_natural_parallel_prewindow_v1 import seal_inputs


def write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def inputs(tmp_path: Path):
    return (
        write(tmp_path, "o.json", {"target_session": "2026-09-18"}),
        write(tmp_path, "u.json", {"target_session": "2026-09-18"}),
        write(tmp_path, "journal.json", {"config_hash": "a" * 64, "commands": []}),
    )


def test_seals_three_inputs_without_runtime_writes(tmp_path):
    op, up, jp = inputs(tmp_path)
    result = seal_inputs(
        op,
        up,
        jp,
        "2026-09-18",
        "2026-09-21",
        "2026-09-21T09:25:00+08:00",
        sealed_at="2026-09-21T09:24:00+08:00",
    )
    assert result["status"] == "PASS_SAME_CUTOFF_INPUTS"
    assert set(result["input_sha256"]) == {"o_receipt", "u_receipt", "foundation_journal"}
    assert result["input_available_at"]["o_receipt"] == result["sealed_at"]
    assert result["read_only_contract"]["authoritative_foundation_journal_writes"] == 0
    assert result["read_only_contract"]["candidate_journal_writes"] == 0
    assert result["read_only_contract"]["real_orders"] == 0
    assert result["read_only_contract"]["comparison_execution"] is False


def test_rejects_seal_after_cutoff(tmp_path):
    op, up, jp = inputs(tmp_path)
    with pytest.raises(ValueError, match="PREWINDOW_SEAL_AFTER_CUTOFF"):
        seal_inputs(
            op,
            up,
            jp,
            "2026-09-18",
            "2026-09-21",
            "2026-09-21T09:25:00+08:00",
            sealed_at="2026-09-21T09:25:01+08:00",
        )


def test_rejects_naive_cutoff(tmp_path):
    op, up, jp = inputs(tmp_path)
    with pytest.raises(ValueError, match="PREWINDOW_CUTOFF_TIMEZONE_REQUIRED"):
        seal_inputs(
            op,
            up,
            jp,
            "2026-09-18",
            "2026-09-21",
            "2026-09-21T09:25:00",
            sealed_at="2026-09-21T09:24:00+08:00",
        )


def test_rejects_missing_input(tmp_path):
    op, up, jp = inputs(tmp_path)
    jp.unlink()
    with pytest.raises(ValueError, match="PREWINDOW_INPUT_MISSING:foundation_journal"):
        seal_inputs(
            op,
            up,
            jp,
            "2026-09-18",
            "2026-09-21",
            "2026-09-21T09:25:00+08:00",
            sealed_at="2026-09-21T09:24:00+08:00",
        )
