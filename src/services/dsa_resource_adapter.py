"""Foundation-governed shared-resource primitives for DSA.

This module is deliberately model-agnostic.  It turns broker grants into local,
durable guards; it never acquires a resource, calls a provider, or promotes a
runtime by itself.  SQLite transactions provide the durable single-flight and
quota semantics required between workflow transports on one adapter host.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any


class ResourceConflict(RuntimeError):
    """A fixed fail-closed resource contract error."""


@dataclass(frozen=True)
class ResourceClaim:
    resource_id: str
    claim_id: str
    run_id: str
    fencing_epoch: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResourceClaim":
        try:
            claim = cls(
                resource_id=str(value["resource_id"]),
                claim_id=str(value["claim_id"]),
                run_id=str(value["run_id"]),
                fencing_epoch=int(value["fencing_epoch"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResourceConflict("RESOURCE_CLAIM_INVALID") from exc
        if not all((claim.resource_id, claim.claim_id, claim.run_id)) or claim.fencing_epoch < 1:
            raise ResourceConflict("RESOURCE_CLAIM_INVALID")
        return claim


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


class DurableResourceState:
    """Transactional adapter state.  One database must be shared by all DSA writers."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS fences(
                resource_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, claim_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cycles(
                cycle_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, state TEXT NOT NULL,
                receipt_json TEXT);
              CREATE TABLE IF NOT EXISTS reservations(
                reservation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, units TEXT NOT NULL,
                consumed TEXT NOT NULL DEFAULT '0', state TEXT NOT NULL,
                fencing_epoch INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE);
              CREATE TABLE IF NOT EXISTS quota(
                resource_id TEXT PRIMARY KEY, available TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS quota_ops(
                idempotency_key TEXT PRIMARY KEY, reservation_id TEXT NOT NULL,
                operation TEXT NOT NULL, result_state TEXT NOT NULL);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def validate_claim(self, claim: ResourceClaim, expected_resource: str) -> None:
        if claim.resource_id != expected_resource:
            raise ResourceConflict("RESOURCE_CLAIM_SCOPE_MISMATCH")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT epoch,claim_id FROM fences WHERE resource_id=?", (claim.resource_id,)).fetchone()
            if row and claim.fencing_epoch < row["epoch"]:
                db.rollback(); raise ResourceConflict("STALE_FENCING_EPOCH")
            if row and claim.fencing_epoch == row["epoch"] and claim.claim_id != row["claim_id"]:
                db.rollback(); raise ResourceConflict("FENCING_EPOCH_CLAIM_CONFLICT")
            db.execute("INSERT INTO fences(resource_id,epoch,claim_id) VALUES(?,?,?) "
                       "ON CONFLICT(resource_id) DO UPDATE SET epoch=excluded.epoch,claim_id=excluded.claim_id",
                       (claim.resource_id, claim.fencing_epoch, claim.claim_id))
            db.commit()

    @staticmethod
    def logical_cycle_key(target_session: str, track: str, contract_hash: str) -> str:
        if not target_session or track not in {"O", "U"} or len(contract_hash) != 64:
            raise ResourceConflict("LOGICAL_CYCLE_INPUT_INVALID")
        return canonical_hash({"target_session": target_session, "track": track, "contract_hash": contract_hash})

    def begin_cycle(self, cycle_key: str, run_id: str, claim: ResourceClaim) -> dict[str, Any]:
        self.validate_claim(claim, "SCHEDULE:DSA:DAILY_FORMAL")
        if claim.run_id != run_id: raise ResourceConflict("RESOURCE_CLAIM_RUN_MISMATCH")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM cycles WHERE cycle_key=?", (cycle_key,)).fetchone()
            if not row:
                db.execute("INSERT INTO cycles VALUES(?,?,?,NULL)", (cycle_key, run_id, "RUNNING")); db.commit()
                return {"action": "EXECUTE", "owner_run_id": run_id}
            db.commit()
            return {"action": "NOOP" if row["state"] == "COMPLETE" else "ATTACH_WAIT",
                    "owner_run_id": row["run_id"], "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None}

    def complete_cycle(self, cycle_key: str, run_id: str, receipt: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT run_id,state FROM cycles WHERE cycle_key=?", (cycle_key,)).fetchone()
            if not row or row["run_id"] != run_id or row["state"] != "RUNNING":
                db.rollback(); raise ResourceConflict("LOGICAL_CYCLE_NOT_OWNED")
            db.execute("UPDATE cycles SET state='COMPLETE',receipt_json=? WHERE cycle_key=?",
                       (json.dumps(receipt, sort_keys=True), cycle_key)); db.commit()

    def advance_latest(self, pointer: Path, receipt: dict[str, Any], claim: ResourceClaim) -> str:
        self.validate_claim(claim, "GIT:DSA:FORMAL_LATEST_POINTERS")
        required = {"target_session", "generation", "source_hash"}
        if not required <= receipt.keys() or len(str(receipt["source_hash"])) != 64:
            raise ResourceConflict("LATEST_RECEIPT_INVALID")
        current = json.loads(pointer.read_text()) if pointer.exists() else None
        rank = (str(receipt["target_session"]), int(receipt["generation"]))
        old_rank = (str(current["target_session"]), int(current["generation"])) if current else None
        if old_rank and rank < old_rank:
            return "STALE_RECEIPT_PRESERVED"
        if old_rank == rank and current["source_hash"] != receipt["source_hash"]:
            raise ResourceConflict("LATEST_SAME_GENERATION_CONFLICT")
        if current == receipt:
            return "LATEST_IDEMPOTENT"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temp = pointer.with_suffix(pointer.suffix + ".tmp")
        temp.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        temp.replace(pointer)
        return "LATEST_ADVANCED"

    def publish_projection(self, receipts_dir: Path, pointer: Path,
                           receipt: dict[str, Any], claim: ResourceClaim) -> str:
        """Persist the authority receipt before updating its derived projection."""
        self.validate_claim(claim, "GIT:DSA:FORMAL_LATEST_POINTERS")
        receipt_id = canonical_hash(receipt)
        receipts_dir.mkdir(parents=True, exist_ok=True)
        immutable = receipts_dir / f"{receipt['target_session']}-G{int(receipt['generation']):08d}-{receipt_id}.json"
        encoded = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
        try:
            with immutable.open("x", encoding="utf-8") as stream: stream.write(encoded)
        except FileExistsError:
            if immutable.read_text(encoding="utf-8") != encoded:
                raise ResourceConflict("IMMUTABLE_RECEIPT_CONFLICT")
        return self.advance_latest(pointer, receipt, claim)

    def configure_quota(self, resource_id: str, available: Decimal) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO quota VALUES(?,?) ON CONFLICT(resource_id) DO UPDATE SET available=excluded.available",
                       (resource_id, str(available)))

    def reserve_quota(self, claim: ResourceClaim, reservation_id: str, units: Decimal,
                      idempotency_key: str) -> dict[str, str]:
        self.validate_claim(claim, "API:DEEPSEEK:DSA")
        try: units = Decimal(units)
        except InvalidOperation as exc: raise ResourceConflict("QUOTA_UNITS_INVALID") from exc
        if units <= 0: raise ResourceConflict("QUOTA_UNITS_INVALID")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM reservations WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if old:
                db.commit()
                if old["reservation_id"] != reservation_id or Decimal(old["units"]) != units:
                    raise ResourceConflict("QUOTA_IDEMPOTENCY_CONFLICT")
                return dict(old)
            q = db.execute("SELECT available FROM quota WHERE resource_id=?", (claim.resource_id,)).fetchone()
            if not q or Decimal(q["available"]) < units:
                db.rollback(); raise ResourceConflict("QUOTA_INSUFFICIENT")
            db.execute("UPDATE quota SET available=? WHERE resource_id=?", (str(Decimal(q["available"])-units), claim.resource_id))
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
                       (reservation_id, claim.run_id, str(units), "0", "RESERVED", claim.fencing_epoch, idempotency_key))
            db.commit()
            return {"reservation_id": reservation_id, "state": "RESERVED", "units": str(units)}

    def settle_quota(self, claim: ResourceClaim, reservation_id: str, operation: str,
                     idempotency_key: str, units: Decimal | None = None) -> str:
        self.validate_claim(claim, "API:DEEPSEEK:DSA")
        if operation not in {"consume", "release", "expire"}: raise ResourceConflict("QUOTA_OPERATION_INVALID")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM quota_ops WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if prior:
                db.commit()
                if prior["reservation_id"] != reservation_id or prior["operation"] != operation:
                    raise ResourceConflict("QUOTA_IDEMPOTENCY_CONFLICT")
                return prior["result_state"]
            row = db.execute("SELECT * FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if not row: db.rollback(); raise ResourceConflict("QUOTA_RESERVATION_UNKNOWN")
            if claim.run_id != row["run_id"] or claim.fencing_epoch < row["fencing_epoch"]:
                db.rollback(); raise ResourceConflict("QUOTA_RESERVATION_CLAIM_MISMATCH")
            if row["state"] != "RESERVED": db.rollback(); raise ResourceConflict("QUOTA_ALREADY_SETTLED")
            reserved = Decimal(row["units"]); amount = reserved if units is None else Decimal(units)
            if amount < 0 or amount > reserved: db.rollback(); raise ResourceConflict("QUOTA_SETTLEMENT_INVALID")
            state = "CONSUMED" if operation == "consume" else operation.upper() + "D"
            refund = reserved - amount if operation == "consume" else reserved
            if refund:
                q = db.execute("SELECT available FROM quota WHERE resource_id='API:DEEPSEEK:DSA'").fetchone()
                db.execute("UPDATE quota SET available=? WHERE resource_id='API:DEEPSEEK:DSA'", (str(Decimal(q[0])+refund),))
            db.execute("UPDATE reservations SET consumed=?,state=? WHERE reservation_id=?", (str(amount if operation == "consume" else 0), state, reservation_id))
            db.execute("INSERT INTO quota_ops VALUES(?,?,?,?)", (idempotency_key,reservation_id,operation,state))
            db.commit(); return state


def git_cas_push(repo: Path, remote: str, ref: str, observed_base_sha: str,
                 commit_sha: str, expected_tree_sha: str, claim: ResourceClaim,
                 state: DurableResourceState) -> dict[str, str]:
    """Non-force shared-ref CAS: verify base/tree, push, then read back.

    Concurrent fast-forward pushes from the same base cannot both succeed.  A
    rejection is surfaced for caller re-read/reconciliation, never rebased.
    """
    state.validate_claim(claim, "GIT:DSA:NATIVE_PRIVATE_BRANCH")
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.STDOUT).strip()
    remote_before = git("ls-remote", remote, ref).split()
    actual = remote_before[0] if remote_before else ""
    if actual != observed_base_sha: raise ResourceConflict("GIT_OBSERVED_BASE_CONFLICT")
    if git("show", "-s", "--format=%T", commit_sha) != expected_tree_sha:
        raise ResourceConflict("GIT_EXPECTED_TREE_CONFLICT")
    cp = subprocess.run(["git", "push", "--porcelain", remote, f"{commit_sha}:{ref}"], cwd=repo,
                        text=True, capture_output=True)
    if cp.returncode: raise ResourceConflict("GIT_PUSH_CONFLICT_RECONCILE")
    after = git("ls-remote", remote, ref).split()
    if not after or after[0] != commit_sha: raise ResourceConflict("GIT_POSTWRITE_READBACK_MISMATCH")
    return {"status": "GIT_CAS_WRITTEN", "ref": ref, "before": actual, "after": commit_sha, "force": "false"}
