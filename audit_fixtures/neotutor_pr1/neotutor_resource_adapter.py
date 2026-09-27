#!/usr/bin/env python3
"""Fail-closed consumer adapter for Foundation-managed NeoTutor resources.

This module is deliberately not a broker.  It validates a Foundation grant and
maintains an atomic, job-scoped child-resource ledger for safe local cleanup.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from typing import Any, Iterator

RESOURCE = "LOCAL:NEOTUTOR:ACCEPTANCE_RUNTIME"
QUOTA_RESOURCE = "API:OPENAI:NEOTUTOR"
STABLE = Path("/home/alienware/NeoTutor")
STATES = {"ACTIVE", "DRAINING", "CLEANUP", "READBACK", "RELEASED", "QUARANTINED"}

class ResourceError(RuntimeError):
    pass

def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResourceError("claim timestamps must include a timezone")
    return parsed

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError): os.unlink(name)

@contextlib.contextmanager
def locked_state(root: Path) -> Iterator[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "adapter.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = root / "ledger.json"
        data = json.loads(ledger.read_text()) if ledger.exists() else {"claims": {}, "quota": {}}
        try:
            yield data
        finally:
            # Persist transitional/quarantine state even when validation raises.
            # A crash before this write leaves the previous non-free state.
            atomic_json(ledger, data)

def validate_claim(claim: dict[str, Any], epoch: dict[str, Any], workspace: Path) -> None:
    required = {"job_id", "claim_id", "resource_id", "fencing_epoch", "issued_at", "expires_at", "verified"}
    missing = required - claim.keys()
    if missing: raise ResourceError(f"invalid grant: missing {sorted(missing)}")
    if claim["verified"] is not True: raise ResourceError("grant is not Foundation-verified")
    if claim["resource_id"] != RESOURCE: raise ResourceError("resource identity mismatch")
    if not claim["job_id"] or not claim["claim_id"]: raise ResourceError("empty job/claim identity")
    if int(claim["fencing_epoch"]) != int(epoch.get("fencing_epoch", -1)): raise ResourceError("STALE_FENCE")
    if epoch.get("resource_id") != RESOURCE or epoch.get("claim_id") != claim["claim_id"]: raise ResourceError("fencing identity mismatch")
    now = utcnow()
    if parse_time(claim["issued_at"]) > now or parse_time(claim["expires_at"]) <= now: raise ResourceError("grant is not currently valid")
    resolved, stable = workspace.resolve(), STABLE.resolve()
    if resolved == stable or stable in resolved.parents: raise ResourceError("candidate workspace overlaps Stable Runtime")

def pid_identity(pid: int) -> dict[str, Any] | None:
    proc = Path("/proc") / str(pid)
    try:
        stat = (proc / "stat").read_text().split()
        return {"pid": pid, "start_ticks": stat[21], "executable": os.readlink(proc / "exe"),
                "command": (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()}
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError): return None

def port_available(port: int) -> bool:
    for family, address in ((socket.AF_INET, ("127.0.0.1", port)), (socket.AF_INET6, ("::1", port))):
        try:
            with socket.socket(family) as sock: sock.bind(address)
        except OSError: return False
    return True

def docker_record(name: str) -> dict[str, str] | None:
    result = subprocess.run(["docker", "inspect", name, "--format", "{{json .}}"], text=True, capture_output=True)
    if result.returncode:
        if "No such" in result.stderr: return None
        raise ResourceError(f"cannot establish Docker ownership: {result.stderr.strip()}")
    obj = json.loads(result.stdout)
    labels = obj.get("Config", {}).get("Labels") or {}
    return {"container_id": obj["Id"], "job_id": labels.get("io.rupheal.job_id", ""),
            "claim_id": labels.get("io.rupheal.claim_id", ""), "fencing_epoch": labels.get("io.rupheal.fencing_epoch", "")}

def preflight(args: argparse.Namespace) -> dict[str, Any]:
    claim, epoch = json.loads(Path(args.claim).read_text()), json.loads(Path(args.epoch).read_text())
    workspace, root = Path(args.workspace), Path(args.state_dir)
    validate_claim(claim, epoch, workspace)
    ports = [{"port": p, "purpose": purpose} for purpose, values in (("backend", args.backend_port), ("frontend", args.frontend_port)) for p in values]
    if len({x["port"] for x in ports}) != len(ports) or any(not 1 <= x["port"] <= 65535 for x in ports):
        raise ResourceError("managed ports must be unique and between 1 and 65535")
    with locked_state(root) as ledger:
        for cid, old in ledger["claims"].items():
            if old.get("state") != "RELEASED" and cid != claim["claim_id"]:
                if {x["port"] for x in old.get("ports", [])} & {x["port"] for x in ports}: raise ResourceError("WAIT_RESOURCE / RESOURCE_CONFLICT: port claimed")
                if set(old.get("containers", [])) & set(args.container): raise ResourceError("RESOURCE_CONFLICT / QUARANTINE_REQUIRED: container claimed")
        for item in ports:
            if not port_available(item["port"]): raise ResourceError(f"WAIT_RESOURCE / RESOURCE_CONFLICT: foreign owner on port {item['port']}")
        for name in args.container:
            found = docker_record(name) if shutil.which("docker") else None
            if found and (found["claim_id"] != claim["claim_id"] or found["job_id"] != claim["job_id"]): raise ResourceError("RESOURCE_CONFLICT / QUARANTINE_REQUIRED: foreign Docker container")
        previous = ledger["claims"].get(claim["claim_id"])
        if previous and (previous["job_id"] != claim["job_id"] or previous["fencing_epoch"] != claim["fencing_epoch"]): raise ResourceError("claim identity reuse")
        temp = (root / "tmp" / claim["claim_id"]).resolve()
        if root.resolve() not in temp.parents: raise ResourceError("unsafe temp path")
        temp.mkdir(parents=True, exist_ok=True)
        record = {"state": "ACTIVE", "job_id": claim["job_id"], "claim_id": claim["claim_id"], "resource_id": RESOURCE,
                  "fencing_epoch": claim["fencing_epoch"], "workspace": str(workspace.resolve()), "ports": ports,
                  "containers": args.container, "pids": [], "temp_dir": str(temp), "stable_runtime_touched": False, "updated_at": utcnow().isoformat()}
        ledger["claims"][claim["claim_id"]] = record
    receipt = root / "receipts" / f"preflight-{claim['claim_id']}.json"; atomic_json(receipt, record)
    return record

def register_pid(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.state_dir)
    with locked_state(root) as ledger:
        record = ledger["claims"].get(args.claim_id)
        if not record or record["state"] != "ACTIVE": raise ResourceError("claim is not ACTIVE")
        identity = pid_identity(args.pid)
        if not identity: raise ResourceError("PID is not observable")
        identity.update(started_at=args.started_at or utcnow().isoformat(), job_id=record["job_id"], claim_id=args.claim_id)
        record["pids"].append(identity)
        return identity

def cleanup(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.state_dir)
    with locked_state(root) as ledger:
        record = ledger["claims"].get(args.claim_id)
        if not record: raise ResourceError("unknown claim")
        if record["state"] == "RELEASED": return record
        record["state"] = "DRAINING"; record["updated_at"] = utcnow().isoformat()
        for saved in record["pids"]:
            live = pid_identity(saved["pid"])
            if live and (live["start_ticks"] != saved["start_ticks"] or live["executable"] != saved["executable"]):
                record["state"] = "QUARANTINED"; raise ResourceError("PID ownership uncertain; quarantined")
            if live:
                os.kill(saved["pid"], signal.SIGTERM)
                try: os.waitpid(saved["pid"], 0)
                except ChildProcessError: pass
                if pid_identity(saved["pid"]): record["state"] = "QUARANTINED"; raise ResourceError("owned PID did not terminate")
        record["state"] = "CLEANUP"
        for name in record["containers"]:
            if not shutil.which("docker"): continue
            found = docker_record(name)
            if found and (found["claim_id"] != record["claim_id"] or found["job_id"] != record["job_id"] or str(found["fencing_epoch"]) != str(record["fencing_epoch"])):
                record["state"] = "QUARANTINED"; raise ResourceError("foreign Docker container; quarantined")
            if found: subprocess.run(["docker", "rm", "-f", found["container_id"]], check=True)
        temp = Path(record["temp_dir"])
        if root.resolve() not in temp.resolve().parents: record["state"] = "QUARANTINED"; raise ResourceError("unsafe temp ownership")
        shutil.rmtree(temp, ignore_errors=True)
        record["state"] = "READBACK"
        if any(not port_available(x["port"]) for x in record["ports"]): record["state"] = "QUARANTINED"; raise ResourceError("port remains occupied after cleanup")
        record["stable_runtime_touched"] = False
        record["state"] = "RELEASED"; record["updated_at"] = utcnow().isoformat()
    atomic_json(root / "receipts" / f"drain-{args.claim_id}.json", record)
    return record

def quota(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.state_dir)
    with locked_state(root) as ledger:
        q = ledger["quota"].setdefault(args.reservation_id, {"resource_id": QUOTA_RESOURCE, "run_id": args.run_id,
            "reservation_id": args.reservation_id, "requested_units": args.requested_units, "consumed_units": 0,
            "idempotency": {}, "state": "RESERVED"})
        if q["run_id"] != args.run_id or q["requested_units"] != args.requested_units: raise ResourceError("reservation identity mismatch")
        prior = q["idempotency"].get(args.idempotency_key)
        if prior and prior != args.operation: raise ResourceError("idempotency key reused for different operation")
        if not prior:
            if args.operation == "consume":
                if q["state"] != "RESERVED" or q["consumed_units"] + args.units > q["requested_units"]: raise ResourceError("QUOTA_EXCEEDED")
                q["consumed_units"] += args.units
            elif args.operation in {"release", "expire"}: q["state"] = args.operation.upper() + "D"
            q["idempotency"][args.idempotency_key] = args.operation
        return q

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(); p.add_argument("--state-dir", default=".neotutor-resource-state")
    sub=p.add_subparsers(dest="command", required=True)
    x=sub.add_parser("preflight"); x.add_argument("--claim", required=True); x.add_argument("--epoch", required=True); x.add_argument("--workspace", required=True); x.add_argument("--backend-port", type=int, action="append", default=[]); x.add_argument("--frontend-port", type=int, action="append", default=[]); x.add_argument("--container", action="append", default=[]); x.set_defaults(func=preflight)
    x=sub.add_parser("register-pid"); x.add_argument("--claim-id", required=True); x.add_argument("--pid", required=True, type=int); x.add_argument("--started-at"); x.set_defaults(func=register_pid)
    x=sub.add_parser("cleanup"); x.add_argument("--claim-id", required=True); x.set_defaults(func=cleanup)
    x=sub.add_parser("quota"); x.add_argument("operation", choices=["reserve","consume","release","expire"]); x.add_argument("--run-id", required=True); x.add_argument("--reservation-id", required=True); x.add_argument("--requested-units", required=True, type=int); x.add_argument("--units", type=int, default=0); x.add_argument("--idempotency-key", required=True); x.set_defaults(func=quota)
    return p

def main() -> int:
    args=parser().parse_args()
    try: print(json.dumps(args.func(args), indent=2, sort_keys=True)); return 0
    except (ResourceError, OSError, ValueError, json.JSONDecodeError) as exc: print(f"RESOURCE_ADAPTER_DENIED: {exc}", file=sys.stderr); return 2
if __name__ == "__main__": raise SystemExit(main())
