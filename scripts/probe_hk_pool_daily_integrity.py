"""Free comparison of retained public OHLCV tables; no model or credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hk_batch_integrity import canonical, native_rows, validate_rows, tencent_rows, compare_history


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-db', type=Path, required=True)
    p.add_argument('--upgraded-db', type=Path, required=True)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--target', required=True)
    p.add_argument('--reuse-cache', type=Path)
    args = p.parse_args()
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=False)
    requests, failures = {}, {}
    expected = {'O': 'f1b50fa459e229455fddadb6fbd23823199ec5ea4927d289f54ad683ed9a045b',
                'U': '4de088566416b6535a931a62107303cbfe346ac673e04f8ee7a5c3b8f2b0e663'}
    for track, database in [('U', args.upgraded_db), ('O', args.original_db)]:
        if hashlib.sha256(database.read_bytes()).hexdigest() != expected[track]:
            raise ValueError('retained database hash mismatch')
        universe = json.loads((args.repo / ('docs/dsa-' + track.lower() + '-universe.json')).read_text())
        codes = [canonical(r['code']) for r in universe['members']]
        if len(set(codes)) != universe['member_count']:
            raise ValueError('universe denominator mismatch')
        rows_out = []
        lock = Lock()
        def check(code):
            record = {'code': code, 'status': 'isolated'}
            try:
                native = native_rows(database, code)
                validate_rows(native, args.target)
                previous = args.reuse_cache / (code + '.json') if args.reuse_cache else None
                if code not in requests and previous and previous.is_file():
                    requests[code] = json.loads(previous.read_text())['payload']
                if track == 'U' and 'Tencent' in str(native[-1].get('data_source')):
                    independent = native_rows(args.original_db, code)
                    if independent and independent[-1].get('data_source'):
                        provider = independent[-1]['data_source']
                        adjustment = 'retained original provider adjusted values; database hash recorded'
                        record['independent_reused_original_data'] = True
                    else:
                        import yfinance as yf
                        frame = yf.Ticker(code[2:].lstrip('0').zfill(4)+'.HK').history(period='3mo', auto_adjust=True, actions=True, timeout=20)
                        independent = [{'date':str(idx)[:10], **{k:row[k.title()] for k in ['open','high','low','close','volume']}} for idx,row in frame.iterrows()]
                        provider, adjustment = 'YfinanceFetcher', 'auto_adjust=True'
                        (root/(code+'-yahoo.json')).write_text(json.dumps({'provider':provider,'retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':independent},default=str))
                elif code not in requests:
                    url = 'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?' + urlencode({'param': code.lower()+',day,,,180,qfq'})
                    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20) as response:
                        raw = response.read(2000000)
                    payload = json.loads(raw)
                    receipt = {'code': code, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'url': url,
                               'sha256': hashlib.sha256(raw).hexdigest(), 'payload': payload}
                    (root / (code + '.json')).write_text(json.dumps(receipt, ensure_ascii=False))
                    requests[code] = payload
                if not (track == 'U' and 'Tencent' in str(native[-1].get('data_source'))):
                    independent, adjustment = tencent_rows(requests[code], code)
                    provider = 'TencentFetcher'
                independent = [r for r in independent if r['date'] <= args.target]
                audit = compare_history(native, independent, args.target, provider)
                record.update(audit=audit, adjustment=adjustment, native_source=native[-1].get('data_source'), independent_provider=provider)
                if audit['passed']:
                    record['status'] = 'passed_21_observed_daily_bars'
                else:
                    record['reason'] = 'independent_daily_disagreement'
            except Exception as exc:
                record['reason'] = type(exc).__name__+':'+str(exc)[:150]
                if hasattr(exc, 'public_row'): record['invalid_bar'] = exc.public_row
            with lock:
                rows_out.append(record)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(check, codes))
        rows_out.sort(key=lambda r: r['code'])
        isolated = [r for r in rows_out if r['status']=='isolated']
        reasons = {}
        for r in isolated: reasons[r['reason']] = reasons.get(r['reason'], 0)+1
        report = {'track': track, 'target': args.target, 'denominator': len(codes),
                  'passed': len(rows_out)-len(isolated), 'isolated': len(isolated), 'reasons': reasons,
                  'database_sha256': expected[track], 'coverage': rows_out,
                  'model_http_requests': 0, 'model_fees_cny': '0', 'full_pool_top3_approved': False,
                  'scope': 'public market data, last 21 observed OHLCV comparisons; entire retained history geometry checked'}
        (root / (track+'-integrity.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('FREE_POOL_INTEGRITY',json.dumps({k:v for k,v in report.items() if k!='coverage'},ensure_ascii=False),flush=True)
        print('ISOLATED_PUBLIC_MARKET_CODES',json.dumps({'track':track,'codes':[{'code':r['code'],'reason':r['reason']} for r in isolated]},ensure_ascii=False),flush=True)
        print('PUBLIC_DATA_FAILURE_EXAMPLES',json.dumps({'track':track,'examples':isolated[:12]},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
