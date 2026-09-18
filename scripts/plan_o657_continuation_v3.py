#!/usr/bin/env python3
"""Plan a continuation wave strictly from a prior partial O formal result."""
from __future__ import annotations
import argparse,json
from decimal import Decimal
from pathlib import Path

PER_MEMBER_CAP=Decimal("0.10")

def build(universe,policy,ledger,previous,affordable_calls,max_shards=16):
    cur=policy.get("current_session") or {}
    if previous.get("target_session")!=cur.get("session"):
        raise ValueError("PREVIOUS_SESSION_MISMATCH")
    if int(previous.get("official_O_denominator",0))!=int(cur["official_denominator"]):
        raise ValueError("PREVIOUS_OFFICIAL_DENOMINATOR_MISMATCH")
    members=universe.get("members") or []
    idx={str(m["code"]):i for i,m in enumerate(members)}
    base_excluded={str(x["code"]) for x in cur.get("excluded_unresolved") or []}
    operational=[str(m["code"]) for m in members if str(m["code"]) not in base_excluded]
    if len(operational)!=int(cur["operational_denominator"]):
        raise ValueError("OPERATIONAL_DENOMINATOR_MISMATCH")
    missing=[str(x) for x in previous.get("missing_operational_members") or []]
    if len(missing)!=len(set(missing)) or any(x not in operational for x in missing):
        raise ValueError("INVALID_PREVIOUS_MISSING_SET")
    frozen=str(ledger["frozen_upstream"]);session=str(ledger["session"])
    no_repeat={}
    for bucket in ("confirmed_provider_sends","no_repeat_uncertain_claims"):
        for row in ledger.get(bucket) or []:
            code=str(row.get("code") or "")
            key=str(row.get("model_call_key") or "")
            if key!=f"{session}:{code}:{frozen}":
                raise ValueError("MODEL_LEDGER_KEY_MISMATCH:"+code)
            if code in no_repeat:
                raise ValueError("DUPLICATE_NO_REPEAT_CODE:"+code)
            no_repeat[code]=bucket
    blocked=[x for x in missing if x in no_repeat]
    candidates=[x for x in missing if x not in no_repeat]
    candidates.sort(key=lambda x:idx[x])
    n=max(0,min(int(affordable_calls),len(candidates)))
    planned=candidates[:n];deferred=candidates[n:]
    shard_count=min(max_shards,n) if n else 0
    shards=[]
    if n:
        q,r=divmod(n,shard_count);pos=0
        for i in range(shard_count):
            size=q+(1 if i<r else 0)
            codes=planned[pos:pos+size];pos+=size
            rows=[{"code":c,"universe_index":idx[c],"official_name":members[idx[c]].get("official_name")} for c in codes]
            shards.append({
              "shard_id":f"{i:02d}","codes":rows,"count":len(rows),
              "maximum_requests":len(rows),"maximum_cost_cny":str(PER_MEMBER_CAP*len(rows))
            })
    return {
      "schema_version":1,
      "session":session,
      "prior_state":previous.get("state"),
      "prior_missing_count":len(missing),
      "blocked_no_repeat_missing_count":len(blocked),
      "blocked_no_repeat_missing":blocked,
      "retryable_missing_before_wave":len(candidates),
      "planned_calls":n,
      "deferred_count":len(deferred),
      "planned_maximum_cost_cny":str(PER_MEMBER_CAP*n),
      "full_retryable_wave":len(deferred)==0,
      "shard_count":shard_count,
      "shards":shards,
      "deferred_codes":deferred,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--ledger",type=Path,required=True)
    ap.add_argument("--previous",type=Path,required=True)
    ap.add_argument("--affordable-calls",type=int,required=True)
    ap.add_argument("--max-shards",type=int,default=16)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    o=build(*(json.loads(p.read_text()) for p in (a.universe,a.policy,a.ledger,a.previous)),
            a.affordable_calls,a.max_shards)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:o[k] for k in ("prior_missing_count","blocked_no_repeat_missing_count","retryable_missing_before_wave","planned_calls","deferred_count","shard_count")}))
if __name__=="__main__":main()
