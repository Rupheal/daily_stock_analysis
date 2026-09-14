"""Reuse Run009 receipts without changing past snapshots or claiming current signals."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import openpyxl
from dsa_u_execution_audit import yahoo_rows, valid


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipts', type=Path, required=True)
    p.add_argument('--universe', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run-id', required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    source_receipts = json.loads((a.sources / 'source-probe.json').read_text())['sources']
    for r in source_receipts:
        if r.get('status') == 'received' and r.get('sha256'):
            assert sha(a.sources / r['file']) == r['sha256'], 'SOURCE_RECEIPT_HASH_MISMATCH'
    sse = json.loads((a.sources / 'sse-list.json').read_text())['result']
    sessions = {r['UPDATE_DATE'] for r in sse}
    assert len(sessions) == 1
    session = next(iter(sessions))
    buy = {r['SECURITY_CODE'] for r in sse if r['SECURITY_TYPE'] == '股票' and r['TRADE_FLAG'] == '1'}
    meta = json.loads((a.sources / 'szse-list.json').read_text())[0]['metadata']
    assert meta['subname'] == session
    wb = openpyxl.load_workbook(a.sources / 'szse-list.xlsx', read_only=True, data_only=True)
    ws = wb.active; ws.reset_dimensions()
    sz = list(ws.values)
    assert sz[0] == ('证券代码', '中文简称', '英文简称')
    assert len(sz) - 1 == meta['recordcount']
    sz_names = {str(r[0]).zfill(5): r[1] for r in sz[1:]}
    wb = openpyxl.load_workbook(a.sources / 'hkex-securities.xlsx', read_only=True, data_only=True)
    ws = wb.active; ws.reset_dimensions(); hk = list(ws.values)
    assert hk[1][0] == 'Updated as at ' + datetime.fromisoformat(session).strftime('%d/%m/%Y')
    hkmap = {str(r[0]).zfill(5): r for r in hk[3:] if r[0] is not None}
    members = json.loads(a.universe.read_text())['members']
    assert len(members) == len({m['code'] for m in members}) == 45
    result = []
    for m in members:
        code = m['code']; folder = a.receipts / code
        old = json.loads((folder / 'audit.json').read_text())
        raw = folder / 'yahoo.json'
        receipt = next(r for r in old['source_receipts'] if 'finance.yahoo' in r['source'])
        match = sha(raw) == receipt['sha256']
        data = json.loads(raw.read_text())['chart']['result'][0]
        rows, ym = yahoo_rows(raw.read_bytes(), session)
        h = hkmap.get(code)
        row = {'code': code, 'user_alias': m['user_alias'], 'source_session': session,
               'sse_buyable_on_source_session': code in buy,
               'szse_listed_on_source_session': code in sz_names,
               'union_positive_eligibility': code in buy,
               'union_status': 'SSE_BUY_FLAG_VERIFIED' if code in buy else 'SZSE_BUY_FLAG_NEEDS_REVIEW' if code in sz_names else 'ABSENT_FROM_BOTH_SNAPSHOTS',
               'official_identity': {'name': h[1], 'isin': h[5], 'board_lot': h[4], 'currency': h[16]} if h else None,
               'yahoo_symbol_matches_code': ym.get('symbol') == code.lstrip('0').zfill(4) + '.HK',
               'cached_price_bytes_verified': match, 'price_source': receipt,
               'source_price_time': old.get('yahoo_price_time'),
               'bar_timestamp': data['timestamp'][-1],
               'source_market_session_end': ym.get('currentTradingPeriod', {}).get('regular', {}).get('end'),
               'latest_ohlcv_geometry': valid(rows.get(session, {})),
               'adjustment_status': 'QUOTE_ARRAY_OBSERVED_CORPORATE_ACTION_BASIS_NOT_VERIFIED',
               'volume_unit_status': 'PROVIDER_RAW_UNITS_NOT_INDEPENDENTLY_VERIFIED',
               'suspension_status': 'OFFICIAL_SUSPENSION_EVIDENCE_MISSING',
               'news_status': 'CURRENT_COMPANY_ANNOUNCEMENT_COVERAGE_MISSING',
               'capital_tide_status': 'CURRENT_CAPITAL_EVIDENCE_MISSING',
               'availability': 'retrieval_time_retained_not_backfilled_into_past_snapshots',
               'preparation_complete': False, 'execution_qualified': False, 'action': 'WAIT'}
        row['missing'] = ['SUSPENSION', 'CORPORATE_ACTION_PRICE_BASIS', 'VOLUME_UNIT', 'NEWS', 'CAPITAL', 'TRADE_PLAN_AND_COSTS']
        if not row['union_positive_eligibility']:
            row['missing'].append('BUY_ELIGIBILITY')
        result.append(row)
    report = {'run_id': a.run_id, 'scope': 'cached_2026-09-14_preparation_not_current_signal',
              'created_at': datetime.now(timezone.utc).isoformat(), 'denominator': 45,
              'members_reviewed': len(result), 'preparation_complete': sum(r['preparation_complete'] for r in result),
              'identity_lot_currency_records': sum(r['official_identity'] is not None for r in result),
              'positive_union_eligibility': sum(r['union_positive_eligibility'] for r in result),
              'price_receipts_verified': sum(r['cached_price_bytes_verified'] for r in result),
              'missing_counts': dict(Counter(x for r in result for x in r['missing'])),
              'model_requests': 0, 'new_market_data_requests': 0, 'source_receipts': source_receipts,
              'universe_sha256': sha(a.universe), 'rows': result}
    (a.output / 'U45_PREPARATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('rows', 'source_receipts')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
