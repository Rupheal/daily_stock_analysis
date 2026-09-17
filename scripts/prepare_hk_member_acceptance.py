"""Per-member preflight reusing accepted price rules and reviewed public facts.

This admits bounded issuer evidence, not complete news coverage or a BUY signal.
"""
import argparse,hashlib,json
from datetime import datetime,timedelta,timezone
from pathlib import Path


def reviewed_events(code,target,evidence,review,evidence_sha,decision_at):
    from o_semantic_handoff_contract import aware
    if review['source_evidence_sha256']!=evidence_sha:raise ValueError('REVIEW_HASH_MISMATCH')
    r=next((r for r in review['members'] if r['code']==code),None)
    if not r or r['status']!='PASS_REVIEWED_COVERAGE' or not r['company_identity_verified']:raise ValueError('NO_REVIEWED_ISSUER_EVIDENCE')
    if aware(r['reviewed_at'])>aware(decision_at):raise ValueError('FUTURE_REVIEW')
    approved={s['sha256']:s for s in r['sources']};sources={s['sha256']:s for s in evidence['sources'] if s['code']==code};out=[]
    for f in evidence['facts']:
        if f['code']!=code or f['source_sha256'] not in approved:continue
        s=sources[f['source_sha256']]
        if s['url']!=approved[s['sha256']]['url']:raise ValueError('REVIEW_SOURCE_MISMATCH')
        if aware(s['available_at'])>aware(decision_at):raise ValueError('FUTURE_SOURCE')
        day=s['published_date'].replace('.','-')
        # Date-only publication: retain precision; use a conservative three-day window.
        if not (aware(decision_at)-timedelta(days=2)).date().isoformat()<=day<=aware(decision_at).date().isoformat():continue
        if f['kind']!='ISSUER_SHARE_REPURCHASE':raise ValueError('UNSUPPORTED_REVIEWED_FACT')
        summary=f"公司披露 {f['event_date']} 回购 {f['shares']} 股，金额 {f['amount']} {f['currency']}，每股价格区间 {f['low']}–{f['high']} {f['currency']}。仅为已核验回购披露，不代表完整新闻覆盖、外资流入或买入信号。"
        out.append({'event_id':code+'-repurchase-'+f['event_date'],'title':f"HK{code} {f['event_date']} 股份回购披露",'summary':summary,'source':'Issuer original disclosure','published_at':day,'publication_precision':'date_only','source_urls':[s['url']],'source_records':[{'source':'Issuer original disclosure','url':s['url'],'sha256':s['sha256'],'available_at':s['available_at']}],'evidence_kind':'公司原始公告中的已复核事实；有限范围','full_coverage':False})
    if not out:raise ValueError('NO_RECENT_REVIEWED_EVENT')
    return out


