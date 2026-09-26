"""Replay candidate commands on a pinned journal copy, never a remote writer.

The caller supplies independently read-back Git blob and canonical hashes.
Source provenance is a prerequisite, not inferred from a filename.
"""
from __future__ import annotations

import copy
import argparse
import hashlib
import json
from pathlib import Path

from scripts.dsa_production_orchestrator_v1 import filter_commands_against_journal
from src.services import dsa_simulation_ledger as ledger
from src.services.dsa_prediction_ledger import canonical_hash


def replay_candidate(raw, expected_blob, expected_hash, commands):
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != expected_blob:
        raise ValueError("JOURNAL_GIT_BLOB_MISMATCH")
    source = json.loads(raw)
    if canonical_hash(source) != expected_hash:
        raise ValueError("JOURNAL_CANONICAL_HASH_MISMATCH")
    ledger.replay(source)
    pending, noop = filter_commands_against_journal(commands, source)
    candidate = copy.deepcopy(source)
    before_counts = {k: len(v["events"]) for k, v in ledger.replay(source).items()}
    for command in pending:
        # New isolated commands must use the versioned path. Legacy source
        # commands retain their original replay semantics.
        if command["kind"] == "SIGNAL" and command["signal"].get("passed"):
            if not command["signal"].get("entry_policy"):
                raise ValueError("UNBOUND_NEW_BUY_SIGNAL")
        if command["kind"] == "ENTRY":
            state = ledger.replay(candidate)[command["account"]]
            signal = state["signals"].get(command.get("signal_id"), {}).get("original", {})
            if not signal.get("entry_policy"):
                raise ValueError("UNBOUND_NEW_ENTRY")
        candidate = ledger.append(candidate, command)
    state = ledger.replay(candidate)
    events = {k: v["events"][before_counts[k]:] for k, v in state.items()}
    rejected = any(e["kind"] in ("NO_TRADE", "ENTRY_WAIT") for es in events.values() for e in es)
    fills = sum(e["kind"] == "BUY" for es in events.values() for e in es)
    return {"state": "ISOLATED_POLICY_REJECTED" if rejected else
            "ISOLATED_FILL_REPLAYED" if fills else "ISOLATED_NO_FILL",
            "candidate": candidate, "summary": ledger.summary(candidate), "events": events,
            "source_hash": canonical_hash(source), "candidate_hash": canonical_hash(candidate),
            "noop_ids": noop, "pending_count": len(pending), "new_fills": fills,
            "formal_writes": 0, "natural_cycle_credit": 0}


def main():
    from scripts.dsa_formal_receipt_resolver_v1 import resolve
    from scripts.dsa_production_orchestrator_v1 import orchestrate
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--target-session", required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--next-session", required=True)
    ap.add_argument("--entry-evidence", type=Path, required=True)
    ap.add_argument("--journal", type=Path, required=True)
    ap.add_argument("--expected-blob", required=True)
    ap.add_argument("--expected-hash", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    raw = a.journal.read_bytes()
    # Validate source identity before resolving or generating any commands.
    replay_candidate(raw, a.expected_blob, a.expected_hash, [])
    resolved = resolve(a.root, a.target_session)
    if resolved["state"] != "READY":
        raise ValueError("CURRENT_FORMAL_INPUTS_UNAVAILABLE")
    result = orchestrate(resolved["O"]["receipt"], resolved["U"]["receipt"],
        a.target_session, a.now, a.next_session, Path(resolved["O"]["path"]),
        Path(resolved["U"]["path"]), json.loads(a.entry_evidence.read_bytes()), True)
    if result["state"] not in ("READY_FOR_ENTRY_V1_REPLAY", "WAIT_NO_BUY"):
        print(json.dumps({"state": result["state"], "blockers": result["entry_blockers"],
                          "formal_writes": 0, "natural_cycle_credit": 0}))
        return 2
    replayed = replay_candidate(raw, a.expected_blob, a.expected_hash, result["commands"])
    # Never create/reset a source journal or overwrite any prior output.
    a.out_dir.mkdir(parents=True, exist_ok=False)
    for name, obj in (("candidate-journal.json", replayed.pop("candidate")),
                      ("orchestrator.json", result), ("replay.json", replayed)):
        with (a.out_dir/name).open("x", encoding="utf-8") as stream:
            json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    if a.journal.read_bytes() != raw:
        raise ValueError("SOURCE_CHANGED_DURING_REPLAY")
    print(json.dumps({k: replayed[k] for k in ("state", "new_fills", "formal_writes", "natural_cycle_credit")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
