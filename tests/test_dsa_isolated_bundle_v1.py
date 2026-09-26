from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.dsa_isolated_bundle_v1 import build_bundle
from src.services.dsa_prediction_ledger import canonical_hash


CODE_SHA = "2" * 40


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def source_fixture(tmp_path: Path):
    root = tmp_path / "repo"
    o = root / "O.json"
    u = root / "U.json"
    entry = root / "entry.json"
    journal = root / "journal.json"

    o_receipt = {
        "target_session": "2026-09-28",
        "status": "PASS_FORMAL_O_DECISION_WAIT",
    }
    u_receipt = {
        "target_session": "2026-09-28",
        "state": "PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
    }
    write_json(o, o_receipt)
    write_json(u, u_receipt)
    write_json(entry, {"O": {}, "U": {}})
    journal_value = {
        "schema_version": 1,
        "config": {"accounts": {"O": "1", "U": "1"}},
        "config_hash": "fixture",
        "commands": [],
    }
    write_json(journal, journal_value)
    raw = journal.read_bytes()
    return {
        "root": root,
        "o": o,
        "u": u,
        "entry": entry,
        "journal": journal,
        "journal_raw": raw,
        "journal_blob": git_blob(raw),
        "journal_hash": canonical_hash(journal_value),
        "o_receipt": o_receipt,
        "u_receipt": u_receipt,
    }


def resolver_for(fx: dict, *, missing: str | None = None):
    def _resolve(root: Path, target: str):
        def row(account: str):
            if account == missing:
                return {
                    "path": None,
                    "receipt": None,
                    "checked": [{"status": "MISSING"}],
                }
            path = fx[account.lower()]
            receipt = fx[f"{account.lower()}_receipt"]
            return {
                "path": str(path),
                "receipt": receipt,
                "checked": [{"status": "MATCH", "session": target}],
            }

        ready = missing is None
        return {
            "schema_version": 1,
            "target_session": target,
            "state": "READY" if ready else "MISSING_FORMAL_RECEIPT",
            "O": row("O"),
            "U": row("U"),
            "orchestrator_permitted": ready,
            "real_orders": 0,
        }

    return _resolve


def fake_orchestrator(
    o,
    u,
    target_session,
    now,
    next_session,
    o_path,
    u_path,
    entry,
    journal_configured,
):
    assert journal_configured is True
    assert target_session == "2026-09-28"
    return {
        "schema_version": 1,
        "state": "WAIT_NO_BUY",
        "tracks": {
            "O": {"state": "WAIT"},
            "U": {"state": "WAIT"},
        },
        "entry_blockers": {"O": [], "U": []},
        "commands": [
            {
                "id": "wait-fixture",
                "account": "O",
                "kind": "SIGNAL",
                "at": now,
                "signal": {"passed": False},
            }
        ],
        "real_orders": 0,
    }


def fake_replayer(raw, expected_blob, expected_hash, commands):
    assert git_blob(raw) == expected_blob
    source = json.loads(raw)
    assert canonical_hash(source) == expected_hash
    return {
        "state": "ISOLATED_NO_FILL",
        "candidate": source,
        "summary": {"scope": "forward_simulation"},
        "events": {"O": [], "U": []},
        "source_hash": expected_hash,
        "candidate_hash": expected_hash,
        "noop_ids": [],
        "pending_count": len(commands),
        "new_fills": 0,
        "formal_writes": 0,
        "natural_cycle_credit": 0,
    }


def kwargs(fx: dict, out_dir: Path) -> dict:
    return {
        "root": fx["root"],
        "target_session": "2026-09-28",
        "now": "2026-09-28T09:31:00+08:00",
        "next_session": "2026-09-29",
        "verification_clock": "2026-09-28T09:32:00+08:00",
        "entry_evidence": fx["entry"],
        "journal": fx["journal"],
        "expected_blob": fx["journal_blob"],
        "expected_hash": fx["journal_hash"],
        "out_dir": out_dir,
        "run_id": "RECOVERY-001",
        "code_sha": CODE_SHA,
        "input_classification": "REAL",
        "resolver": resolver_for(fx),
        "orchestrator": fake_orchestrator,
        "replayer": fake_replayer,
    }


