#!/usr/bin/env python3
"""Private append-only Drive snapshots for the DSA dual-account simulation journal.

No model or broker calls. Each journal state is immutable and stored under a
monotonic command-count name. Single-writer workflow concurrency is still
required; parent-hash validation prevents stale writers from advancing history.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import httpx

from dsa_drive_store import DriveStore, scoped_token, API, StoreError
from src.services.dsa_prediction_ledger import canonical_hash

PREFIX="DSA-DUAL-ACCOUNT-JOURNAL"
NAME_RE=re.compile(r"^DSA-DUAL-ACCOUNT-JOURNAL-C(\d{8})-H([0-9a-f]{12})\.bin$")


def _client_store():
    c=httpx.Client(timeout=30,follow_redirects=False)
    c.headers["Authorization"]="Bearer "+scoped_token(c)
    return c,DriveStore(c,os.environ.get("DSA_DRIVE_FOLDER_ID",""))


def list_snapshots(store:DriveStore):
    q=("'" + store.folder + "' in parents and trashed=false and "
       "name contains '" + PREFIX + "-C'")
    data=store.request("GET",API+"/files",params={
      "q":q,
      "fields":"files(id,name,appProperties,createdTime),nextPageToken",
      "pageSize":1000,
      "orderBy":"createdTime asc",
    }).json()
    if data.get("nextPageToken"):
        raise StoreError("JOURNAL_SNAPSHOT_PAGE_OVERFLOW")
    rows=[]
    for f in data.get("files") or []:
        m=NAME_RE.fullmatch(str(f.get("name") or ""))
        if not m:
            continue
        props=f.get("appProperties") or {}
        sha=props.get("sha256")
        if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha):
            raise StoreError("JOURNAL_SNAPSHOT_SHA_MISSING")
        rows.append({
          "count":int(m.group(1)),"hash12":m.group(2),
          "file_id":f["id"],"sha256":sha,"run_id":props.get("run_id"),
          "name":f["name"],
        })
    rows.sort(key=lambda x:(x["count"],x["name"]))
    counts={}
    for x in rows:
        counts.setdefault(x["count"],[]).append(x)
    for n,xs in counts.items():
        if len(xs)>1:
            # Multiple snapshots for the same command count are only safe if
            # they point to the same journal canonical hash prefix.
            if len({x["hash12"] for x in xs})!=1:
                raise StoreError("JOURNAL_FORK_DETECTED")
    return rows


def load_latest(out:Path|None=None):
    c,store=_client_store()
    try:
        rows=list_snapshots(store)
        if not rows:
            return {"status":"JOURNAL_UNCONFIGURED","exists":False,"command_count":0}
        row=rows[-1]
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"journal.json"
            store.recover(row["file_id"],row["sha256"],p)
            obj=json.loads(p.read_text(encoding="utf-8"))
            count=len(obj.get("commands") or [])
            if count!=row["count"]:
                raise StoreError("JOURNAL_COMMAND_COUNT_MISMATCH")
            ch=canonical_hash(obj)
            if not ch.startswith(row["hash12"]):
                raise StoreError("JOURNAL_CANONICAL_HASH_MISMATCH")
            if out:
                out.parent.mkdir(parents=True,exist_ok=True)
                out.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            return {
              "status":"JOURNAL_LOADED","exists":True,"command_count":count,
              "canonical_hash":ch,"artifact_name":row["name"],
              "file_sha256":row["sha256"],"file_id":row["file_id"],
            }
    finally:
        c.close()


def save_snapshot(journal_path:Path,run_id:str,expected_parent_hash:str|None,allow_init:bool=False):
    obj=json.loads(journal_path.read_text(encoding="utf-8"))
    if set(obj.get("config",{}).get("accounts",{}))!={"U","O"}:
        raise StoreError("JOURNAL_UO_CONFIG_REQUIRED")
    count=len(obj.get("commands") or [])
    ch=canonical_hash(obj)
    c,store=_client_store()
    try:
        rows=list_snapshots(store)
        if not rows:
            if not allow_init:
                raise StoreError("JOURNAL_INIT_NOT_AUTHORIZED")
            if count!=0:
                raise StoreError("INITIAL_JOURNAL_MUST_HAVE_ZERO_COMMANDS")
        else:
            latest=rows[-1]
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/"latest.json"
                store.recover(latest["file_id"],latest["sha256"],p)
                old=json.loads(p.read_text(encoding="utf-8"))
                old_hash=canonical_hash(old)
                old_count=len(old.get("commands") or [])
            if expected_parent_hash!=old_hash:
                raise StoreError("JOURNAL_PARENT_HASH_CONFLICT")
            if count<old_count:
                raise StoreError("JOURNAL_COMMAND_COUNT_REGRESSION")
            if count==old_count:
                if ch==old_hash:
                    return {"status":"JOURNAL_IDEMPOTENT","command_count":count,"canonical_hash":ch}
                raise StoreError("JOURNAL_SAME_COUNT_CONFLICT")
        artifact=f"{PREFIX}-C{count:08d}-H{ch[:12]}"
        payload=(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
        receipt=store.put(artifact,payload,run_id)
        # Verify the stored payload canonical hash rather than trusting metadata.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"verify.json"
            store.recover(receipt["file_id"],receipt["sha256"],p)
            restored=json.loads(p.read_text(encoding="utf-8"))
            if canonical_hash(restored)!=ch:
                raise StoreError("JOURNAL_POSTWRITE_CANONICAL_HASH_MISMATCH")
        return {
          "status":"JOURNAL_SNAPSHOT_SAVED","command_count":count,
          "canonical_hash":ch,"artifact_id":artifact,
          "save_read_hash_restore":True,
        }
    finally:
        c.close()


def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("load");p.add_argument("--out",type=Path)
    p=sub.add_parser("save");p.add_argument("--journal",type=Path,required=True)
    p.add_argument("--run-id",required=True);p.add_argument("--expected-parent-hash")
    p.add_argument("--allow-init",action="store_true")
    a=ap.parse_args()
    try:
        if a.cmd=="load":
            print(json.dumps(load_latest(a.out),ensure_ascii=False))
        else:
            print(json.dumps(save_snapshot(a.journal,a.run_id,a.expected_parent_hash,a.allow_init),ensure_ascii=False))
    except Exception as exc:
        reason=str(exc) if isinstance(exc,StoreError) else type(exc).__name__
        print(json.dumps({"status":"FAILED","reason":reason}))
        raise SystemExit(2) from None


if __name__=="__main__":
    main()
