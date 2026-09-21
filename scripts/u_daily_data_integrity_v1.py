"""R0 price integrity only; no ranking, BUY, provider inference or fills."""
from __future__ import annotations
import math,re
from datetime import date,timedelta

def canonical_code(value):
    text=str(value)
    if not re.fullmatch(r'[0-9]{1,5}',text) or int(text)==0:raise ValueError('INVALID_HK_SECURITY_CODE')
    return text.zfill(5)

def yahoo_symbol(value):
    return f'{int(canonical_code(value)):04d}.HK'

def valid_bar(row):
    try:
        vals=[row[k] for k in ('open','high','low','close','volume')]
        if any(isinstance(v,bool) for v in vals):return False
        o,h,lo,c,v=map(float,vals)
        return all(map(math.isfinite,(o,h,lo,c,v))) and 0<lo<=min(o,c)<=max(o,c)<=h and v>=0
    except (KeyError,TypeError,ValueError):return False

def normalize_history(rows,target):
    date.fromisoformat(target);seen=set();result=[]
    for row in rows:
        d=str(row.get('date') or '')[:10];date.fromisoformat(d)
        if d>target:continue
        if d in seen:raise ValueError('DUPLICATE_DAILY_BAR')
        seen.add(d)
        if not valid_bar(row):raise ValueError('INVALID_OHLCV_BAR')
        result.append({'date':d,**{k:float(row[k]) for k in ('open','high','low','close','volume')}})
    return sorted(result,key=lambda x:x['date'])

def load_history(code,target):
    import yfinance as yf
    symbol=yahoo_symbol(code)
    end=(date.fromisoformat(target)+timedelta(days=1)).isoformat()
    start=(date.fromisoformat(target)-timedelta(days=120)).isoformat()
    frame=yf.download(symbol,start=start,end=end,interval='1d',auto_adjust=False,progress=False,threads=False,multi_level_index=False)
    if frame is None or frame.empty:return []
    required=('Open','High','Low','Close','Volume')
    if frame.columns.nlevels!=1 or frame.columns.has_duplicates or not set(required)<=set(frame.columns):raise ValueError('UNEXPECTED_YAHOO_COLUMN_SCHEMA')
    rows=[{'date':ts.date().isoformat(),**{k.lower():row[k] for k in required}} for ts,row in frame.iterrows()]
    return normalize_history(rows,target)

def assess_refresh(universe,member,close,target):
    expected=[canonical_code(x['code']) for x in universe.get('members',[])]
    if len(expected)!=45 or len(set(expected))!=45:raise ValueError('U45_UNIVERSE_INVALID')
    if member.get('target_session')!=target or close.get('target_session')!=target:raise ValueError('U_PRICE_TARGET_SESSION_MISMATCH')
    reports=member.get('members') or [];facts=close.get('facts') or []
    rc=[canonical_code(x['code']) for x in reports];fc=[canonical_code(x['code']) for x in facts]
    if len(rc)!=len(set(rc)) or len(fc)!=len(set(fc)) or set(fc)!=set(expected) or not set(rc)<=set(expected):raise ValueError('U_PRICE_MEMBER_SET_MISMATCH')
    rmap=dict(zip(rc,reports));fmap=dict(zip(fc,facts));valid=[]
    for code in expected:
        f=fmap[code];r=rmap.get(code,{})
        if (f.get('current_valid_bar') is True and f.get('target_session')==target and f.get('latest_date')==target and valid_bar(f) and r.get('data_session')==target and r.get('status')=='PRODUCTION_TECHNICAL_FACT_REPORT' and int(r.get('history_bars',0))>=21 and (r.get('facts') or {}).get('close')==f.get('close')):valid.append(code)
    if member.get('current_member_count')!=len(reports) or close.get('current_valid_count')!=sum(x.get('current_valid_bar') is True for x in facts):raise ValueError('U_DECLARED_COVERAGE_COUNT_MISMATCH')
    if member.get('model_http_requests',0)!=0 or close.get('model_http_requests',0)!=0:raise ValueError('R0_MODEL_CALL_BOUNDARY')
    complete=len(valid)==45
    return {'r0_refresh_complete':complete,'r0_price_refresh_complete':complete,'r0_scan_denominator':45,'current_member_count':len(reports),'current_valid_count':len(valid),'missing_or_invalid_codes':[c for c in expected if c not in valid],'state':'R0_PRICE_REFRESH_COMPLETE' if complete else 'WAIT_U_PRICE_DATA','paid_model_calls':0,'real_orders':0,'formal_generation_complete':False}
