#!/usr/bin/env python3
"""Model-free U45 public-news readiness probe.

Uses the existing approved HK/US/European public-news policy. This measures whether
fresh, dated company evidence is discoverable; it does not claim complete news
coverage, sentiment, or strategy acceptance.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode

from src.services.intelligence_service import IntelligenceService
from src.services import hk_company_news as n


def probe_member(service, member, now, days, regional_cache):
    code='HK'+member['code']; name=member.get('user_alias') or member.get('official_name') or code
    items=[]; diagnostics=[]
    try:
        html=n.fetch_public(service,f"https://www.futunn.com/stock/{member['code']}-HK/news")
        rows=n.parse_futu(html,code,name,now,days)
        rows=[x for x in rows if n.approved_news_origin(x)]
        items.extend(rows);diagnostics.append({'source':'futu','accepted':len(rows)})
    except Exception as exc:
        diagnostics.append({'source':'futu','error':type(exc).__name__})
    try:
        html=n.fetch_public(service,'https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news.php?'+urlencode({'code':int(member['code'])}))
        rows=[]
        for url in n.etnet_candidates(html,code,name,now,days):
            try:
                item=n.parse_etnet_article(n.fetch_public(service,url),url,code,name,now,days)
                if item and n.approved_news_origin(item): rows.append(item)
            except Exception as exc:
                diagnostics.append({'source':'etnet_article','error':type(exc).__name__})
        items.extend(rows);diagnostics.append({'source':'etnet_company','accepted':len(rows)})
    except Exception as exc:
        diagnostics.append({'source':'etnet_company','error':type(exc).__name__})
    for channel,content,publisher in regional_cache:
        try:
            rows=n.parse_regional_rss(content,publisher,code,name,now,days)
            items.extend(rows);diagnostics.append({'source':channel,'accepted':len(rows)})
        except Exception as exc:
            diagnostics.append({'source':channel,'error':type(exc).__name__})
    unique={}
    for item in items:
        unique[(item.get('url'),str(item.get('title','')).casefold())]=item
    items=list(unique.values())
    origins=sorted({tuple(n.approved_news_origin(x) or ('UNKNOWN','UNKNOWN')) for x in items})
    return {'code':member['code'],'name':name,'accepted_count':len(items),'origin_count':len(origins),'origins':[list(x) for x in origins],
            'news_ready':len(items)>0,'coverage_complete':False,'window_days':days,
            'status':'NEWS_READY_LIMITED' if items else 'NEWS_NOT_FOUND_OR_PROVIDER_BLOCKED','diagnostics':diagnostics}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--universe',required=True);ap.add_argument('--out',required=True);ap.add_argument('--days',type=int,default=3);args=ap.parse_args()
    u=json.loads(Path(args.universe).read_text(encoding='utf-8')); assert u['member_count']==45 and len(u['members'])==45
    service=IntelligenceService();now=datetime.now(timezone.utc);regional=[];global_diag=[]
    for channel,url,publisher in n._REGIONAL_FEEDS:
        try: regional.append((channel,n.fetch_public(service,url),publisher));global_diag.append({'source':channel,'fetch':'PASS'})
        except Exception as exc: global_diag.append({'source':channel,'fetch':'FAIL','error':type(exc).__name__})
    rows=[probe_member(service,m,now,args.days,regional) for m in u['members']]
    out={'schema_version':'U45_PUBLIC_NEWS_READINESS_v1','generated_at':now.isoformat(),'denominator':45,'window_days':args.days,
         'policy':'approved HK/US/European public sources; dated company evidence; no full-coverage claim','model_requests':0,
         'global_diagnostics':global_diag,'news_ready_count':sum(x['news_ready'] for x in rows),'members':rows}
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'denominator':45,'news_ready':out['news_ready_count'],'model_requests':0}))
if __name__=='__main__': main()