def test_builds_complete_bundle_without_source_mutation(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    result = build_bundle(**kwargs(fx, out))

    assert result["state"] == "READY_ISOLATED_BUNDLE"
    assert result["natural_cycle_credit"] == 0
    assert result["formal_writes"] == 0
    assert result["real_orders"] == 0
    assert result["production_pointer_switched"] is False
    assert result["journal_source_unchanged"] is True
    assert fx["journal"].read_bytes() == fx["journal_raw"]
    assert (out / "manifest.json").is_file()
    assert (out / "candidate-journal.json").is_file()


def test_exact_retry_is_noop_and_preserves_output_bytes(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    first = build_bundle(**kwargs(fx, out))
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}

    second = build_bundle(**kwargs(fx, out))
    after = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}

    assert first["spec_sha256"] == second["spec_sha256"]
    assert second["delivery_noop"] is True
    assert before == after


def test_changed_spec_is_rejected_against_existing_output(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    build_bundle(**kwargs(fx, out))

    changed = kwargs(fx, out)
    changed["verification_clock"] = "2026-09-28T09:33:00+08:00"
    with pytest.raises(ValueError, match="SPEC_HASH_MISMATCH"):
        build_bundle(**changed)


def test_compatible_partial_directory_resumes(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    partial = out.with_name(out.name + ".partial")
    partial.mkdir()
    # A crash may leave no complete marker. The next attempt may populate
    # missing files, but write_once will reject any incompatible existing bytes.
    result = build_bundle(**kwargs(fx, out))
    assert result["state"] == "READY_ISOLATED_BUNDLE"
    assert out.is_dir()
    assert not partial.exists()


def test_mismatched_partial_output_fails_closed(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    partial = out.with_name(out.name + ".partial")
    partial.mkdir()
    (partial / "bundle-spec.json").write_text('{"wrong":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="OUTPUT_DRIFT:bundle-spec.json"):
        build_bundle(**kwargs(fx, out))
    assert not out.exists()


def test_missing_track_is_visible_blocked_and_other_track_preserved(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    call = kwargs(fx, out)
    call["resolver"] = resolver_for(fx, missing="U")
    result = build_bundle(**call)

    assert result["state"] == "BLOCKED_INPUTS"
    assert result["tracks"]["O"]["available"] is True
    assert result["tracks"]["O"]["sha256"]
    assert result["tracks"]["U"]["available"] is False
    assert result["tracks"]["U"]["sha256"] is None
    assert result["natural_cycle_credit"] == 0
    assert not (out / "candidate-journal.json").exists()


@pytest.mark.parametrize("classification", ["SYNTHETIC", "HISTORICAL_REPLAY"])
def test_non_real_inputs_never_receive_natural_cycle_credit(
    tmp_path: Path, classification: str
):
    fx = source_fixture(tmp_path)
    out = tmp_path / f"bundle-{classification}"
    call = kwargs(fx, out)
    call["input_classification"] = classification
    result = build_bundle(**call)
    assert result["input_classification"] == classification
    assert result["natural_cycle_credit"] == 0


def test_journal_identity_mismatch_fails_before_output(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    call = kwargs(fx, out)
    call["expected_blob"] = "0" * 40
    with pytest.raises(ValueError, match="JOURNAL_GIT_BLOB_MISMATCH"):
        build_bundle(**call)
    assert not out.exists()


def test_incomplete_final_directory_is_not_accepted(tmp_path: Path):
    fx = source_fixture(tmp_path)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "bundle-spec.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COMPLETE_OUTPUT_MARKERS_MISSING"):
        build_bundle(**kwargs(fx, out))
