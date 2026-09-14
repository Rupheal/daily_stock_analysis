"""Offline incremental audit of recovered U45 preparation, never a signal engine."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile
from dsa_drive_bundle import verify_bundle


def aware(value):
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return t


def audit_rows(prep):
    rows = prep['rows']
    codes = [r.get('code') if isinstance(r, dict) else None for r in rows]
    if prep.get('denominator') != 45 or len(rows) != 45 or len(set(codes)) != 45 or None in codes:
        raise ValueError('U45_DENOMINATOR_OR_IDENTITY_CONTRACT')
    refs = [s['u_reference_rows'] for s in prep['source_receipts'] if 'u_reference_rows' in s]
    reference = {r[0]: r for r in refs[0]} if len(refs) == 1 else {}
    output = []
    for r in rows:
        code = r['code']; issues = []
        identity = False; clocks = False; lot = None
        try:
            h = reference[code]; i = r['official_identity']
            identity = i == dict(name=h[1], isin=h[5], board_lot=h[4], currency=h[16])
            lot = int(i['board_lot'].replace(',', ''))
            if not identity or lot <= 0 or i['currency'] != 'HKD':
                issues.append('IDENTITY_OR_LOT_CONFLICT')
        except (KeyError, TypeError, ValueError, IndexError):
            issues.append('IDENTITY_OR_LOT_UNREADABLE')
        try:
            retrieval = aware(r['price_source']['retrieved_at'])
            price_time = aware(r['source_price_time'])
            bar = datetime.fromtimestamp(r['bar_timestamp'], timezone.utc)
            end = datetime.fromtimestamp(r['source_market_session_end'], timezone.utc)
            clocks = bar <= price_time <= end <= retrieval
            if not clocks: issues.append('SOURCE_CLOCK_ORDER_CONFLICT')
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            issues.append('SOURCE_CLOCK_UNREADABLE')
        output.append({
            'code': code, 'identity_receipt_consistent': identity,
            'board_lot_normalized': lot, 'clock_order_consistent': clocks,
            'preparation_source_session': r.get('source_session'),
            'new_raw_yahoo_hash_verification': False,
            'raw_yahoo_reason': 'only prior receipt recovered; original Yahoo bytes absent in this audit',
            'buy_eligibility_inherited': r.get('union_positive_eligibility') is True,
            'issues': issues, 'inherited_missing': r.get('missing', []),
            'preparation_complete': False, 'execution_qualified': False, 'action': 'WAIT'})
    return output


def audit_media(raw):
    verify_bundle(raw)
    result = []; source_count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        final = json.loads(z.read('MEDIA_PREPARATION_FINAL.json'))
        by_link = {}
        for source in final['sources']:
            b = z.read(source['channel'] + '.xml')
            if len(b) != source['bytes'] or hashlib.sha256(b).hexdigest() != source['sha256']:
                raise ValueError('MEDIA_RECEIPT_HASH_MISMATCH')
            retrieved = aware(source['retrieved_at'])
            source_count += 1
            for item in ET.fromstring(b).findall('.//item'):
                link = item.findtext('link')
                try:
                    published = parsedate_to_datetime(item.findtext('pubDate'))
                    if published.tzinfo is None: raise ValueError('TIMEZONE_REQUIRED')
                    clock = {'publisher_time': published.isoformat(),
                             'retrieved_at': retrieved.isoformat(),
                             'conservative_available_at': max(published, retrieved).isoformat(),
                             'source_sha256': source['sha256']}
                except (TypeError, ValueError, OverflowError):
                    clock = {'error': 'PUBLISHER_TIME_UNVERIFIED'}
                by_link.setdefault(link, []).append(clock)
        for r in final['rows']:
            leads = []
            for lead in r['leads']:
                matches = by_link.get(lead['url'], [])
                leads.append({'url': lead['url'], 'inherited_naive_time': lead['published_at'],
                              'original_rss_clock_receipts': matches,
                              'official_announcement_accepted': False})
            result.append({'code': r['code'], 'leads': leads,
                           'official_announcement_accepted': False})
    return {'raw_source_hashes_verified': source_count, 'rows': result,
            'scope': 'recovered RSS publication clocks only, no company announcement acceptance'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preparation', required=True, type=Path)
    p.add_argument('--media-bundle', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    b = a.preparation.read_bytes(); media = a.media_bundle.read_bytes()
    prep = json.loads(b); rows = audit_rows(prep); m = audit_media(media)
    if {r['code'] for r in m['rows']} != {r['code'] for r in rows} or len(m['rows']) != 45:
        raise ValueError('MEDIA_U45_IDENTITY_CONTRACT')
    summary = {'denominator': 45, 'members_rechecked': len(rows),
               'identity_receipt_consistent': sum(r['identity_receipt_consistent'] for r in rows),
               'clock_order_consistent': sum(r['clock_order_consistent'] for r in rows),
               'row_failures_isolated': sum(bool(r['issues']) for r in rows),
               'inherited_buy_eligible': sum(r['buy_eligibility_inherited'] for r in rows),
               'raw_media_hashes_verified': m['raw_source_hashes_verified'],
               'members_with_media_leads': sum(bool(r['leads']) for r in m['rows']),
               'inherited_missing_counts': dict(Counter(x for r in rows for x in r['inherited_missing'])),
               'preparation_complete': 0, 'execution_qualified': 0,
               'model_requests': 0, 'market_data_requests': 0}
    report = {'run_id': 'TRI-DSA-EXEC-20260914-014', 'parent_run_id': prep['run_id'],
              'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'offline recovered-receipt audit; not a refreshed market snapshot',
              'preparation_sha256': hashlib.sha256(b).hexdigest(),
              'media_bundle_sha256': hashlib.sha256(media).hexdigest(),
              'summary': summary, 'rows': rows, 'media': m}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
