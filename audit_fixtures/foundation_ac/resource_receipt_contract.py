#!/usr/bin/env python3
"""Canonical export layer for Foundation Resource Broker receipts.

Pure mapping/serialization only. No keys, signatures, providers, runners or
Production side effects are created here.
"""
from __future__ import annotations
import hashlib, json
from decimal import Decimal

CLAIM_SCHEMA="foundation.resource-claim-receipt/v1"
CLAIM_READBACK_SCHEMA="foundation.resource-claim-readback/v1"
QUOTA_SCHEMA="foundation.quota-reservation-receipt/v1"
QUOTA_READBACK_SCHEMA="foundation.quota-reservation-readback/v1"

def _json_default(value):
    if isinstance(value,Decimal):
        return str(value)
    raise TypeError(f"UNSUPPORTED_CANONICAL_TYPE:{type(value).__name__}")

def canonical_bytes(value)->bytes:
    return (json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                       allow_nan=False,default=_json_default)+"\n").encode()

def canonical_hash(value)->str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

def broker_state_proof(state)->dict:
    return {"version":1,"hash":canonical_hash(state)}

def _require(value,name):
    if value in (None,""): raise ValueError("MISSING_"+name.upper())
    return value

def claim_receipt(claim,broker_state)->dict:
    if claim.get("state")!="ACTIVE": raise ValueError("CLAIM_NOT_ACTIVE")
    holder={
      "task_id":_require(claim.get("task_id"),"task_id"),
      "worker_id":_require(claim.get("worker_id"),"worker_id"),
      "job_id":_require(claim.get("session_ref"),"job_id")
    }
    return {
      "schema":CLAIM_SCHEMA,
      "resource_id":_require(claim.get("resource_id"),"resource_id"),
      "claim_id":_require(claim.get("claim_id"),"claim_id"),
      "holder":holder,
      "fencing_epoch":int(_require(claim.get("epoch"),"epoch")),
      "acquired_at":_require(claim.get("acquired_at"),"acquired_at"),
      "expires_at":_require(claim.get("expires_at"),"expires_at"),
      "broker_state":broker_state_proof(broker_state)
    }

def claim_readback(claim,broker_state)->dict:
    receipt=claim_receipt(claim,broker_state)
    return {
      "schema":CLAIM_READBACK_SCHEMA,
      "state":"ACTIVE",
      **{k:receipt[k] for k in ("resource_id","claim_id","holder","fencing_epoch","expires_at","broker_state")}
    }

def quota_reservation_receipt(reservation,broker_state,*,expires_at,idempotency_key)->dict:
    if reservation.get("state")!="RESERVED": raise ValueError("RESERVATION_NOT_ACTIVE")
    _require(expires_at,"expires_at"); _require(idempotency_key,"idempotency_key")
    return {
      "schema":QUOTA_SCHEMA,
      "resource_id":_require(reservation.get("resource_id"),"resource_id"),
      "run_id":_require(reservation.get("run_id"),"run_id"),
      "reservation_id":_require(reservation.get("reservation_id"),"reservation_id"),
      "reserved_units":str(_require(reservation.get("units"),"reserved_units")),
      "idempotency_key":idempotency_key,
      "expires_at":expires_at,
      "broker_state":broker_state_proof(broker_state)
    }

def quota_reservation_readback(reservation,broker_state,*,expires_at,idempotency_key)->dict:
    receipt=quota_reservation_receipt(reservation,broker_state,expires_at=expires_at,idempotency_key=idempotency_key)
    return {
      "schema":QUOTA_READBACK_SCHEMA,
      "state":"RESERVED",
      **{k:receipt[k] for k in ("resource_id","run_id","reservation_id","reserved_units","idempotency_key","expires_at","broker_state")}
    }
