"""Foundation-governed shared-resource primitives for DSA.

This module is model-agnostic and consumer-only. Foundation is the only global
authority for resource claims, logical-cycle ownership and paid reservations.
SQLite here is host-local defense-in-depth/idempotency state only.
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

FOUNDATION_TRUST_ROOT = Path("/etc/rupheal/foundation/resource-broker-public.pem")
CLAIM_SCHEMA = "foundation.resource-claim-receipt/v1"
CLAIM_READBACK_SCHEMA = "foundation.resource-claim-readback/v1"
QUOTA_SCHEMA = "foundation.quota-reservation-receipt/v1"
QUOTA_READBACK_SCHEMA = "foundation.quota-reservation-readback/v1"


class ResourceConflict(RuntimeError):
    """A fixed fail-closed resource contract error."""


@dataclass(frozen=True)
class ResourceClaim:
    resource_id: str
    claim_id: str
    run_id: str
    fencing_epoch: int
    task_id: str = ""
    worker_id: str = ""
    broker_state_hash: str = ""
    proof_verified: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResourceClaim":
        """Parse for compatibility only; parsing never establishes authority."""
        try:
            if value.get("schema") == CLAIM_SCHEMA:
                holder=value["holder"]
                return cls(
                    resource_id=str(value["resource_id"]),
                    claim_id=str(value["claim_id"]),
                    run_id=str(holder["job_id"]),
                    fencing_epoch=int(value["fencing_epoch"]),
                    task_id=str(holder["task_id"]),
                    worker_id=str(holder["worker_id"]),
                    broker_state_hash=str((value.get("broker_state") or {}).get("hash") or ""),
                    proof_verified=False,
                )
            # Legacy Foundation internal claim shape may be parsed for diagnostics,
            # but remains unverified and cannot cross a mutation boundary.
            claim = cls(
                resource_id=str(value["resource_id"]),
                claim_id=str(value["claim_id"]),
                run_id=str(value.get("run_id") or value.get("session_ref") or ""),
                fencing_epoch=int(value.get("fencing_epoch", value["epoch"])),
                task_id=str(value.get("task_id") or ""),
                worker_id=str(value.get("worker_id") or ""),
                proof_verified=False,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResourceConflict("RESOURCE_CLAIM_INVALID") from exc
        if not all((claim.resource_id, claim.claim_id, claim.run_id)) or claim.fencing_epoch < 1:
            raise ResourceConflict("RESOURCE_CLAIM_INVALID")
        return claim

    @classmethod
    def from_verified_artifacts(cls, receipt_path: str | Path, readback_path: str | Path,
                                signature_path: str | Path) -> "ResourceClaim":
        receipt=json.loads(Path(receipt_path).read_text())
        readback=_load_verified_readback(readback_path,signature_path,FOUNDATION_TRUST_ROOT)
        required={"schema","resource_id","claim_id","holder","fencing_epoch","acquired_at","expires_at","broker_state"}
        if required-receipt.keys() or receipt.get("schema")!=CLAIM_SCHEMA:
            raise ResourceConflict("FOUNDATION_CLAIM_RECEIPT_INVALID")
        holder=receipt.get("holder") or {}
        if any(not holder.get(x) for x in ("task_id","worker_id","job_id")):
            raise ResourceConflict("FOUNDATION_CLAIM_HOLDER_INVALID")
        state=receipt.get("broker_state") or {}
        if not state.get("hash"):
            raise ResourceConflict("FOUNDATION_BROKER_STATE_PROOF_REQUIRED")
        if readback.get("schema")!=CLAIM_READBACK_SCHEMA or readback.get("state")!="ACTIVE":
            raise ResourceConflict("FOUNDATION_CLAIM_READBACK_NOT_ACTIVE")
        bindings=("resource_id","claim_id","holder","fencing_epoch","expires_at","broker_state")
        if any(readback.get(x)!=receipt.get(x) for x in bindings):
            raise ResourceConflict("FOUNDATION_CLAIM_READBACK_BINDING_MISMATCH")
        return cls(
            str(receipt["resource_id"]),str(receipt["claim_id"]),str(holder["job_id"]),
            int(receipt["fencing_epoch"]),str(holder["task_id"]),str(holder["worker_id"]),
            str(state["hash"]),True
        )


@dataclass(frozen=True)
class FoundationReservation:
    resource_id: str
    run_id: str
    reservation_id: str
    reserved_units: Decimal
    idempotency_key: str
    broker_state_hash: str
    proof_verified: bool = False

    @classmethod
    def from_verified_artifacts(cls, receipt_path: str | Path, readback_path: str | Path,
                                signature_path: str | Path) -> "FoundationReservation":
        receipt=json.loads(Path(receipt_path).read_text())
        readback=_load_verified_readback(readback_path,signature_path,FOUNDATION_TRUST_ROOT)
        required={"schema","resource_id","run_id","reservation_id","reserved_units","idempotency_key","expires_at","broker_state"}
        if required-receipt.keys() or receipt.get("schema")!=QUOTA_SCHEMA:
            raise ResourceConflict("FOUNDATION_RESERVATION_RECEIPT_INVALID")
        state=receipt.get("broker_state") or {}
        if not state.get("hash"):
            raise ResourceConflict("FOUNDATION_BROKER_STATE_PROOF_REQUIRED")
        if readback.get("schema")!=QUOTA_READBACK_SCHEMA or readback.get("state")!="RESERVED":
            raise ResourceConflict("FOUNDATION_RESERVATION_NOT_ACTIVE")
        bindings=("resource_id","run_id","reservation_id","reserved_units","idempotency_key","expires_at","broker_state")
        if any(readback.get(x)!=receipt.get(x) for x in bindings):
            raise ResourceConflict("FOUNDATION_RESERVATION_BINDING_MISMATCH")
        try:
            units=Decimal(str(receipt["reserved_units"]))
        except (InvalidOperation,ValueError,TypeError) as exc:
            raise ResourceConflict("QUOTA_UNITS_INVALID") from exc
        if units<=0: raise ResourceConflict("QUOTA_UNITS_INVALID")
        return cls(str(receipt["resource_id"]),str(receipt["run_id"]),str(receipt["reservation_id"]),
                   units,str(receipt["idempotency_key"]),str(state["hash"]),True)


def _load_verified_readback(readback_path: str | Path, signature_path: str | Path,
                            trust_root: str | Path) -> dict[str, Any]:
    trust=Path(trust_root); readback=Path(readback_path); signature=Path(signature_path)
    if not trust.is_file() or not readback.is_file() or not signature.is_file():
        raise ResourceConflict("FOUNDATION_PROOF_REQUIRED")
    cp=subprocess.run(["openssl","pkeyutl","-verify","-rawin","-pubin","-inkey",str(trust),
                       "-sigfile",str(signature),"-in",str(readback)],
                      capture_output=True,text=True)
    if cp.returncode:
        raise ResourceConflict("FOUNDATION_PROOF_INVALID")
    value=json.loads(readback.read_text())
    if not isinstance(value,dict): raise ResourceConflict("FOUNDATION_READBACK_INVALID")
    return value


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


class DurableResourceState:
    """Host-local defense-in-depth state; never the global Broker authority."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS fences(
                resource_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, claim_id TEXT NOT NULL,
                broker_state_hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cycles(
                cycle_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, state TEXT NOT NULL,
                receipt_json TEXT);
              CREATE TABLE IF NOT EXISTS reservations(
                reservation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, reserved_units TEXT NOT NULL,
                consumed_units TEXT NOT NULL DEFAULT '0', state TEXT NOT NULL,
                broker_state_hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS quota_ops(
                idempotency_key TEXT PRIMARY KEY, reservation_id TEXT NOT NULL,
                operation TEXT NOT NULL, result_state TEXT NOT NULL);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def validate_claim(self, claim: ResourceClaim, expected_resource: str) -> None:
        if not claim.proof_verified or not claim.broker_state_hash:
            raise ResourceConflict("FOUNDATION_CLAIM_PROOF_REQUIRED")
        if claim.resource_id != expected_resource:
            raise ResourceConflict("RESOURCE_CLAIM_SCOPE_MISMATCH")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT epoch,claim_id,broker_state_hash FROM fences WHERE resource_id=?",
                           (claim.resource_id,)).fetchone()
            if row and claim.fencing_epoch < row["epoch"]:
                db.rollback(); raise ResourceConflict("STALE_FENCING_EPOCH")
            if row and claim.fencing_epoch == row["epoch"] and (
                    claim.claim_id != row["claim_id"] or claim.broker_state_hash != row["broker_state_hash"]):
                db.rollback(); raise ResourceConflict("FENCING_EPOCH_CLAIM_CONFLICT")
            db.execute("INSERT INTO fences(resource_id,epoch,claim_id,broker_state_hash) VALUES(?,?,?,?) "
                       "ON CONFLICT(resource_id) DO UPDATE SET epoch=excluded.epoch,claim_id=excluded.claim_id,"
                       "broker_state_hash=excluded.broker_state_hash",
                       (claim.resource_id,claim.fencing_epoch,claim.claim_id,claim.broker_state_hash))
            db.commit()

    @staticmethod
    def logical_cycle_key(target_session: str, track: str, contract_hash: str) -> str:
        if not target_session or track not in {"O", "U"} or len(contract_hash) != 64:
            raise ResourceConflict("LOGICAL_CYCLE_INPUT_INVALID")
        return canonical_hash({"target_session": target_session, "track": track, "contract_hash": contract_hash})

    def begin_cycle(self, cycle_key: str, run_id: str, claim: ResourceClaim) -> dict[str, Any]:
        # Global ownership is Foundation. Without proof, this host must never execute.
        if not claim.proof_verified:
            return {"action":"WAIT_FOUNDATION_GRANT","owner_run_id":None}
        self.validate_claim(claim, "SCHEDULE:DSA:DAILY_FORMAL")
        # Foundation request identity must be the deterministic logical-cycle key.
        # This makes schedule/push/manual transports converge on one Broker request.
        if claim.run_id != cycle_key or run_id != cycle_key:
            raise ResourceConflict("FOUNDATION_LOGICAL_CYCLE_BINDING_MISMATCH")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM cycles WHERE cycle_key=?", (cycle_key,)).fetchone()
            if not row:
                db.execute("INSERT INTO cycles VALUES(?,?,?,NULL)", (cycle_key,run_id,"RUNNING"));db.commit()
                return {"action":"EXECUTE","owner_run_id":run_id}
            db.commit()
            return {"action":"NOOP" if row["state"]=="COMPLETE" else "ATTACH_WAIT",
                    "owner_run_id":row["run_id"],"receipt":json.loads(row["receipt_json"]) if row["receipt_json"] else None}

    def complete_cycle(self, cycle_key: str, run_id: str, receipt: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT run_id,state FROM cycles WHERE cycle_key=?", (cycle_key,)).fetchone()
            if not row or row["run_id"]!=run_id or row["state"]!="RUNNING":
                db.rollback(); raise ResourceConflict("LOGICAL_CYCLE_NOT_OWNED")
            db.execute("UPDATE cycles SET state='COMPLETE',receipt_json=? WHERE cycle_key=?",
                       (json.dumps(receipt,sort_keys=True),cycle_key));db.commit()

    def advance_latest(self, pointer: Path, receipt: dict[str, Any], claim: ResourceClaim) -> str:
        self.validate_claim(claim, "GIT:DSA:FORMAL_LATEST_POINTERS")
        required={"target_session","generation","source_hash"}
        if not required<=receipt.keys() or len(str(receipt["source_hash"]))!=64:
            raise ResourceConflict("LATEST_RECEIPT_INVALID")
        current=json.loads(pointer.read_text()) if pointer.exists() else None
        rank=(str(receipt["target_session"]),int(receipt["generation"]))
        old_rank=(str(current["target_session"]),int(current["generation"])) if current else None
        if old_rank and rank<old_rank:return "STALE_RECEIPT_PRESERVED"
        if old_rank==rank and current["source_hash"]!=receipt["source_hash"]:
            raise ResourceConflict("LATEST_SAME_GENERATION_CONFLICT")
        if current==receipt:return "LATEST_IDEMPOTENT"
        pointer.parent.mkdir(parents=True,exist_ok=True)
        temp=pointer.with_suffix(pointer.suffix+".tmp")
        temp.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n");temp.replace(pointer)
        return "LATEST_ADVANCED"

    def publish_projection(self, receipts_dir: Path, pointer: Path,
                           receipt: dict[str, Any], claim: ResourceClaim) -> str:
        self.validate_claim(claim, "GIT:DSA:FORMAL_LATEST_POINTERS")
        receipt_id=canonical_hash(receipt);receipts_dir.mkdir(parents=True,exist_ok=True)
        immutable=receipts_dir/f"{receipt['target_session']}-G{int(receipt['generation']):08d}-{receipt_id}.json"
        encoded=json.dumps(receipt,sort_keys=True,indent=2)+"\n"
        try:
            with immutable.open("x",encoding="utf-8") as stream:stream.write(encoded)
        except FileExistsError:
            if immutable.read_text(encoding="utf-8")!=encoded:
                raise ResourceConflict("IMMUTABLE_RECEIPT_CONFLICT")
        return self.advance_latest(pointer,receipt,claim)

    def configure_quota(self, resource_id: str, available: Decimal) -> None:
        raise ResourceConflict("FOUNDATION_GLOBAL_QUOTA_AUTHORITY_REQUIRED")

    def reserve_quota(self, claim: ResourceClaim, reservation_id: str, units: Decimal,
                      idempotency_key: str) -> dict[str, str]:
        raise ResourceConflict("FOUNDATION_RESERVATION_PROOF_REQUIRED")

    def consume_foundation_reservation(self, reservation: FoundationReservation, operation: str,
                                       idempotency_key: str, units: Decimal | None = None) -> str:
        if not reservation.proof_verified:
            raise ResourceConflict("FOUNDATION_RESERVATION_PROOF_REQUIRED")
        if operation not in {"consume","settle","release","expire"}:
            raise ResourceConflict("QUOTA_OPERATION_INVALID")
        amount=reservation.reserved_units if units is None else Decimal(str(units))
        if amount<0 or amount>reservation.reserved_units:
            raise ResourceConflict("QUOTA_SETTLEMENT_INVALID")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior=db.execute("SELECT * FROM quota_ops WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if prior:
                db.commit()
                if prior["reservation_id"]!=reservation.reservation_id or prior["operation"]!=operation:
                    raise ResourceConflict("QUOTA_IDEMPOTENCY_CONFLICT")
                return prior["result_state"]
            row=db.execute("SELECT * FROM reservations WHERE reservation_id=?",
                           (reservation.reservation_id,)).fetchone()
            if not row:
                db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?)",
                           (reservation.reservation_id,reservation.run_id,str(reservation.reserved_units),
                            "0","RESERVED",reservation.broker_state_hash))
                row=db.execute("SELECT * FROM reservations WHERE reservation_id=?",
                               (reservation.reservation_id,)).fetchone()
            if row["run_id"]!=reservation.run_id or row["broker_state_hash"]!=reservation.broker_state_hash:
                db.rollback(); raise ResourceConflict("QUOTA_RESERVATION_CLAIM_MISMATCH")
            if row["state"] not in {"RESERVED","PARTIALLY_CONSUMED"}:
                db.rollback(); raise ResourceConflict("QUOTA_ALREADY_SETTLED")
            consumed=Decimal(row["consumed_units"])
            if operation=="consume":
                if amount<=0 or consumed+amount>reservation.reserved_units:
                    db.rollback(); raise ResourceConflict("QUOTA_EXCEEDED")
                consumed+=amount
                state="CONSUMED" if consumed==reservation.reserved_units else "PARTIALLY_CONSUMED"
            elif operation=="settle":
                state="SETTLED"
            else:
                state=operation.upper()+"D"
            db.execute("UPDATE reservations SET consumed_units=?,state=? WHERE reservation_id=?",
                       (str(consumed),state,reservation.reservation_id))
            db.execute("INSERT INTO quota_ops VALUES(?,?,?,?)",
                       (idempotency_key,reservation.reservation_id,operation,state))
            db.commit();return state

    def settle_quota(self, claim: ResourceClaim, reservation_id: str, operation: str,
                     idempotency_key: str, units: Decimal | None = None) -> str:
        raise ResourceConflict("FOUNDATION_RESERVATION_PROOF_REQUIRED")


