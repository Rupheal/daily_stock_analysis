"""External retrieval adapter that replays the already frozen native OHLCV window.

This does not change the frozen upstream checkout, scoring, prompt, model, or strategy.
It only prevents mutable Yahoo history from drifting between preflight and provider send.
The caller must still independently validate the target session before using this adapter.
"""
from __future__ import annotations
from contextlib import contextmanager
import json, os
from pathlib import Path
from unittest.mock import patch

FIELDS={"open":"open","high":"high","low":"low","close":"close","volume":"volume"}

def _field(col):
    if isinstance(col,tuple):
        parts=[str(x).strip().lower() for x in col]
        for name in FIELDS:
            if name in parts:return name
        return None
    x=str(col).strip().lower()
    return x if x in FIELDS else None

def _is_target_request(args,kwargs,symbol):
    v=kwargs.get("tickers")
    if v is None and args:v=args[0]
    if isinstance(v,str): parts=[x.upper() for x in v.replace(","," ").split()]
    elif isinstance(v,(list,tuple,set)): parts=[str(x).upper() for x in v]
    else: parts=[]
    normalized={symbol.upper(),symbol[2:]+".HK"}
    return bool(parts) and all(x in normalized for x in parts)

@contextmanager
def patched_yahoo_frozen_history(preflight_path:str|Path):
    import yfinance as yf
    p=Path(preflight_path)
    pre=json.loads(p.read_text())
    symbol=pre["symbol"].upper()
    expected=pre.get("validated_native_history") or []
    if not expected or pre.get("passed") is not True:
        raise ValueError("FROZEN_HISTORY_PREFLIGHT_INVALID")
    byday={str(x["date"])[:10]:x for x in expected}
    original=yf.download
    audit={"enabled":True,"symbol":symbol,"expected_count":len(expected),"calls":0,
           "rows_replayed":0,"cells_replayed":0,"missing_expected_dates":[]}

    def frozen_download(*args,**kwargs):
        df=original(*args,**kwargs)
        if not _is_target_request(args,kwargs,symbol) or getattr(df,"empty",False):
            return df
        out=df.copy()
        present=set()
        for idx in out.index:
            day=str(idx)[:10]
            ref=byday.get(day)
            if ref is None: continue
            present.add(day); audit["rows_replayed"]+=1
            for col in out.columns:
                f=_field(col)
                if f:
                    out.at[idx,col]=ref[f]
                    audit["cells_replayed"]+=1
        audit["calls"]+=1
        audit["missing_expected_dates"]=sorted(set(byday)-present)
        return out

    try:
        with patch.object(yf,"download",frozen_download):
            yield audit
    finally:
        path=os.environ.get("DSA_FROZEN_HISTORY_AUDIT_PATH")
        if path:
            Path(path).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
