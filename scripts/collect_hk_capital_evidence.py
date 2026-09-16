"""Bounded, model-free public evidence collection; never produces trade signals."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = 'capital-evidence-v1'
LIMIT = 2_000_000


def clock(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result


def number(value):
    result = Decimal(str(value).replace(',', ''))
    if not result.is_finite():
        raise ValueError('NONFINITE_VALUE')
    return result


def parse_hkex(raw, target):
    match = re.fullmatch(r'\s*tabData\s*=\s*(\[.*\])\s*;?\s*', raw.decode('utf-8-sig'), re.S)
    if not match:
        raise ValueError('SCHEMA_CHANGED')
    data = json.loads(match[1])
    channels = {}
    stocks = {}
    for market in ('SSE Southbound', 'SZSE Southbound'):
        entries = [x for x in data if x['market'] == market]
        if len(entries) != 1:
            raise ValueError('MISSING_OR_DUPLICATE_CHANNEL')
        item = entries[0]
        if item['date'] != target or item['tradingDay'] != 1:
            raise ValueError('WRONG_DATE_OR_NONTRADING')
        tables = {c['table']['classname']: c['table'] for c in item['content']}
        summary = tables['tradingTable']
        labels = summary['schema'][0]
        if len(set(labels)) != len(labels) or len(labels) != len(summary['tr']):
            raise ValueError('SCHEMA_CHANGED')
        values = dict(zip(labels, [number(r['td'][0][0]) for r in summary['tr']]))
        buy, sell, total = [values[k] for k in ('Buy Turnover', 'Sell Turnover', 'Total Turnover')]
        if min(buy, sell, total) < 0 or abs(buy + sell - total) > Decimal('.01'):
            raise ValueError('TURNOVER_CONFLICT')
        channels[market] = {'buy_hkd': str(buy * 1000000), 'sell_hkd': str(sell * 1000000),
                            'net_buy_hkd': str((buy - sell) * 1000000)}
        top = tables['top10Table']
        if top['schema'] != [['Rank', 'Stock Code', 'Stock Name', 'Buy Turnover', 'Sell Turnover', 'Total Turnover']]:
            raise ValueError('SCHEMA_CHANGED')
        seen = set()
        for row in top['tr']:
            rank, code, name, b, s, t = row['td'][0]
            if not re.fullmatch(r'\d{5}', code) or code in seen:
                raise ValueError('INVALID_OR_DUPLICATE_CODE')
            seen.add(code)
            b, s, t = map(number, (b, s, t))
            if min(b, s, t) < 0 or b + s != t:
                raise ValueError('STOCK_TURNOVER_CONFLICT')
            stocks.setdefault(code, {})[market] = {'name': name, 'net_buy_hkd': str(b-s)}
    combined = {}
    for code, evidence in stocks.items():
        complete = len(evidence) == 2
        combined[code] = {'channels': evidence, 'channel_coverage': len(evidence),
                          'status': 'VERIFIED' if complete else 'PARTIAL_CHANNEL_COVERAGE',
                          'net_buy_hkd': str(sum(number(v['net_buy_hkd']) for v in evidence.values())) if complete else None}
    return {'as_of_date': target, 'evidence_class': 'VERIFIED_CAPITAL_FLOW',
            'scope': 'Southbound turnover including eligible ETFs; not equity-only',
            'channels': channels, 'net_buy_hkd': str(sum(number(v['net_buy_hkd']) for v in channels.values())),
            'top10_union': combined, 'unlisted_stock_status': 'NOT_DISCLOSED_IN_TOP10_NOT_ZERO'}


def parse_hkma(raw, target):
    data = json.loads(raw)
    if data['header']['err_code'] != '0000':
        raise ValueError('SOURCE_ERROR')
    rows = [r for r in data['result']['records'] if r['end_of_date'] == target]
    if len(rows) != 1:
        raise ValueError('TARGET_DATE_NOT_AVAILABLE')
    row = rows[0]
    fields = {'hibor_overnight': 'percent', 'hibor_fixing_1m': 'percent', 'closing_balance': 'HKD million'}
    return {'as_of_date': target, 'evidence_class': 'LIQUIDITY_PROXY_NOT_EQUITY_FLOW',
            'fields': {k: {'value': str(number(row[k])), 'unit': unit} for k, unit in fields.items()}}


class FixedOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https' or urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            raise ValueError('REDIRECT_OUTSIDE_SOURCE')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    opener = build_opener(FixedOriginRedirect())
    for attempt in range(2):
        try:
            with opener.open(Request(url, headers={'User-Agent': 'DSA-Public-Evidence/1.0'}), timeout=12) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('RESPONSE_TOO_LARGE')
            return raw, attempt + 1
        except HTTPError as exc:
            if attempt or exc.code not in (429, 500, 502, 503, 504):
                raise
        except (URLError, TimeoutError):
            if attempt:
                raise
        time.sleep(.25)


def collect_one(name, url, parser, target, cutoff, folder):
    start = time.monotonic()
    result = {'source': name, 'source_locator': url, 'published_at': None,
              'data_time_precision': 'date', 'status': 'FETCH_FAILED', 'eligible_at_cutoff': False}
    try:
        raw, attempts = fetch(url)
        observed = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(raw).hexdigest()
        filename = name + '-' + digest + '.raw'
        with (folder / filename).open('xb') as handle:
            handle.write(raw)
        result.update(retrieved_at=observed, first_observed_at=observed, sha256=digest,
                      artifact=filename, bytes=len(raw), attempts=attempts, status='VALIDATION_FAILED')
        parsed = parser(raw, target)
        result.update(data=parsed, status='VERIFIED', eligible_at_cutoff=clock(observed) <= clock(cutoff),
                      cutoff_reason='OBSERVED_BY_CUTOFF' if clock(observed) <= clock(cutoff) else 'FIRST_OBSERVED_AFTER_CUTOFF')
    except Exception as exc:
        result['reason'] = 'HTTP_' + str(exc.code) if isinstance(exc, HTTPError) else type(exc).__name__
        if isinstance(exc, ValueError):
            result['reason'] = str(exc) if re.fullmatch('[A-Z_]+', str(exc)) else 'SCHEMA_CHANGED'
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    return result


def run(target, cutoff, folder):
    date.fromisoformat(target)
    decision = clock(cutoff)
    if target > decision.date().isoformat():
        raise ValueError('TARGET_AFTER_CUTOFF')
    folder = Path(folder)
    receipt = folder / 'receipt.json'
    if receipt.exists():
        existing = json.loads(receipt.read_text())
        if (existing['target_date'], existing['cutoff'], existing['version']) != (target, cutoff, VERSION):
            raise ValueError('CACHE_CONTRACT_MISMATCH')
        for source in existing['sources']:
            if 'artifact' in source:
                if hashlib.sha256((folder/source['artifact']).read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('CACHE_HASH_MISMATCH')
        return existing
    folder.mkdir(parents=True, exist_ok=False)
    sources = [
        ('hkex', 'https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_' + target.replace('-', '') + 'e.js', parse_hkex),
        ('hkma', 'https://api.hkma.gov.hk/public/market-data-and-statistics/daily-monetary-statistics/daily-figures-interbank-liquidity?pagesize=30', parse_hkma),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(collect_one, name, url, parser, target, cutoff, folder) for name, url, parser in sources]
        results = [f.result() for f in futures]
    report = {'run_id': folder.name, 'version': VERSION, 'target_date': target, 'cutoff': cutoff,
              'completed_at': datetime.now(timezone.utc).isoformat(), 'source_denominator': len(sources),
              'verified_sources': sum(r['status'] == 'VERIFIED' for r in results),
              'cutoff_eligible_sources': sum(r['eligible_at_cutoff'] for r in results), 'sources': results,
              'unresolved': {'foreign_investor_net_flow': 'NOT_PUBLICLY_IDENTIFIABLE',
                             'local_institution_net_flow': 'NOT_PUBLICLY_IDENTIFIABLE',
                             'etf_creation_redemption': 'ISSUER_SERIES_ADAPTER_PENDING'},
              'model_calls': 0, 'paid_data_calls': 0, 'api_cost_cny': 0, 'trade_gate_changed': False}
    with receipt.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-date', required=True, help='Explicit verified HK session date; no calendar inference')
    parser.add_argument('--cutoff', required=True, help='ISO timestamp with timezone')
    parser.add_argument('--output', required=True, help='New run directory; identical run reuses verified cached bytes')
    args = parser.parse_args()
    result = run(args.target_date, args.cutoff, args.output)
    # Logs contain health counts only; raw content remains in the evidence directory.
    print(json.dumps({k: result[k] for k in ('run_id', 'verified_sources', 'source_denominator', 'cutoff_eligible_sources', 'model_calls')}))


if __name__ == '__main__':
    main()