def git_cas_push(repo: Path, remote: str, ref: str, observed_base_sha: str,
                 commit_sha: str, expected_tree_sha: str, claim: ResourceClaim,
                 state: DurableResourceState) -> dict[str, str]:
    state.validate_claim(claim, "GIT:DSA:NATIVE_PRIVATE_BRANCH")
    def git(*args: str) -> str:
        return subprocess.check_output(["git",*args],cwd=repo,text=True,stderr=subprocess.STDOUT).strip()
    remote_before=git("ls-remote",remote,ref).split();actual=remote_before[0] if remote_before else ""
    if actual!=observed_base_sha:raise ResourceConflict("GIT_OBSERVED_BASE_CONFLICT")
    if git("show","-s","--format=%T",commit_sha)!=expected_tree_sha:
        raise ResourceConflict("GIT_EXPECTED_TREE_CONFLICT")
    cp=subprocess.run(["git","push","--porcelain",remote,f"{commit_sha}:{ref}"],cwd=repo,text=True,capture_output=True)
    if cp.returncode:raise ResourceConflict("GIT_PUSH_CONFLICT_RECONCILE")
    after=git("ls-remote",remote,ref).split()
    if not after or after[0]!=commit_sha:raise ResourceConflict("GIT_POSTWRITE_READBACK_MISMATCH")
    return {"status":"GIT_CAS_WRITTEN","ref":ref,"before":actual,"after":commit_sha,"force":"false"}