def prepare(code,target,universe,cache,root):
    import pandas as pd,yfinance as yf
    from prepare_xiaomi_acceptance import compare_prices,atomic_json
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts
    from data_provider.tencent_fetcher import TencentFetcher
    root.mkdir(parents=True,exist_ok=False)
    u=json.loads(universe.read_text());member=next(x for x in u['members'] if x['code']==code)
    assert u['full_union_verified'] and member['channels']
    history=json.loads(cache.read_text());assert history['target_session']==target
    item=history['histories'][code]
    if not item['tencent'] or not item.get('independent_source',{}).get('sha256'):raise ValueError('PERSISTED_TENCENT_SOURCE_MISSING')
    native=item.get('native') or []
    from audit_dual_history_cache import normalized
    native=normalized(native,target); native_dates={r['date'] for r in native}
    df=pd.DataFrame([r for r in item['tencent'] if r['date'] in native_dates]);fetcher=TencentFetcher();df=fetcher._calculate_indicators(fetcher._clean_data(fetcher._normalize_data(df,'HK'+code)))
    df['date']=pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d');df=df[df['date']<=target].sort_values('date')
    end=datetime.fromisoformat(target)+timedelta(days=1);start=datetime.fromisoformat(native[0]['date'])
    h=yf.Ticker(f'{int(code):04d}.HK').history(start=start.date().isoformat(),end=end.date().isoformat(),auto_adjust=True,actions=True,repair=True,timeout=20)
    if h.empty:raise ValueError('INDEPENDENT_YAHOO_HISTORY_EMPTY')
    y=h.reset_index();y.columns=[str(c).lower() for c in y.columns];y['date']=pd.to_datetime(y['date']).dt.strftime('%Y-%m-%d');y=y[y['date']<=target].sort_values('date')
    atomic_json(root/'independent_history.json',{'provider':'Yahoo via yfinance','adjustment':'auto_adjust=True,repair=True','source_locator':f'https://query1.finance.yahoo.com/v8/finance/chart/{int(code):04d}.HK','retrieved_at':datetime.now(timezone.utc).isoformat(),'result':y.to_dict('records')})
    overlap,reconciliation=compare_prices(df,y,target,True,minimum_overlap=len(native))
    if set(df['date'])!=native_dates or set(y['date'])!=native_dates:raise ValueError('NATIVE_WINDOW_NOT_COMPLETELY_VALIDATED')
    # Price rules are unchanged. Explicitly distinguish exact comparisons from the legacy latest-bar bound.
    today,yesterday=df.iloc[-1].to_dict(),df.iloc[-2].to_dict();context={'today':today,'yesterday':yesterday,'volume_change_ratio':round(today['volume']/yesterday['volume'],2)}
    validate_daily_context(context,target)
    now=datetime.now(timezone.utc).isoformat();base=Path(__file__).resolve().parents[1]/'docs/runtime';eraw=(base/'RUN032_PRIMARY_EVIDENCE.json').read_bytes();review=json.loads((base/'RUN032_PRIMARY_REVIEW.json').read_text())
    events=reviewed_events(code,target,json.loads(eraw),review,hashlib.sha256(eraw).hexdigest(),now)
    urls=sorted({s for e in events for s in e['source_urls']})
    preflight={'passed':True,'symbol':'HK'+code,'stock_name':member['official_name'],'prices_passed':True,'prepared_at':now,'target':target,'today':today,'yesterday':yesterday,'facts':daily_consistency_facts(context),'price_reconciliation':reconciliation,'overlap':overlap,'validated_native_history':native,'native_history_window':{'first':native[0]['date'],'last':target,'count':len(native),'scope':'Every bar in frozen native data-only window; unrelated earlier archive conflicts retained separately','ma60_supported':len(native)>=60},'component_status':{'prices':'passed','news':'passed_limited_coverage'},'news_count':len(urls),'allowed_news_urls':urls,'company_news_evidence':events,'execution_contract':{'realtime_quote_available':False,'target_session':target},'hk_report_contract':{'required_risk_ids':[]},'risk_review_complete':False,'limitation':'Only reviewed issuer repurchases are admitted. No exhaustive risk/news review, execution clearance, U rule acceptance or whole-pool ranking.','sources':{'universe_sha256':hashlib.sha256(universe.read_bytes()).hexdigest(),'history_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'primary_evidence_sha256':hashlib.sha256(eraw).hexdigest(),'tencent':item['independent_source']}}
    atomic_json(root/'preflight.json',preflight)
    return {'symbol':'HK'+code,'preflight':'PASS_BOUNDED_NATIVE_RESEARCH','overlap':overlap,'news_count':len(events),'model_requests':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--code',required=True);p.add_argument('--target',required=True);p.add_argument('--universe',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    try:
        print(json.dumps(prepare(a.code,a.target,a.universe,a.cache,a.out),ensure_ascii=False))
    except Exception as exc:
        import re
        reason=str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_ :.-]{2,150}',str(exc)) else type(exc).__name__
        if a.out.exists(): (a.out/'FREE_PREFLIGHT_STATUS.json').write_text(json.dumps({'status':'FAILED','reason':reason,'model_requests':0}))
        raise
