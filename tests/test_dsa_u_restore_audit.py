"""U45 isolation tests use synthetic receipts, not model scores or live prices."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsa_u_restore_audit import audit_rows


def fixture():
    rows = []; refs = []
    for n in range(45):
        c = str(n + 1).zfill(5)
        refs.append([c, 'SYNTHETIC', '', '', '1,000', 'SYNTHETIC-ISIN'] + [None] * 10 + ['HKD'])
        rows.append({'code': c, 'official_identity': {'name': 'SYNTHETIC', 'isin': 'SYNTHETIC-ISIN', 'board_lot': '1,000', 'currency': 'HKD'},
                     'bar_timestamp': 0, 'source_market_session_end': 60,
                     'source_price_time': '1970-01-01T00:00:30+00:00',
                     'price_source': {'retrieved_at': '1970-01-01T00:02:00+00:00'}})
    return {'denominator': 45, 'rows': rows, 'source_receipts': [{'u_reference_rows': refs}]}


def test_all_45_retained_no_signal():
    out = audit_rows(fixture())
    assert len(out) == 45
    assert all(r['clock_order_consistent'] and r['identity_receipt_consistent'] for r in out)
    assert all(r['board_lot_normalized'] == 1000 and not r['execution_qualified'] for r in out)


def test_bad_member_isolated_without_shrinking_denominator():
    p = fixture(); p['rows'][7]['official_identity'] = None
    p['rows'][7]['price_source'] = {}
    out = audit_rows(p)
    assert len(out) == 45 and bool(out[7]['issues'])
    assert sum(not r['issues'] for r in out) == 44


def test_naive_time_rejected_not_assumed_timezone():
    p = fixture(); p['rows'][1]['source_price_time'] = '1970-01-01T00:00:30'
    out = audit_rows(p)
    assert not out[1]['clock_order_consistent'] and len(out) == 45


def test_duplicate_member_never_changes_universe():
    p = fixture(); p['rows'][1]['code'] = p['rows'][0]['code']
    with pytest.raises(ValueError, match='DENOMINATOR'): audit_rows(p)


def test_price_before_publication_does_not_become_entry():
    p = fixture(); p['rows'][1]['price_source']['retrieved_at'] = '1969-12-31T00:00:00+00:00'
    out = audit_rows(p)
    assert not out[1]['clock_order_consistent']
    assert out[1]['action'] == 'WAIT' and not out[1]['execution_qualified']
