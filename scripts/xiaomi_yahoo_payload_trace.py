"""Observe the exact Yahoo decoded-JSON -> yfinance parser boundary.

Uses the SAME preflight and the SAME network calls. Returns parser result without
editing data. Last three daily points only; no credentials or raw model content.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path


def summarize_payload(data):
    meta=data.get('meta') or {}
    tz_name=meta.get('exchangeTimezoneName')
    zone=ZoneInfo(tz_name) if tz_name else None
    times=data.get('timestamp') or []
    indicators=data.get('indicators') or {}
    quotes=(indicators.get('quote') or [{}])[0]
    adj=(indicators.get('adjclose') or [{}])[0].get('adjclose')
    rows=[]
    for i in range(max(0,len(times)-3),len(times)):
        row={'epoch':times[i], 'session':datetime.fromtimestamp(times[i],timezone.utc).astimezone(zone).date().isoformat() if zone else None}
        for key in ('open','high','low','close','volume'):
            values=quotes.get(key)
            value=values[i] if isinstance(values,list) and i<len(values) else 'MISSING_ARRAY_ELEMENT'
            row[key]={'type':type(value).__name__,'value_repr':repr(value)[:60]}
        value=adj[i] if isinstance(adj,list) and i<len(adj) else 'MISSING_ARRAY_ELEMENT'
        row['adj_close']={'type':type(value).__name__,'value_repr':repr(value)[:60]}
        rows.append(row)
    return {'boundary':'decoded_Yahoo_chart_result_before_parse_quotes',
            'symbol':meta.get('symbol'),'exchange_timezone':tz_name,'rows':len(times),'last_rows':rows,
            'decoded_payload_canonical_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=True).encode()).hexdigest(),
            'hash_is_raw_HTTP_bytes':False}


@contextmanager
def observe_parser(utils_module,records):
    original=utils_module.parse_quotes
    def wrapped(data,*args,**kwargs):
        try: record=summarize_payload(data)
        except Exception as exc: record={'observation_error':type(exc).__name__}
        records.append(record)
        result=original(data,*args,**kwargs)
        record['parser_returned']=True
        return result
    utils_module.parse_quotes=wrapped
    try:yield
    finally:utils_module.parse_quotes=original


def main():
    if any(k.startswith('LLM_') or 'DEEPSEEK' in k for k in os.environ):
        raise RuntimeError('MODEL_CREDENTIAL_PRESENT_IN_MODEL_FREE_JOB')
    import yfinance
    import yfinance.scrapers.history as history_module
    import xiaomi_preflight_field_diagnostics as diagnostics
    records=[]
    with observe_parser(history_module.utils,records):
        rc=diagnostics.main()
    path=Path('field-diagnostics/strict-preflight-fields.json')
    report=json.loads(path.read_text())
    report['yahoo_parser_boundary']={
        'yfinance_version':yfinance.__version__,
        'parser_source_sha256':hashlib.sha256(Path(history_module.utils.__file__).read_bytes()).hexdigest(),
        'target_session':report.get('target_session'),
        'extra_network_requests_added_by_observer':0,
        'observations':records,
        'replacement_prices_created':False}
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    print('YAHOO_PARSER_BOUNDARY',json.dumps(report['yahoo_parser_boundary'],ensure_ascii=False,allow_nan=False))
    return rc

if __name__=='__main__':
    raise SystemExit(main())
