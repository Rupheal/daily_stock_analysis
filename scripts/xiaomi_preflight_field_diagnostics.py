"""Bounded, model-free diagnostics around the existing strict Xiaomi preflight.

No fallback, dropped rows, changed tolerance, model key or authorization edit.
Public output contains field-shape diagnostics, not prompts/news/raw model input.
"""
from __future__ import annotations
import json
import math
import os
import re
from pathlib import Path

FIELDS = ('open', 'high', 'low', 'close', 'volume')

def inspect_frame(frame, source):
    report = {'source': source, 'rows': len(frame), 'columns': [str(x) for x in frame.columns],
              'first_session': None, 'last_session': None, 'fields': {}}
    if len(frame) and 'date' in frame.columns:
        report.update(first_session=str(frame.iloc[0]['date']), last_session=str(frame.iloc[-1]['date']))
    for field in FIELDS:
        failures = []
        types = {}
        if field not in frame.columns:
            report['fields'][field] = {'status':'MISSING_COLUMN','invalid_count':len(frame),'examples':[]}
            continue
        for idx, value in frame[field].items():
            type_name = type(value).__module__+'.'+type(value).__name__
            types[type_name] = types.get(type_name,0)+1
            try:
                valid = not isinstance(value, bool) and math.isfinite(float(value))
            except (TypeError,ValueError,OverflowError):
                valid = False
            if not valid:
                day = str(frame.loc[idx, 'date']) if 'date' in frame else 'UNKNOWN'
                failures.append({'session':day,'python_type':type_name,'value_repr':str(value)[:60]})
        report['fields'][field] = {'status':'NONFINITE_OR_NONNUMERIC' if failures else 'FINITE',
             'invalid_count':len(failures),'value_types':types,'examples':failures[:20]}
    return report

def probe_yahoo_target_boundary(target, ticker_factory):
    """Two bounded diagnostic reads; never replace accepted adjusted inputs."""
    from datetime import date, timedelta
    target_date=date.fromisoformat(target)
    start=(target_date-timedelta(days=7)).isoformat()
    end=(target_date+timedelta(days=1)).isoformat()
    out=[]
    for adjusted in (False,True):
        item={'auto_adjust':adjusted,'start':start,'end_exclusive':end,
              'target_session':target,'diagnostic_only':True,'repair':False}
        try:
            h=ticker_factory('1810.HK').history(start=start,end=end,auto_adjust=adjusted,
                actions=True,keepna=True,repair=False,timeout=20)
            df=h.reset_index()
            df.columns=[str(c).lower() for c in df.columns]
            df['date']=df['date'].astype(str).str[:10]
            item['frame']=inspect_frame(df,'Yahoo explicit boundary adjusted='+str(adjusted))
            rows=df[df['date']==target]
            item['target_count']=len(rows)
            if len(rows)==1:
                row=rows.iloc[0]
                item['target_values']={k:str(row[k]) for k in FIELDS+('adj close','dividends','stock splits') if k in row}
        except Exception as exc:
            item['failure_type']=type(exc).__name__
        out.append(item)
    return out

def main():
    prohibited = [k for k in os.environ if k.startswith('LLM_') or 'DEEPSEEK' in k]
    if prohibited:
        raise RuntimeError('MODEL_CREDENTIAL_PRESENT_IN_MODEL_FREE_JOB')
    import prepare_xiaomi_acceptance_targeted as targeted
    base = targeted.base
    root = Path('probe')
    output = Path('field-diagnostics')
    output.mkdir(exist_ok=True)
    report = {'schema_version':1,'run_id':os.getenv('GITHUB_RUN_ID'),
        'commit':os.getenv('GITHUB_SHA'),'scope':'strict_existing_preflight_field_diagnostics',
        'allow_partial_news':False,'model_http_requests':0,'request_authorized':False,
        'thresholds_unchanged':True,'data_rows_dropped':0,'source_frames':[],
        'preflight_passed':False,'failure_type':None,'failure_code':None}
    original = base.compare_prices
    def wrapped(primary, independent, target, *args, **kwargs):
        report['target_session'] = str(target)
        report['source_frames'] = [inspect_frame(primary,'Tencent normalized'),inspect_frame(independent,'Yahoo independent')]
        return original(primary,independent,target,*args,**kwargs)
    base.compare_prices = wrapped
    try:
        audit, receipt = targeted.prepare_targeted(root=root,allow_partial_news=False)
        report['preflight_passed'] = audit.get('passed') is True and receipt.get('target_match') is True
        report['target_receipt'] = receipt
        report['components'] = audit.get('component_status',{})
        report['news_count'] = audit.get('news_count')
        report['news_origins_count'] = len(audit.get('origins',[]))
        report['price_reconciliation'] = audit.get('price_reconciliation')
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        message = str(exc)
        report['failure_code'] = message if re.fullmatch(r'[A-Z][A-Z0-9_]{0,150}',message) else 'NON_CODE_EXCEPTION_SEE_COMPONENT_STATUS'
        if (root/'target-session-receipt.json').exists():
            receipt=json.loads((root/'target-session-receipt.json').read_text())
            report['target_receipt']={k:v for k,v in receipt.items() if k not in ('failure_message',)}
        if (root/'acceptance-queue.json').exists():
            report['components']=json.loads((root/'acceptance-queue.json').read_text()).get('tasks',{})
        if report['failure_code'].startswith('PRICE_') and report.get('target_session'):
            report['bounded_yahoo_followup']=probe_yahoo_target_boundary(report['target_session'],base.yf.Ticker)
    finally:
        base.compare_prices=original
        (output/'strict-preflight-fields.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    print('STRICT_PREFLIGHT_FIELDS',json.dumps(report,ensure_ascii=False,allow_nan=False))
    return 0 if report['preflight_passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
