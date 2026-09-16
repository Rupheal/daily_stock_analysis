#!/usr/bin/env python3
"""Deterministic event-candidate layer for U45 public-news evidence.

This script intentionally does NOT set event_ready or formal_news_ready. It only
adds traceable candidate categories to rows that already passed the bounded
recency + issuer-title relevance gate. Event/formal acceptance remains a
separate fail-closed step.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RULES = [
    ("FINANCING_EQUITY", True, [r"配股", r"配售", r"集资", r"集資", r"筹资", r"籌资", r"籌資", r"equity offering", r"placement"]),
    ("CLINICAL_TRIAL", True, [r"临床", r"臨床", r"试验", r"試驗", r"生存期", r"clinical trial", r"phase [123]", r"overall survival"]),
    ("LEGAL_REGULATORY_EVENT", True, [r"调查", r"調查", r"诉讼", r"訴訟", r"反垄断", r"反壟斷", r"处罚", r"處罰", r"sanction", r"lawsuit", r"antitrust", r"probe"]),
    ("ROUTINE_REGULATORY_DISCLOSURE", False, [r"翌日披露", r"披露报表", r"披露報表", r"公告"]),
    ("ANALYST_RATING", False, [r"评级", r"評級", r"目标价", r"目標價", r"维持.*买入", r"維持.*買入", r"upgrade", r"downgrade", r"price target"]),
    ("MARKET_PRICE_COMMENTARY", False, [r"港股市况", r"港股市況", r"港股收市", r"高开", r"高開", r"低开", r"低開", r"早盘", r"早盤", r"盘初", r"盤初", r"adr", r"升超", r"跌超", r"上涨", r"上升", r"下跌"]),
]


def classify_title(title: str) -> list[dict]:
    text=" ".join(str(title or "").casefold().split())
    matches=[]
    for category, material, patterns in RULES:
        hits=[p for p in patterns if re.search(p,text,re.I)]
        if hits:
            matches.append({"category":category,"material_candidate":material,"matched_rules":hits})
    return matches


def classify_receipt(data: dict) -> dict:
    rows=[]; material_members=[]; category_counts={}
    for row in data.get("rows",[]):
        if not row.get("relevance_ready"):
            continue
        items=[]; member_material=False
        for item in row.get("unique_recent_relevant_items") or []:
            cats=classify_title(item.get("title",""))
            if cats:
                for c in cats:
                    category_counts[c["category"]]=category_counts.get(c["category"],0)+1
                    member_material = member_material or bool(c["material_candidate"])
            items.append({"title":item.get("title"),"published":item.get("published"),"url":item.get("url"),"categories":cats,
                          "material_event_candidate":any(c["material_candidate"] for c in cats)})
        rows.append({"code":row.get("code"),"name":row.get("name"),"relevance_ready":True,
                     "material_event_candidate":member_material,"items":items,"event_ready":False,"formal_news_ready":False})
        if member_material: material_members.append(row.get("code"))
    return {
        "schema_version":"U45_NEWS_EVENT_CANDIDATES_v1",
        "source_schema":data.get("schema_version"),
        "source_generated_at":data.get("generated_at"),
        "universe_denominator":data.get("universe_denominator"),
        "execution_eligible_denominator":data.get("execution_eligible_denominator"),
        "retrieval_ready":data.get("members_retrieval_ready"),
        "relevance_ready":data.get("members_relevance_ready"),
        "event_candidate_members":len(material_members),
        "material_event_candidate_codes":material_members,
        "category_match_counts":category_counts,
        "event_ready":0,
        "formal_news_ready":0,
        "formal_u_acceptance_added":0,
        "model_http_requests":0,
        "paid_data_calls":0,
        "classification_contract":"Keyword/rule-based candidate routing only; not semantic truth and not formal event acceptance.",
        "rows":rows,
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); ap.add_argument("--out",required=True); args=ap.parse_args()
    data=json.loads(Path(args.input).read_text(encoding="utf-8")); out=classify_receipt(data)
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("retrieval_ready","relevance_ready","event_candidate_members","material_event_candidate_codes","event_ready","formal_news_ready","model_http_requests")},ensure_ascii=False))
    if out["event_ready"] != 0 or out["formal_news_ready"] != 0 or out["formal_u_acceptance_added"] != 0:
        raise SystemExit("EVENT_CANDIDATE_LAYER_BREACHED_FORMAL_GATE")

if __name__=="__main__":
    main()
