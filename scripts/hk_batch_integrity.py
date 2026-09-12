"""External input checks for native O/U research; never rewrite either input."""
from datetime import date
from decimal import Decimal
import json
import sqlite3


FIELDS = ('open', 'high', 'low', 'close', 'volume')


def canonical(code):
    return 'HK' + str(code).upper().removeprefix('HK').removesuffix('.HK').zfill(5)


def native_rows(database, code):
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute('SELECT * FROM stock_daily WHERE code=? COLLATE NOCASE ORDER BY date', (canonical(code),)).fetchall()
    return [dict(r, date=str(r['date'])[:10]) for r in rows]


def validate_rows(rows, target):
    if len(rows) < 21 or rows[-1]['date'] != target:
        raise ValueError('missing_latest_session_or_21_bar_history')
    previous = None
    for row in rows:
        date.fromisoformat(row['date'])
        if previous and row['date'] <= previous:
            raise ValueError('duplicate_or_unsorted_session')
        previous = row['date']
        v = {k: Decimal(str(row[k])) for k in FIELDS}
        if not all(x.is_finite() for x in v.values()):
            raise ValueError('non_finite_daily_value')
        if not 0 < v['low'] <= min(v['open'], v['close']) <= max(v['open'], v['close']) <= v['high'] or v['volume'] < 0:
            raise ValueError('invalid_daily_geometry')
    return rows[-21:]


def tencent_rows(payload, code):
    item = payload['data'][canonical(code).lower()]
    key = 'qfqday' if item.get('qfqday') else 'day'
    rows = []
    for r in item.get(key, []):
        if len(r) < 6:
            raise ValueError('incomplete_independent_bar')
        rows.append(dict(date=str(r[0]), open=r[1], close=r[2], high=r[3], low=r[4], volume=r[5]))
    return rows, key


def compare_history(native, independent, target):
    recent = validate_rows(native, target)
    independent = validate_rows(independent, target)
    lookup = {r['date']: r for r in independent}
    if any('Tencent' in str(r.get('data_source', '')) for r in recent):
        raise ValueError('comparison_provider_not_independent')
    mismatches = []
    for row in recent:
        other = lookup.get(row['date'])
        if other is None:
            raise ValueError('independent_session_missing')
        for field in FIELDS:
            tolerance = Decimal('.5') if field == 'volume' else Decimal('.005')
            if abs(Decimal(str(row[field])) - Decimal(str(other[field]))) > tolerance:
                mismatches.append({'date': row['date'], 'field': field, 'native': row[field], 'independent': other[field]})
    return {'passed': not mismatches, 'overlap': len(recent), 'mismatches': mismatches,
            'scope': 'last 21 observed daily OHLCV bars; adjusted provider values, not complete corporate-action certification'}


def validate_native_context(context, accepted):
    today = context.get('today') or {}
    latest = accepted[-1]
    if str(today.get('date'))[:10] != latest['date']:
        raise ValueError('native_context_session_changed')
    for field in FIELDS:
        tolerance = Decimal('.5') if field == 'volume' else Decimal('.005')
        if abs(Decimal(str(today[field])) - Decimal(str(latest[field]))) > tolerance:
            raise ValueError('native_context_value_changed:' + field)
    for n in (5, 10, 20):
        expected = sum(Decimal(str(r['close'])) for r in accepted[-n:]) / n
        if abs(Decimal(str(today['ma' + str(n)])) - expected) > Decimal('.015'):
            raise ValueError('native_mean_not_reproducible:ma' + str(n))
    yesterday = context.get('yesterday') or {}
    if str(yesterday.get('date'))[:10] != accepted[-2]['date']:
        raise ValueError('native_previous_session_changed')
    return True
