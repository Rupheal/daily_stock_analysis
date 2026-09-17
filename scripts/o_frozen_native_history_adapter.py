"""Runtime-only adapter that feeds an immutable preflight native history to frozen DSA.

The frozen upstream checkout is not modified. Only DataFetcherManager.get_daily_data
for the one symbol bound by the accepted preflight is intercepted. The returned rows
are byte-derived from preflight.validated_native_history; prompts, scoring, strategy,
analyzer and post-output contracts are untouched.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
from unittest.mock import patch

VERSION="O_FROZEN_NATIVE_HISTORY_ADAPTER_v1"

def _canonical(rows):
    return json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

@contextmanager
def patched_frozen_native_history(preflight):
    symbol=str(preflight.get("symbol") or "").upper()
    rows=preflight.get("validated_native_history")
    window=preflight.get("native_history_window") or {}
    if not symbol.startswith("HK") or not isinstance(rows,list) or len(rows)<21:
        raise ValueError("FROZEN_NATIVE_HISTORY_INVALID")
    dates=[str(x.get("date"))[:10] for x in rows]
    if dates!=sorted(set(dates)) or dates[-1]!=str(preflight.get("target"))[:10]:
        raise ValueError("FROZEN_NATIVE_HISTORY_WINDOW_INVALID")
    if window.get("count")!=len(rows) or str(window.get("first"))[:10]!=dates[0] or str(window.get("last"))[:10]!=dates[-1]:
        raise ValueError("FROZEN_NATIVE_HISTORY_WINDOW_UNBOUND")
    # Import original namespace only when entered, after the frozen checkout has
    # already been placed first on sys.path by the probe.
    import pandas as pd
    from data_provider.base import DataFetcherManager
    original=DataFetcherManager.get_daily_data
    applied={"version":VERSION,"count":0,"symbol":symbol,"rows":len(rows),
             "first":dates[0],"last":dates[-1],"history_sha256":hashlib.sha256(_canonical(rows)).hexdigest()}
    def bounded(instance,code,*args,**kwargs):
        if str(code or "").upper()==symbol:
            df=pd.DataFrame([dict(x) for x in rows])
            df["date"]=pd.to_datetime(df["date"])
            applied["count"]+=1
            return df,"FrozenNativeHistoryAdapter"
        return original(instance,code,*args,**kwargs)
    with patch.object(DataFetcherManager,"get_daily_data",bounded):
        yield applied
