#!/usr/bin/env python3
"""TRIDENT worker artifact persistence gate.

This module is deliberately provider-I/O free.  The trusted Control Room reads
the remote provider, constructs the observed snapshot, and this module validates
the binding.  A worker-local claim can never satisfy this gate by itself.
"""
from __future__ import annotations
import hashlib, json, re

DIRECT_COMMIT="DIRECT_COMMIT"
PATCH_RECONSTRUCTION="PATCH_RECONSTRUCTION"
VERIFIED="REMOTE_READBACK_VERIFIED"
PENDING="PERSIST_PENDING"
MISSING="PERSISTENCE_MISSING"
CONFLICT="PERSISTENCE_CONFLICT"
HEX40=re.compile(r"^[0-9a-f]{40}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")

class PersistenceError(RuntimeError): pass

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def _need(obj,key):
    value=obj.get(key)
    if value in (None,""): raise PersistenceError("MISSING_"+key.upper())
    return value

def _same(expected,actual,code):
    if expected!=actual: raise PersistenceError(code)

def evaluate(expected,observed):
    """Validate one independent remote readback and return a bound receipt."""
    if not isinstance(expected,dict) or not isinstance(observed,dict):
        raise PersistenceError("PERSISTENCE_OBJECT_REQUIRED")
    mode=_need(expected,"mode")
    if mode not in {DIRECT_COMMIT,PATCH_RECONSTRUCTION}:
        raise PersistenceError("UNSUPPORTED_PERSISTENCE_MODE")
    if observed.get("source")!="GITHUB_REMOTE_READBACK":
        raise PersistenceError("INDEPENDENT_REMOTE_READBACK_REQUIRED")
    for key in ("repository","branch"):
        _same(_need(expected,key),_need(observed,key),"REMOTE_"+key.upper()+"_MISMATCH")
    if observed.get("commit_exists") is not True:
        raise PersistenceError("REMOTE_COMMIT_MISSING")
    remote_head=_need(observed,"branch_head")
    remote_commit=_need(observed,"commit_sha")
    _same(remote_head,remote_commit,"REMOTE_BRANCH_COMMIT_MISMATCH")
    input_head=_need(expected,"input_head")
    if not HEX40.fullmatch(input_head):
        raise PersistenceError("INVALID_INPUT_HEAD")
    if observed.get("ancestry_contains_input") is not True:
        raise PersistenceError("INPUT_HEAD_NOT_IN_REMOTE_ANCESTRY")
    if expected.get("pr_number") is not None:
        if observed.get("pr_number")!=expected["pr_number"]:
            raise PersistenceError("PR_NUMBER_MISMATCH")
        _same(remote_head,_need(observed,"pr_head"),"REMOTE_PR_HEAD_MISMATCH")
    if expected.get("tree_sha") is not None:
        _same(expected["tree_sha"],_need(observed,"tree_sha"),"REMOTE_TREE_MISMATCH")
    if mode==DIRECT_COMMIT:
        output=_need(expected,"worker_output_head")
        if not HEX40.fullmatch(output): raise PersistenceError("INVALID_WORKER_OUTPUT_HEAD")
        _same(output,remote_head,"WORKER_OUTPUT_NOT_REMOTE_HEAD")
    else:
        patch_hash=_need(expected,"patch_sha256")
        if not HEX64.fullmatch(patch_hash): raise PersistenceError("INVALID_PATCH_SHA256")
        target=expected.get("target_blobs")
        if not isinstance(target,dict) or not target:
            raise PersistenceError("PATCH_TARGET_BLOBS_REQUIRED")
        changed=expected.get("changed_paths")
        if sorted(changed or [])!=sorted(target):
            raise PersistenceError("PATCH_CHANGED_PATH_CONTRACT_INVALID")
        remote_blobs=observed.get("remote_blobs")
        if not isinstance(remote_blobs,dict):
            raise PersistenceError("REMOTE_BLOB_READBACK_REQUIRED")
        if sorted(remote_blobs)!=sorted(target):
            raise PersistenceError("REMOTE_CHANGED_PATH_SET_MISMATCH")
        for path,sha in target.items():
            if not HEX40.fullmatch(str(sha)): raise PersistenceError("INVALID_TARGET_BLOB_SHA:"+path)
            if remote_blobs.get(path)!=sha:
                raise PersistenceError("REMOTE_TARGET_BLOB_MISMATCH:"+path)
        if observed.get("patch_sha256") not in (None,patch_hash):
            raise PersistenceError("PATCH_HASH_MISMATCH")
    binding={"expected":expected,"observed":observed}
    return {
        "schema_version":1,
        "state":VERIFIED,
        "mode":mode,
        "repository":expected["repository"],
        "branch":expected["branch"],
        "remote_head":remote_head,
        "pr_number":expected.get("pr_number"),
        "verified_by":"CONTROL_ROOM_REMOTE_READBACK",
        "binding_hash":canonical_hash(binding)
    }

def pending(expected,reason):
    return {"schema_version":1,"state":PENDING,"mode":expected.get("mode"),"reason":reason}

def require_verified(receipt):
    if not isinstance(receipt,dict): raise PersistenceError("PERSISTENCE_RECEIPT_REQUIRED")
    if receipt.get("state")!=VERIFIED: raise PersistenceError("REMOTE_PERSISTENCE_NOT_VERIFIED")
    if receipt.get("verified_by")!="CONTROL_ROOM_REMOTE_READBACK": raise PersistenceError("UNTRUSTED_PERSISTENCE_VERIFIER")
    if not HEX64.fullmatch(str(receipt.get("binding_hash") or "")): raise PersistenceError("PERSISTENCE_BINDING_HASH_REQUIRED")
    if not HEX40.fullmatch(str(receipt.get("remote_head") or "")): raise PersistenceError("PERSISTENCE_REMOTE_HEAD_REQUIRED")
    return True
