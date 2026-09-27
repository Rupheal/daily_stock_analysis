#!/usr/bin/env python3
"""Deterministic candidate Shared Resource Broker.

Pure state transformer. Persistence is external and MUST be parent-CAS / blob-SHA CAS.
No device, GitHub, Drive, provider, or production side effect occurs in this module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

TERMINAL_SESSION_STATES={"COMPLETED","FAILED","CANCELLED"}
READ_MODES={"READ","HEALTH_READ"}
WRITE_MODES={"WRITE","SESSION","JOB"}

class ResourceConflict(RuntimeError): pass
class CASConflict(ResourceConflict): pass

def canonical_hash(value)->str:
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False
    ).encode()).hexdigest()

def parse_ts(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)

def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def resource_def(registry,resource_id):
    for row in registry.get("resources") or []:
        if row.get("resource_id")==resource_id:return row
    raise KeyError("UNREGISTERED_RESOURCE:"+resource_id)

def active_claims(state,resource_id,now):
    rows=[]
    for c in (state.get("claims") or {}).get(resource_id,[]):
        if c.get("state") not in {"ACTIVE","DRAINING"}: continue
        if parse_ts(c["expires_at"])<=now: continue
        rows.append(c)
    return rows

def _conflicts(policy,mode,existing):
    if not existing:return False
    if mode in READ_MODES and policy=="EXCLUSIVE_MUTATION_SHARED_READ":
        return any(x.get("mode") in WRITE_MODES for x in existing)
    return True

def acquire(registry,state,resource_id,task_id,worker_id,mode,now,ttl_seconds=600,purpose="",session_ref=None):
    if mode not in READ_MODES|WRITE_MODES: raise ValueError("INVALID_RESOURCE_MODE")
    if not task_id or not worker_id: raise ValueError("TASK_WORKER_REQUIRED")
    if not 60<=ttl_seconds<=3600: raise ValueError("INVALID_RESOURCE_TTL")
    rd=resource_def(registry,resource_id)
    if rd.get("policy")=="ATOMIC_BUDGET_RESERVATION":
        raise ValueError("USE_BUDGET_RESERVATION")
    out=copy.deepcopy(state)
    out.setdefault("claims",{})
    existing=active_claims(out,resource_id,now)
    if _conflicts(rd.get("policy"),mode,existing):
        raise ResourceConflict("RESOURCE_BUSY:"+resource_id)
    epoch=int(out.get("next_epoch") or 1)
    out["next_epoch"]=epoch+1
    claim={
      "claim_id":"RCL-"+uuid.uuid4().hex,
      "resource_id":resource_id,
      "task_id":task_id,
      "worker_id":worker_id,
      "mode":mode,
      "epoch":epoch,
      "purpose":purpose,
      "session_ref":session_ref,
      "acquired_at":iso(now),
      "heartbeat_at":iso(now),
      "expires_at":iso(now+timedelta(seconds=ttl_seconds)),
      "ttl_seconds":ttl_seconds,
      "state":"ACTIVE",
      "sessions":[],
      "handoff_state":"NOT_REQUIRED" if not rd.get("handoff_required") else "ACTIVE"
    }
    out["claims"].setdefault(resource_id,[]).append(claim)
    return out,claim

def validate_fence(state,resource_id,claim_id,epoch,task_id=None,worker_id=None,now=None):
    now=now or datetime.now(timezone.utc)
    current=None
    for c in active_claims(state,resource_id,now):
        if c.get("claim_id")==claim_id: current=c;break
    if current is None: raise ResourceConflict("STALE_FENCE:STALE_OR_MISSING_CLAIM")
    if int(current.get("epoch",-1))!=int(epoch): raise ResourceConflict("STALE_FENCE:FENCING_EPOCH_MISMATCH")
    if task_id is not None and current.get("task_id")!=task_id: raise ResourceConflict("CLAIM_TASK_MISMATCH")
    if worker_id is not None and current.get("worker_id")!=worker_id: raise ResourceConflict("CLAIM_WORKER_MISMATCH")
    return True

def heartbeat(state,resource_id,claim_id,epoch,now):
    out=copy.deepcopy(state)
    rows=out.get("claims",{}).get(resource_id,[])
    target=next((c for c in rows if c.get("claim_id")==claim_id),None)
    if target is None: raise ResourceConflict("CLAIM_NOT_FOUND")
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target["heartbeat_at"]=iso(now)
    target["expires_at"]=iso(now+timedelta(seconds=int(target["ttl_seconds"])))
    return out

def attach_session(state,resource_id,claim_id,epoch,session_id,kind,now):
    if not session_id or not kind: raise ValueError("SESSION_ID_KIND_REQUIRED")
    out=copy.deepcopy(state)
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target=next(c for c in out["claims"][resource_id] if c["claim_id"]==claim_id)
    if any(x.get("session_id")==session_id for x in target["sessions"]):
        raise ValueError("DUPLICATE_SESSION_ID")
    target["sessions"].append({
      "session_id":session_id,"kind":kind,"state":"RUNNING","started_at":iso(now),"ended_at":None
    })
    return out

def finish_session(state,resource_id,claim_id,epoch,session_id,session_state,now):
    if session_state not in TERMINAL_SESSION_STATES: raise ValueError("SESSION_NOT_TERMINAL")
    out=copy.deepcopy(state)
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target=next(c for c in out["claims"][resource_id] if c["claim_id"]==claim_id)
    row=next((x for x in target["sessions"] if x.get("session_id")==session_id),None)
    if row is None: raise ValueError("SESSION_NOT_OWNED_BY_CLAIM")
    row["state"]=session_state;row["ended_at"]=iso(now)
    return out

def begin_drain(state,resource_id,claim_id,epoch,now):
    out=copy.deepcopy(state)
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target=next(c for c in out["claims"][resource_id] if c["claim_id"]==claim_id)
    target["state"]="DRAINING";target["handoff_state"]="DRAINING"
    return out

def mark_drained(state,registry,resource_id,claim_id,epoch,now,readback_verified):
    if readback_verified is not True: raise ValueError("HANDOFF_READBACK_REQUIRED")
    rd=resource_def(registry,resource_id)
    out=copy.deepcopy(state)
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target=next(c for c in out["claims"][resource_id] if c["claim_id"]==claim_id)
    active=[x for x in target["sessions"] if x.get("state") not in TERMINAL_SESSION_STATES]
    if active: raise ResourceConflict("ACTIVE_SESSIONS_BLOCK_HANDOFF")
    if rd.get("handoff_required"):
        target["handoff_state"]="DRAINED"
    target["readback_verified_at"]=iso(now)
    return out

def release(state,registry,resource_id,claim_id,epoch,now):
    rd=resource_def(registry,resource_id)
    out=copy.deepcopy(state)
    validate_fence(out,resource_id,claim_id,epoch,now=now)
    target=next(c for c in out["claims"][resource_id] if c["claim_id"]==claim_id)
    if any(x.get("state") not in TERMINAL_SESSION_STATES for x in target["sessions"]):
        raise ResourceConflict("ACTIVE_SESSIONS_BLOCK_RELEASE")
    if rd.get("handoff_required") and target.get("handoff_state")!="DRAINED":
        raise ResourceConflict("DRAIN_BEFORE_RELEASE_REQUIRED")
    target["state"]="RELEASED";target["released_at"]=iso(now)
    return out

def reserve_budget(registry,state,resource_id,run_id,units,now,reservation_id=None):
    rd=resource_def(registry,resource_id)
    if rd.get("policy")!="ATOMIC_BUDGET_RESERVATION": raise ValueError("NOT_BUDGET_RESOURCE")
    try:
        requested=Decimal(str(units))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError("BUDGET_UNITS_INVALID") from None
    if requested<=0: raise ValueError("POSITIVE_RESERVATION_REQUIRED")
    out=copy.deepcopy(state);out.setdefault("budgets",{});out.setdefault("reservations",{})
    budget=out["budgets"].get(resource_id)
    if not isinstance(budget,dict) or budget.get("available_units") is None:
        raise ResourceConflict("BUDGET_RECONCILIATION_REQUIRED")
    rid=reservation_id or ("RSV-"+uuid.uuid4().hex)
    prior=out["reservations"].get(rid)
    if prior:
        if prior.get("resource_id")==resource_id and prior.get("run_id")==run_id and prior.get("units")==units:
            return out,prior
        raise ResourceConflict("RESERVATION_ID_CONFLICT")
    try:
        available=Decimal(str(budget["available_units"]))
        active=sum((Decimal(str(x["units"])) for x in out["reservations"].values()
                    if x.get("resource_id")==resource_id and x.get("state")=="RESERVED"),Decimal(0))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError("BUDGET_UNITS_INVALID") from None
    if requested<=0 or available<0:
        raise ValueError("BUDGET_UNITS_INVALID")
    if active+requested>available:
        raise ResourceConflict("BUDGET_RESERVATION_EXCEEDS_AVAILABLE")
    row={"reservation_id":rid,"resource_id":resource_id,"run_id":run_id,
         "units":units,"state":"RESERVED","reserved_at":iso(now)}
    out["reservations"][rid]=row
    return out,row

def normalize_resources(resources):
    """Validate and canonically order a MultiLock-style resource set."""
    if not isinstance(resources,list) or not resources: raise ValueError("RESOURCES_REQUIRED")
    rows=[]; seen=set()
    for item in resources:
        if not isinstance(item,dict): raise ValueError("RESOURCE_REQUEST_OBJECT_REQUIRED")
        rid=item.get("resource_id"); mode=item.get("mode")
        if not rid or rid in seen: raise ValueError("DUPLICATE_OR_MISSING_RESOURCE")
        if mode not in READ_MODES|WRITE_MODES: raise ValueError("INVALID_RESOURCE_MODE")
        seen.add(rid); rows.append({"resource_id":rid,"mode":mode,
                                   "required":item.get("required",True),"purpose":item.get("purpose","")})
    return sorted(rows,key=lambda x:x["resource_id"])

def enqueue_request(registry,state,task_id,worker_id,job_id,resources,priority,now,
                    idempotency_key,request_id=None,ttl_seconds=600):
    """Persist a fair/stingy logical request; duplicate keys collapse."""
    if not idempotency_key: raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    requested=normalize_resources(resources)
    for row in requested: resource_def(registry,row["resource_id"])
    out=copy.deepcopy(state); out.setdefault("requests",{}); out.setdefault("queue",[])
    for prior in out["requests"].values():
        if prior.get("idempotency_key")==idempotency_key and prior.get("state") not in {"CANCELLED","RELEASED"}:
            return out,prior
    rid=request_id or "RRQ-"+uuid.uuid4().hex
    if rid in out["requests"]: raise ResourceConflict("REQUEST_ID_CONFLICT")
    row={"request_id":rid,"task_id":task_id,"worker_id":worker_id,"job_id":job_id,
         "resources":requested,"priority":int(priority),"requested_at":iso(now),
         "idempotency_key":idempotency_key,"state":"QUEUED","ttl_seconds":ttl_seconds,
         "claim_ids":[]}
    out["requests"][rid]=row; out["queue"].append(rid)
    return out,row

def grant_request(registry,state,request_id,now):
    """Atomically grant the complete set or leave state byte-for-byte unchanged."""
    req=(state.get("requests") or {}).get(request_id)
    if not req: raise KeyError("REQUEST_NOT_FOUND")
    if req.get("state")=="GRANTED": return copy.deepcopy(state),req
    if req.get("state")!="QUEUED": raise ResourceConflict("REQUEST_NOT_QUEUED")
    # Evaluate the full snapshot before mutating it: no AB/BA locking and no partial owner.
    for item in req["resources"]:
        rd=resource_def(registry,item["resource_id"])
        if rd.get("policy")=="ATOMIC_BUDGET_RESERVATION" or _conflicts(
                rd.get("policy"),item["mode"],active_claims(state,item["resource_id"],now)):
            raise ResourceConflict("RESOURCE_BUSY:"+item["resource_id"])
    out=copy.deepcopy(state); claims=[]
    for item in req["resources"]:
        out,claim=acquire(registry,out,item["resource_id"],req["task_id"],req["worker_id"],
                          item["mode"],now,req["ttl_seconds"],item["purpose"],req.get("job_id"))
        claim["request_id"]=request_id; claims.append(claim)
    target=out["requests"][request_id]; target["state"]="GRANTED"
    target["granted_at"]=iso(now); target["claim_ids"]=[x["claim_id"] for x in claims]
    out["queue"]=[x for x in out.get("queue",[]) if x!=request_id]
    return out,target

def promote_next(registry,state,now):
    """Fair priority/FIFO scan; busy requests remain durable while independent work proceeds."""
    out=copy.deepcopy(state); granted=[]
    ordered=sorted(out.get("queue",[]),key=lambda rid:(
        -(out["requests"][rid].get("priority",0)),out["requests"][rid]["requested_at"],rid))
    for rid in ordered:
        try: out,row=grant_request(registry,out,rid,now); granted.append(row)
        except ResourceConflict: continue
    return out,granted

def quarantine_expired(state,now):
    """Expired ownership is fenced but never silently made FREE before finalization."""
    out=copy.deepcopy(state)
    for rows in out.get("claims",{}).values():
        for claim in rows:
            if claim.get("state") in {"ACTIVE","DRAINING"} and parse_ts(claim["expires_at"])<=now:
                claim["state"]="QUARANTINED"; claim["quarantined_at"]=iso(now)
                claim["quarantine_reason"]="LEASE_EXPIRED_FINALIZERS_REQUIRED"
    return out

def validate_mutation(state,resource_id,claim_id,epoch,expected_base,actual_base,now=None):
    """Unified Git/authority/journal/local-writer mutation-boundary contract."""
    validate_fence(state,resource_id,claim_id,epoch,now=now)
    if not expected_base or expected_base!=actual_base: raise CASConflict("BASE_VERSION_CONFLICT")
    return True

class JsonCASStore:
    """Single-state durable CAS adapter. Callers must read, modify, CAS, then read back."""
    def __init__(self,path): self.path=Path(path)
    def read(self):
        value=json.loads(self.path.read_text(encoding="utf-8")); return value,canonical_hash(value)
    def commit(self,expected_version,value):
        current,version=self.read()
        if version!=expected_version: raise CASConflict("BROKER_STATE_CAS_CONFLICT")
        tmp=self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        tmp.replace(self.path)
        readback,new_version=self.read()
        if canonical_hash(readback)!=canonical_hash(value): raise RuntimeError("CAS_READBACK_MISMATCH")
        return new_version
