"""External retrieval adapter that replays an already frozen native OHLCV window.

No frozen upstream source, scoring, prompt, model, or strategy is changed. This
adapter only prevents mutable Yahoo history from drifting between the accepted
preflight and the one provider send. Target-session independent validation stays
mandatory before this adapter can be used.
"""
from __future__ import annotations
from contextlib import contextmanager
import json, os
from pathlib import Path
from unittest.mock import patch

FIELDS={"open","high","low","close","volume"}

def _field(col):
    if isinstance(col,tuple):
        parts=[str(x).strip().lower() for x in col]
        return next((x for x in FIELDS if x in parts),None)
    x=str(col).strip().lower()
    return x if x in FIELDS else None

def _target_aliases(symbol):
    s=symbol.upper()
    digits=s[2:] if s.startswith("HK") else s.split(".")[0]
    stripped=digits.lstrip("0") or "0"
    return {s, f"{stripped.zfill(4)}.HK", f"{digits}.HK"}

def _is_target_request(args,kwargs,symbol):
    v=kwargs.get("tickers")
    if v is None and args:v=args[0]
    if isinstance(v,str): parts=[x.upper() for x in v.replace(","," ").split()]
    elif isinstance(v,(list,tuple,set)): parts=[str(x).upper() for x in v]
    else: parts=[]
    return bool(parts) and all(x in _target_aliases(symbol) for x in parts)

@contextmanager
def patched_yahoo_frozen_history(preflight_path):
    import yfinance as yf
    p=Path(preflight_path); pre=json.loads(p.read_text())
    symbol=pre["symbol"].upper()
    expected=pre.get("validated_native_history") or []
    if pre.get("passed") is not True or len(expected)<21:
        raise ValueError("FROZEN_HISTORY_PREFLIGHT_INVALID")
    byday={str(x["date"])[:10]:x for x in expected}
    original=yf.download
    audit={"enabled":True,"symbol":symbol,"aliases":sorted(_target_aliases(symbol)),
           "expected_count":len(expected),"calls":0,"rows_replayed":0,
           "cells_replayed":0,"missing_expected_dates":[]}

    def frozen_download(*args,**kwargs):
        df=original(*args,**kwargs)
        if not _is_target_request(args,kwargs,symbol) or getattr(df,"empty",False):
            return df
        out=df.copy(); present=set()
        for idx in out.index:
            day=str(idx)[:10]; ref=byday.get(day)
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
