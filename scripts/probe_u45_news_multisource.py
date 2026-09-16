#!/usr/bin/env python3
"""Model-free U45 news retrieval via independent public sources.

Primary positive path: Google News RSS issuer queries with official-name fallback.
Independent source-health check: Yahoo Finance search API.
Eastmoney remains quarantined in this lane after preserved passportWeb-only
failure evidence. No model credentials, LLM calls, or paid data are used.

Readiness is deliberately layered and fail-closed:
retrieval_ready -> relevance_ready -> event_ready -> formal_news_ready.
Retrieval or deterministic title relevance never auto-promotes event/formal readiness.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

UA = "Mozilla/5.0 (compatible; DSA-U45-NewsMultiSource/1.2)"
YAHOO = "https://query2.finance.yahoo.com/v1/finance/search"
GOOGLE_RSS = "https://news.google.com/rss/search"


def load_universe(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("members", "stocks", "universe"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise SystemExit("U45 universe must resolve to list")
    rows=[]
    for x in raw:
        code=str(x.get("code") or x.get("symbol") or "").upper().replace("HK","").zfill(5)
        name=str(x.get("name") or x.get("user_alias") or x.get("alias") or code).strip()
        official=str(x.get("official_name") or "").strip()
        rows.append({"code":code,"name":name,"official_name":official})
    if len(rows)!=45 or len({x['code'] for x in rows})!=45:
        raise SystemExit(f"U45 denominator invariant failed: {len(rows)}")
    return rows


def yahoo_symbol(code: str) -> str:
    return f"{int(code):04d}.HK"


def safe_title(value) -> str:
    return " ".join(str(value or "").split())[:300]


def clean_alias(s: str) -> str:
    return re.sub(r"-(?:W|SW)$", "", s.strip(), flags=re.I)


def dedupe_key(title: str, published: str | None) -> str:
    normalized_title=" ".join(str(title or "").casefold().split())
    normalized_pub=" ".join(str(published or "").split())
    return hashlib.sha256(f"{normalized_title}|{normalized_pub}".encode("utf-8")).hexdigest()


def dedupe_recent_relevant(items: list[dict]) -> tuple[list[dict], int]:
    seen=set(); out=[]; removed=0
    for raw in items:
        item=dict(raw)
        key=item.get("dedupe_key") or dedupe_key(item.get("title",""),item.get("published"))
        item["dedupe_key"]=key
        if key in seen:
            removed += 1
            continue
        seen.add(key); out.append(item)
    return out, removed


def readiness(retrieval_ready: bool, relevance_ready: bool) -> dict:
    # Event classification has not yet passed a formal semantic acceptance gate.
    # Therefore event/formal readiness remain false even when deterministic title
    # relevance is positive.
    return {
        "retrieval_ready": bool(retrieval_ready),
        "relevance_ready": bool(relevance_ready),
        "event_ready": False,
        "formal_news_ready": False,
        "event_gate_status": "NOT_FORMALLY_CLASSIFIED_FAIL_CLOSED",
        "formal_gate_status": "NOT_ACCEPTED_FAIL_CLOSED",
    }


def fetch_yahoo(member: dict, timeout: float) -> dict:
    symbol=yahoo_symbol(member['code']); started=time.monotonic(); out={'provider':'yahoo_finance_search','query':symbol,'symbol':symbol}
    try:
        r=requests.get(YAHOO,params={'q':symbol,'quotesCount':1,'newsCount':20,'enableFuzzyQuery':'false'},headers={'User-Agent':UA,'Accept':'application/json'},timeout=(8,timeout))
        raw=r.content; out.update(http_status=r.status_code,response_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()); r.raise_for_status(); data=r.json(); news=data.get('news') or []
        if not isinstance(news,list): raise ValueError('news_not_list')
        out.update(parsed=True,items_returned=len(news),sample=[{'title':safe_title(n.get('title')),'publisher':safe_title(n.get('publisher')),'published':n.get('providerPublishTime'),'url':n.get('link')} for n in news[:3] if isinstance(n,dict)])
    except Exception as exc:
        out.update(parsed=False,items_returned=0,error_type=type(exc).__name__)
    out['elapsed_ms']=round((time.monotonic()-started)*1000); return out


def google_once(term: str, timeout: float, cutoff: datetime, relevance_terms: list[str]) -> dict:
    query=f'"{term}" 股票 OR 港股'; started=time.monotonic(); out={'provider':'google_news_rss','query':query,'term':term}
    try:
        r=requests.get(GOOGLE_RSS,params={'q':query,'hl':'zh-TW','gl':'HK','ceid':'HK:zh-Hant'},headers={'User-Agent':UA,'Accept':'application/rss+xml, application/xml;q=0.9, */*;q=0.8'},timeout=(8,timeout))
        raw=r.content; out.update(http_status=r.status_code,response_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()); r.raise_for_status(); root=ET.fromstring(raw); items=root.findall('.//item')
        recent=0; title_hits=0; recent_title_hits=0; sample=[]; recent_relevant=[]
        terms=[t.casefold() for t in relevance_terms if t]
        for i in items:
            title=safe_title(i.findtext('title')); pub=i.findtext('pubDate'); link=i.findtext('link'); is_recent=False
            try:
                dt=parsedate_to_datetime(pub)
                if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                is_recent=dt.astimezone(timezone.utc)>=cutoff
            except Exception:
                pass
            hit=any(t in title.casefold() for t in terms)
            recent += int(is_recent); title_hits += int(hit); recent_title_hits += int(is_recent and hit)
            row={'title':title,'published':pub,'url':link,'recent':is_recent,'issuer_title_hit':hit}
            if is_recent and hit:
                row['dedupe_key']=dedupe_key(title,pub); recent_relevant.append(row)
            if len(sample)<5: sample.append(row)
        unique, removed=dedupe_recent_relevant(recent_relevant)
        out.update(parsed=True,items_returned=len(items),recent_items=recent,title_issuer_hits=title_hits,recent_title_issuer_hits=recent_title_hits,
                   unique_recent_relevant_items=len(unique),duplicate_recent_relevant_items_removed=removed,recent_relevant_items=unique,sample=sample)
    except Exception as exc:
        out.update(parsed=False,items_returned=0,recent_items=0,title_issuer_hits=0,recent_title_issuer_hits=0,unique_recent_relevant_items=0,
                   duplicate_recent_relevant_items_removed=0,recent_relevant_items=[],error_type=type(exc).__name__)
    out['elapsed_ms']=round((time.monotonic()-started)*1000); return out


def fetch_google(member: dict, timeout: float, cutoff: datetime) -> list[dict]:
    alias=clean_alias(member['name']); official=member.get('official_name','').strip(); relevance=[alias,official]
    first=google_once(alias,timeout,cutoff,relevance); attempts=[first]
    if int(first.get('items_returned') or 0)==0 and official and official.casefold()!=alias.casefold():
        attempts.append(google_once(official,timeout,cutoff,relevance))
    return attempts


def fetch_member(member: dict, timeout: float, cutoff: datetime) -> dict:
    y=fetch_yahoo(member,timeout); gs=fetch_google(member,timeout,cutoff); attempts=[y,*gs]; usable=[x for x in attempts if x.get('parsed')]
    total=sum(int(x.get('items_returned') or 0) for x in usable)
    relevant=[]
    for g in gs:
        if g.get('parsed'): relevant.extend(g.get('recent_relevant_items') or [])
    unique_relevant, cross_attempt_duplicates=dedupe_recent_relevant(relevant)
    providers_positive=sorted({x['provider'] for x in usable if int(x.get('items_returned') or 0)>0})
    rdy=readiness(total>0,len(unique_relevant)>0)
    return {
        'code':member['code'],'name':member['name'],'official_name':member.get('official_name',''),'yahoo_symbol':yahoo_symbol(member['code']),
        'provider_parse_ready':len({x['provider'] for x in usable}),'retrieval_positive':total>0,
        'recent_issuer_title_hits':len(unique_relevant),'deterministic_recent_relevance_positive':len(unique_relevant)>0,
        'retrieval_ready':rdy['retrieval_ready'],'relevance_ready':rdy['relevance_ready'],'event_ready':rdy['event_ready'],'formal_news_ready':rdy['formal_news_ready'],
        'event_gate_status':rdy['event_gate_status'],'formal_gate_status':rdy['formal_gate_status'],
        'unique_recent_relevant_items':unique_relevant,
        'duplicate_recent_relevant_items_removed':sum(int(g.get('duplicate_recent_relevant_items_removed') or 0) for g in gs)+cross_attempt_duplicates,
        'providers_positive':providers_positive,'items_returned_across_sources':total,
        'retrieval_status':'ITEMS_RETURNED' if total>0 else ('PARSED_ZERO_ITEMS' if usable else 'ALL_PROVIDERS_FAILED'),
        'attempts':attempts,'model_requests':0
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--universe',default='docs/dsa-u-universe.json'); ap.add_argument('--out',default='probe/u45-news/U45_NEWS_MULTISOURCE.json'); ap.add_argument('--workers',type=int,default=4); ap.add_argument('--timeout',type=float,default=18); ap.add_argument('--days',type=int,default=7); ap.add_argument('--exclude-code',action='append',default=['09618']); args=ap.parse_args()
    members=load_universe(Path(args.universe)); excluded=set(args.exclude_code); executable=[m for m in members if m['code'] not in excluded]; cutoff=datetime.now(timezone.utc)-timedelta(days=args.days)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(lambda m:fetch_member(m,args.timeout,cutoff),executable))
    positives=sum(r['retrieval_positive'] for r in rows); any_provider=sum(r['provider_parse_ready']>0 for r in rows); both_provider=sum(r['provider_parse_ready']==2 for r in rows)
    retrieval_ready=sum(r['retrieval_ready'] for r in rows); relevance_ready=sum(r['relevance_ready'] for r in rows); event_ready=sum(r['event_ready'] for r in rows); formal_ready=sum(r['formal_news_ready'] for r in rows)
    duplicate_removed=sum(int(r.get('duplicate_recent_relevant_items_removed') or 0) for r in rows)
    yahoo_positive=sum('yahoo_finance_search' in r['providers_positive'] for r in rows); google_positive=sum('google_news_rss' in r['providers_positive'] for r in rows)
    receipt={
        'schema_version':'U45_NEWS_MULTISOURCE_v1_2','generated_at':datetime.now(timezone.utc).isoformat(),'cutoff_utc':cutoff.isoformat(),
        'universe_denominator':45,'execution_eligible_denominator':len(executable),'retained_not_currently_executable':sorted(excluded),
        'members_with_any_provider_parseable':any_provider,'members_with_both_providers_parseable':both_provider,
        'members_with_items':positives,'members_with_zero_items':len(rows)-positives,
        'members_with_recent_issuer_title_hits':relevance_ready,
        'members_retrieval_ready':retrieval_ready,'members_relevance_ready':relevance_ready,'members_event_ready':event_ready,'members_formal_news_ready':formal_ready,
        'duplicate_recent_relevant_items_removed':duplicate_removed,
        'readiness_contract':{'retrieval_ready':'at least one parsed source returned items','relevance_ready':'at least one deduplicated <=7-day item has issuer term in title','event_ready':'requires separately accepted event classification; fail-closed here','formal_news_ready':'requires formal news evidence acceptance; fail-closed here'},
        'yahoo_members_with_items':yahoo_positive,'google_members_with_items':google_positive,
        'retrieval_quality_proven':positives>0,'news_semantic_ready':0,'formal_u_acceptance_added':0,
        'model_http_requests':0,'paid_data_calls':0,'rows':rows
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('execution_eligible_denominator','members_with_any_provider_parseable','members_retrieval_ready','members_relevance_ready','members_event_ready','members_formal_news_ready','duplicate_recent_relevant_items_removed','model_http_requests')},ensure_ascii=False))
    if any_provider!=len(executable): raise SystemExit(f'NEWS_ALL_PROVIDERS_FAILED_FOR_{len(executable)-any_provider}_MEMBERS')
    if not receipt['retrieval_quality_proven']: raise SystemExit('NEWS_RETRIEVAL_QUALITY_UNPROVEN_ALL_SOURCES_ZERO')
    if event_ready or formal_ready or receipt['formal_u_acceptance_added']:
        raise SystemExit('NEWS_READINESS_FAIL_CLOSED_BREACH')

if __name__=='__main__': main()
