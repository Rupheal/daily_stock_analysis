#!/usr/bin/env python3
"""Plan a no-duplicate O657 rollout wave from the current-session model ledger."""
from __future__ import annotations
import argparse,json,math
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path

PER_MEMBER_CAP=Decimal("0.10")


def build_plan(universe:dict,policy:dict,ledger:dict,affordable_calls:int,max_shards:int=16):
    cur=policy.get("current_session") or {}
    session=str(cur.get("session"))
    frozen=str(ledger.get("frozen_upstream"))
    members=universe.get("members") or []
    if len(members)!=int(cur["official_denominator"]):
        raise ValueError("OFFICIAL_UNIVERSE_COUNT_MISMATCH")
    excluded={str(x["code"]) for x in cur.get("excluded_unresolved") or []}
    operational=[]
    for i,m in enumerate(members):
        code=str(m.get("code") or "")
        if code not in excluded:
            operational.append({"code":code,"universe_index":i,"official_name":m.get("official_name")})
    if len(operational)!=int(cur["operational_denominator"]):
        raise ValueError("OPERATIONAL_DENOMINATOR_MISMATCH")
    spent={}
    for bucket in ("confirmed_provider_sends","no_repeat_uncertain_claims"):
        for x in ledger.get(bucket) or []:
            key=x.get("model_call_key")
            code=str(x.get("code") or "")
            expected=f"{session}:{code}:{frozen}"
            if key!=expected: raise ValueError("MODEL_LEDGER_KEY_MISMATCH:"+code)
            if code in spent: raise ValueError("DUPLICATE_SPENT_CODE:"+code)
            spent[code]=dict(x,_ledger_bucket=bucket)
    op_codes={x["code"] for x in operational}
    if not set(spent)<=op_codes:
        raise ValueError("SPENT_CODE_OUTSIDE_OPERATIONAL")
    remaining=[x for x in operational if x["code"] not in spent]
    n=max(0,min(int(affordable_calls),len(remaining)))
    planned=remaining[:n]
    deferred=remaining[n:]
    shard_count=min(max_shards,n) if n else 0
    shards=[]
    if n:
        q,r=divmod(n,shard_count);start=0
        for i in range(shard_count):
            size=q+(1 if i<r else 0)
            rows=planned[start:start+size];start+=size
            shards.append({
              "shard_id":f"{i:02d}",
              "codes":rows,
              "count":len(rows),
              "maximum_requests":len(rows),
              "maximum_cost_cny":str(PER_MEMBER_CAP*len(rows)),
            })
    return {
      "schema_version":1,
      "session":session,
      "official_denominator":int(cur["official_denominator"]),
      "operational_denominator":int(cur["operational_denominator"]),
      "base_excluded_count":len(excluded),
      "no_repeat_before_wave":len(spent),
      "confirmed_spent_before_wave":len(ledger.get("confirmed_provider_sends") or []),
      "uncertain_claims_before_wave":len(ledger.get("no_repeat_uncertain_claims") or []),
      "no_repeat_codes":sorted(spent,key=lambda c:next(x["universe_index"] for x in operational if x["code"]==c)),
      "remaining_before_wave":len(remaining),
      "affordable_calls":int(affordable_calls),
      "planned_calls":n,
      "deferred_count":len(deferred),
      "full_remaining_wave":len(deferred)==0,
      "planned_maximum_cost_cny":str(PER_MEMBER_CAP*n),
      "shard_count":shard_count,
      "shards":shards,
      "deferred_codes":[x["code"] for x in deferred],
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--ledger",type=Path,required=True)
    ap.add_argument("--affordable-calls",type=int,required=True)
    ap.add_argument("--max-shards",type=int,default=16)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    out=build_plan(json.loads(a.universe.read_text()),json.loads(a.policy.read_text()),
                   json.loads(a.ledger.read_text()),a.affordable_calls,a.max_shards)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:out[k] for k in ("confirmed_spent_before_wave","remaining_before_wave","planned_calls","deferred_count","shard_count","planned_maximum_cost_cny")},ensure_ascii=False))


if __name__=="__main__":
    main()
