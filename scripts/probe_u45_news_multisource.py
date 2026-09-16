#!/usr/bin/env python3
"""Model-free U45 news retrieval via independent public sources.

Primary: Yahoo Finance search API (symbol-specific finance news).
Fallback/independent cross-check: Google News RSS (issuer-name query).
Eastmoney is intentionally excluded here after the preserved passportWeb-only
failure evidence. No model credentials, LLM calls, or paid data are used.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests

UA = "Mozilla/5.0 (compatible; DSA-U45-NewsMultiSource/1.0)"
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
        rows.append({"code":code,"name":name})
    if len(rows)!=45 or len({x['code'] for x in rows})!=45:
        raise SystemExit(f"U45 denominator invariant failed: {len(rows)}")
    return rows


def yahoo_symbol(code: str) -> str:
    return f"{int(code):04d}.HK"


def safe_title(value) -> str:
    return " ".join(str(value or "").split())[:240]


def fetch_yahoo(member: dict, timeout: float) -> dict:
    symbol=yahoo_symbol(member['code'])
    started=time.monotonic()
    out={'provider':'yahoo_finance_search','query':symbol,'symbol':symbol}
    try:
        r=requests.get(YAHOO,params={'q':symbol,'quotesCount':1,'newsCount':20,'enableFuzzyQuery':'false'},headers={'User-Agent':UA,'Accept':'application/json'},timeout=(8,timeout))
        raw=r.content
        out.update(http_status=r.status_code,response_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        r.raise_for_status(); data=r.json(); news=data.get('news') or []
        if not isinstance(news,list): raise ValueError('news_not_list')
        out.update(parsed=True,items_returned=len(news),sample=[{'title':safe_title(n.get('title')),'publisher':safe_title(n.get('publisher')),'published':n.get('providerPublishTime'),'url':n.get('link')} for n in news[:3] if isinstance(n,dict)])
    except Exception as exc:
        out.update(parsed=False,items_returned=0,error_type=type(exc).__name__)
    out['elapsed_ms']=round((time.monotonic()-started)*1000)
    return out


def fetch_google(member: dict, timeout: float) -> dict:
    # Include HK/stock context but keep issuer name intact.
    query=f'"{member["name"]}" 股票 OR 港股'
    started=time.monotonic(); out={'provider':'google_news_rss','query':query}
    try:
        r=requests.get(GOOGLE_RSS,params={'q':query,'hl':'zh-TW','gl':'HK','ceid':'HK:zh-Hant'},headers={'User-Agent':UA,'Accept':'application/rss+xml, application/xml;q=0.9, */*;q=0.8'},timeout=(8,timeout))
        raw=r.content
        out.update(http_status=r.status_code,response_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        r.raise_for_status(); root=ET.fromstring(raw); items=root.findall('.//item')
        out.update(parsed=True,items_returned=len(items),sample=[{'title':safe_title(i.findtext('title')),'published':i.findtext('pubDate'),'url':i.findtext('link')} for i in items[:3]])
    except Exception as exc:
        out.update(parsed=False,items_returned=0,error_type=type(exc).__name__)
    out['elapsed_ms']=round((time.monotonic()-started)*1000)
    return out


def fetch_member(member: dict, timeout: float) -> dict:
    y=fetch_yahoo(member,timeout)
    g=fetch_google(member,timeout)
    attempts=[y,g]
    usable=[x for x in attempts if x.get('parsed')]
    total=sum(int(x.get('items_returned') or 0) for x in usable)
    providers_positive=[x['provider'] for x in usable if int(x.get('items_returned') or 0)>0]
    return {
        'code':member['code'],'name':member['name'],'yahoo_symbol':yahoo_symbol(member['code']),
        'provider_parse_ready':len(usable),'retrieval_positive':total>0,
        'providers_positive':providers_positive,'items_returned_across_sources':total,
        'retrieval_status':'ITEMS_RETURNED' if total>0 else ('PARSED_ZERO_ITEMS' if usable else 'ALL_PROVIDERS_FAILED'),
        'attempts':attempts,'model_requests':0
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--universe',default='docs/dsa-u-universe.json'); ap.add_argument('--out',default='probe/u45-news/U45_NEWS_MULTISOURCE.json'); ap.add_argument('--workers',type=int,default=4); ap.add_argument('--timeout',type=float,default=18); ap.add_argument('--exclude-code',action='append',default=['09618']); args=ap.parse_args()
    members=load_universe(Path(args.universe)); excluded=set(args.exclude_code); executable=[m for m in members if m['code'] not in excluded]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(lambda m:fetch_member(m,args.timeout),executable))
    positives=sum(r['retrieval_positive'] for r in rows); any_provider=sum(r['provider_parse_ready']>0 for r in rows); both_provider=sum(r['provider_parse_ready']==2 for r in rows)
    yahoo_positive=sum('yahoo_finance_search' in r['providers_positive'] for r in rows); google_positive=sum('google_news_rss' in r['providers_positive'] for r in rows)
    receipt={
        'schema_version':'U45_NEWS_MULTISOURCE_v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'universe_denominator':45,'execution_eligible_denominator':len(executable),'retained_not_currently_executable':sorted(excluded),
        'members_with_any_provider_parseable':any_provider,'members_with_both_providers_parseable':both_provider,
        'members_with_items':positives,'members_with_zero_items':len(rows)-positives,
        'yahoo_members_with_items':yahoo_positive,'google_members_with_items':google_positive,
        'retrieval_quality_proven':positives>0,'news_semantic_ready':0,'formal_u_acceptance_added':0,
        'model_http_requests':0,'paid_data_calls':0,'rows':rows
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('execution_eligible_denominator','members_with_any_provider_parseable','members_with_both_providers_parseable','members_with_items','yahoo_members_with_items','google_members_with_items','retrieval_quality_proven','model_http_requests')},ensure_ascii=False))
    if any_provider!=len(executable): raise SystemExit(f'NEWS_ALL_PROVIDERS_FAILED_FOR_{len(executable)-any_provider}_MEMBERS')
    if not receipt['retrieval_quality_proven']: raise SystemExit('NEWS_RETRIEVAL_QUALITY_UNPROVEN_ALL_SOURCES_ZERO')

if __name__=='__main__': main()
