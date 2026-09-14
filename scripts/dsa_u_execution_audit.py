"""Append-only per-member U readiness audit; never creates scores or BUY signals."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def fetch(url, path):
    if path.exists():
        raw = path.read_bytes()
        return raw, {'source': url, 'cache_reused': True, 'sha256': hashlib.sha256(raw).hexdigest()}
    receipt = {'source': url, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    try:
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as r:
            raw = r.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError('bounded_response_exceeded')
        path.write_bytes(raw)
        receipt.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        return raw, receipt
    except Exception as e:
        receipt.update(error=type(e).__name__+': '+str(e))
        return None, receipt


def valid(row):
    try:
        o, h, l, c, v = [float(row[k]) for k in ('open','high','low','close','volume')]
        return all(math.isfinite(x) for x in (o,h,l,c,v)) and 0 < l <= min(o,c)+1e-6 and max(o,c) <= h+1e-6 and v >= 0
    except (TypeError, ValueError, KeyError):
        return False


def yahoo_rows(raw, session):
    p = json.loads(raw)['chart']['result'][0]
    q = p['indicators']['quote'][0]
    out = {}
    for i, t in enumerate(p['timestamp']):
        day = datetime.fromtimestamp(t, timezone(timedelta(hours=8))).date().isoformat()
        if day <= session:
            out[day] = {k: q[k][i] for k in ('open','high','low','close','volume')}
    return out, p['meta']


def tencent_rows(raw, code, session):
    payload = json.loads(raw)
    if payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
        raise ValueError('TENCENT_SOURCE_REJECTED: '+str(payload.get('msg')))
    data = payload['data']['hk'+code]
    if not data.get('day'):
        raise ValueError('UNADJUSTED_DAY_UNAVAILABLE_NO_QFQ_SUBSTITUTION')
    # A qfqday fallback would silently change the price basis: never use it.
    out = {}
    for z in data.get('day', []):
        if str(z[0]) <= session:
            out[str(z[0])] = dict(zip(('open','close','high','low','volume'), map(float, z[1:6])))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--universe', type=Path, required=True)
    ap.add_argument('--sse', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--session', required=True)
    ap.add_argument('--run-id', required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    members = json.loads(a.universe.read_text())['members']
    assert len(members) == 45 and len({m['code'] for m in members}) == 45
    sse = json.loads(a.sse.read_text())['result']
    assert {x['UPDATE_DATE'] for x in sse} == {a.session}
    buyable = {x['SECURITY_CODE'] for x in sse if x['SECURITY_TYPE']=='股票' and x['TRADE_FLAG']=='1'}

    def member(m):
        code=m['code']; folder=a.output/code; folder.mkdir()
        row={'code':code,'name':m['user_alias'],'sse_buyable':code in buyable,'source_receipts':[],
             'technical_status':'NOT_ACCEPTED','news_status':'NOT_REVIEWED',
             'capital_tide_status':'UNKNOWN','trade_plan_status':'NOT_ACCEPTED',
             'fee_fx_lot_status':'NOT_ACCEPTED','model_score':None,'rank':None,
             'execution_qualified':False,'action':'WAIT'}
        urls=[('yahoo','https://query1.finance.yahoo.com/v8/finance/chart/'+code.lstrip('0').zfill(4)+'.HK?range=3mo&interval=1d'),
              ('tencent','https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?'+urlencode({'param':'hk'+code+',day,,,180'}))]
        parsed={}
        for source,url in urls:
            raw,receipt=fetch(url,folder/(source+'.json')); row['source_receipts'].append(receipt)
            try:
                if raw is None: continue
                if source=='yahoo':
                    parsed[source],meta=yahoo_rows(raw,a.session)
                    row['yahoo_price_time']=datetime.fromtimestamp(meta['regularMarketTime'],timezone.utc).isoformat()
                else:parsed[source]=tencent_rows(raw,code,a.session)
            except Exception as e:receipt['parse_error']=type(e).__name__+': '+str(e)
        row['latest_bars']={s:r.get(a.session) for s,r in parsed.items()}
        row['latest_geometry']={s:valid(r.get(a.session,{})) for s,r in parsed.items()}
        y=parsed.get('yahoo',{}); t=parsed.get('tencent',{})
        days=sorted(set(y)&set(t))[-21:]
        row['common_sessions']=len(days)
        row['latest_common_session']=days[-1] if days else None
        row['geometry_bad_sessions']=[d for d in days if not valid(y[d]) or not valid(t[d])]
        differences=[]
        for d in days:
            for f in ('open','high','low','close'):
                if y[d].get(f) is not None and t[d].get(f) is not None:
                    differences.append(abs(float(y[d][f])-float(t[d][f])))
        row['max_raw_price_difference']=max(differences) if differences else None
        row['legacy_0_005_diagnostic']=bool(len(days)==21 and days[-1]==a.session and not row['geometry_bad_sessions'] and differences and max(differences)<=0.005)
        row['volume_mismatch_sessions']=[d for d in days if y[d].get('volume')!=t[d].get('volume')]
        recent=sorted(y)[-20:]
        if len(recent)==20 and recent[-1]==a.session and all(valid(y[d]) for d in recent):
            closes=[float(y[d]['close']) for d in recent]
            row['single_source_reference_only']={'close':closes[-1],**{'ma'+str(n):sum(closes[-n:])/n for n in (5,10,20)}}
        row['blocking_reasons']=['NEWS_NOT_REVIEWED','CAPITAL_TIDE_UNKNOWN','TRADE_PLAN_NOT_ACCEPTED','EXECUTION_COSTS_NOT_VERIFIED']
        if not row['legacy_0_005_diagnostic']:row['blocking_reasons'].append('PRICE_HISTORY_NOT_ACCEPTED')
        if row['volume_mismatch_sessions']:row['blocking_reasons'].append('RAW_VOLUME_DIFFERENCES_RETAINED')
        if code not in buyable:row['blocking_reasons'].append('NOT_ON_SSE_BUYABLE_LIST_SZSE_RECHECK_REQUIRED')
        (folder/'audit.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
        return row

    rows=list(ThreadPoolExecutor(max_workers=6).map(member,members))
    report={'run_id':a.run_id,'session':a.session,'completed_at':datetime.now(timezone.utc).isoformat(),
            'denominator':45,'rows':rows,'qualified_count':0,'top3':[],
            'latest_geometry_both':sum(all(r['latest_geometry'].get(s,False) for s in ('yahoo','tencent')) for r in rows),
            'legacy_price_diagnostic_count':sum(r['legacy_0_005_diagnostic'] for r in rows),
            'model_requests':0,'official_close_verified':False,
            'basis':'unadjusted price comparison diagnostic only; no new tolerances or scores promoted',
            'universe_sha256':hashlib.sha256(a.universe.read_bytes()).hexdigest(),
            'sse_sha256':hashlib.sha256(a.sse.read_bytes()).hexdigest()}
    (a.output/'U45_EXECUTION_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


if __name__=='__main__':main()
