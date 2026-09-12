"""Admit a small reviewed set of primary disclosures, never aggregator estimates.

This is a versioned evidence checkpoint, not a general financial PDF parser.
Every changed source hash requires a new review. All amounts retain their
original periods, unit and accounting basis; legacy fundamentals stay isolated.
"""
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

REGISTRY = Path(__file__).resolve().parents[2] / 'docs/xiaomi-primary-evidence.json'


def _decimal(value):
    result = Decimal(str(value).replace(',', '').replace('−', '-'))
    if not result.is_finite():
        raise ValueError('Non-finite disclosed value')
    return result


def verify_pages(document, pages):
    """Compare reviewed rows and column order with extracted original pages."""
    first = pages['1']
    if 'XIAOMI CORPORATION' not in first.upper():
        raise ValueError('Issuer mismatch')
    fields = []
    for table in document['tables']:
        lines = pages[str(table['page'])].splitlines()
        rows = [line for line in lines if table['row_label'] in line]
        if not rows:
            raise ValueError('Reviewed row missing: ' + table['row_label'])
        # A note number may occur between the label and the first numeric column.
        tokens = re.findall(r'[-−]?\d[\d,]*(?:\.\d+)?', rows[0].split(table['row_label'], 1)[1])
        count = len(table['values'])
        actual = [_decimal(v) for v in tokens[-count:]]
        expected = [_decimal(v) for v in table['values']]
        if actual != expected or len(table['columns']) != count:
            raise ValueError('Source row or column mismatch: ' + table['metric'])
        for column, value in zip(table['columns'], expected):
            if column is None:  # Displayed percentage, not an amount column.
                continue
            start, end = date.fromisoformat(column['period_start']), date.fromisoformat(column['period_end'])
            if start > end or end > date.fromisoformat(document['published_date']):
                raise ValueError('Invalid disclosure period')
            fields.append(dict(column, id=f"{table['metric']}:{start}:{end}",
                metric=table['metric'], label_zh=table['label_zh'], value=str(value),
                currency=table['currency'], unit=table['unit'], unit_scale=table['unit_scale'],
                amount_cny=str(value * table['unit_scale']), basis=table['basis'],
                source_id=document['id'], source_url=document['url'], page=table['page'],
                publication_date=document['published_date'], publication_precision='day',
                source_sha256=document['sha256'], estimated=False))
    for statement in document.get('statements', []):
        text = ' '.join(pages[str(statement['page'])].split())
        if statement['anchor'] not in text:
            raise ValueError('Reviewed disclosure statement missing')
    buyback = document.get('buyback')
    if buyback:
        page = pages[str(buyback['page'])]
        trade_date = date.fromisoformat(buyback['trade_date']).strftime('%d %B %Y')
        rows = [line for line in page.splitlines() if trade_date in line and 'On the Exchange' in line]
        if 'Section II' not in page or len(rows) != 1:
            raise ValueError('Daily buyback row missing')
        numbers = re.findall(r'\d[\d,]*(?:\.\d+)?', rows[0].split(trade_date, 1)[1])
        expected = [buyback['shares'], buyback['highest_price_hkd'], buyback['lowest_price_hkd'], buyback['consideration_hkd']]
        if [_decimal(n) for n in numbers] != [_decimal(n) for n in expected]:
            raise ValueError('Daily buyback differs from reviewed source')
        total = _decimal(buyback['consideration_hkd'])
        if not _decimal(buyback['lowest_price_hkd'])*buyback['shares'] <= total <= _decimal(buyback['highest_price_hkd'])*buyback['shares']:
            raise ValueError('Buyback consideration outside disclosed price range')
    return fields


def verify_pdf(document, raw):
    from pypdf import PdfReader
    if hashlib.sha256(raw).hexdigest() != document['sha256']:
        raise ValueError('Primary source hash changed; new review required')
    reader = PdfReader(io.BytesIO(raw))
    page_numbers = {1} | {t['page'] for t in document['tables']} | {s['page'] for s in document.get('statements', [])}
    if document.get('buyback'):
        page_numbers.add(document['buyback']['page'])
    pages = {str(n): reader.pages[n-1].extract_text(extraction_mode='layout') for n in sorted(page_numbers)}
    return verify_pages(document, pages), pages


def derived_metrics(fields):
    """Only matched periods/bases; never estimate missing profit or TTM values."""
    by_key = {(f['metric'], f['period_start'], f['period_end']): f for f in fields}
    results = []
    for f in fields:
        end = date.fromisoformat(f['period_end'])
        if end.year != 2026:
            continue
        start = date.fromisoformat(f['period_start'])
        prior = by_key.get((f['metric'], str(start.replace(year=start.year-1)), str(end.replace(year=end.year-1))))
        if prior and prior['basis'] == f['basis'] and _decimal(prior['amount_cny']) > 0:
            results.append({'id': f['id']+':yoy_pct', 'metric': f['metric']+'_yoy_pct',
                'value': str((_decimal(f['amount_cny'])/_decimal(prior['amount_cny'])-1)*100),
                'unit': 'percent', 'formula': '(current/prior_same_period-1)*100',
                'input_ids': [f['id'], prior['id']], 'period_start': f['period_start'], 'period_end': f['period_end']})
        if f['metric'] == 'gross_profit':
            revenue = by_key.get(('revenue', f['period_start'], f['period_end']))
            if revenue and _decimal(revenue['amount_cny']) > 0:
                results.append({'id': f['id']+':margin_pct', 'metric': 'gross_margin_pct',
                    'value': str(_decimal(f['amount_cny'])/_decimal(revenue['amount_cny'])*100),
                    'unit': 'percent', 'formula': 'gross_profit/revenue*100',
                    'input_ids': [f['id'], revenue['id']], 'period_start': f['period_start'], 'period_end': f['period_end']})
    return results


def collect_primary_evidence(root, registry_path=REGISTRY):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    registry = json.loads(Path(registry_path).read_text())
    if registry['schema_version'] != 1 or registry['symbol'] != 'HK01810':
        raise ValueError('Unsupported primary evidence registry')
    now = datetime.now(timezone.utc)
    result = {'schema_version': 1, 'symbol': 'HK01810', 'checked_at': now.isoformat(),
        'registry_sha256': hashlib.sha256(Path(registry_path).read_bytes()).hexdigest(),
        'documents': [], 'financial_fields': [], 'derived_metrics': [], 'buybacks': [],
        'statements': [], 'diagnostics': [], 'coverage_complete': False,
        'limitations': ['Pinned reviewed disclosures only; later or unlisted filings remain outside coverage.',
            'Day precision is insufficient for intraday historical availability; no same-day PIT inference.',
            'ROE, TTM valuation, forecasts and unreviewed financial fields remain unavailable.',
            'Issuer statements do not resolve subsequent regulatory or third-party allegations.']}
    for document in registry['documents']:
        try:
            if date.fromisoformat(document['published_date']) > now.date():
                raise ValueError('Future publication date')
            path = root/document['file']
            if path.name != document['file']:
                raise ValueError('Unsafe evidence filename')
            receipt = {'mode': 'cached_bytes_checked', 'retrieved_at': None}
            if not path.exists():
                request = Request(document['url'], headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(request, timeout=20) as response:
                    raw = response.read(5_000_001)
                    receipt = {'mode': 'downloaded', 'retrieved_at': now.isoformat(),
                        'http_status': response.status, 'final_url': response.url}
                if len(raw) > 5_000_000:
                    raise ValueError('Primary PDF exceeds bounded download size')
                path.write_bytes(raw)
            raw = path.read_bytes()
            fields, pages = verify_pdf(document, raw)
            result['documents'].append({k: document[k] for k in ('id', 'title', 'url', 'sha256', 'published_date', 'publication_precision') } | {
                'verified_pages': sorted(map(int, pages)), 'verified_scope': 'reviewed fields', 'receipt': receipt})
            result['financial_fields'].extend(fields)
            if document.get('buyback'):
                result['buybacks'].append(dict(document['buyback'], id=document['id'], source_url=document['url'], source_sha256=document['sha256']))
            result['statements'].extend(dict(s, source_url=document['url'], source_sha256=document['sha256']) for s in document.get('statements', []))
            (root/(document['id']+'-pages.json')).write_text(json.dumps(pages, ensure_ascii=False, indent=2))
        except Exception as exc:
            result['diagnostics'].append({'source_id': document['id'], 'url': document['url'], 'status': 'failed', 'error': type(exc).__name__+': '+str(exc)})
    result['derived_metrics'] = derived_metrics(result['financial_fields'])
    result['coverage'] = {'verified': len(result['documents']), 'required': len(registry['documents'])}
    result['passed'] = not result['diagnostics'] and bool(result['financial_fields'])
    (root/'verified-primary-evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def render_primary_sections(evidence):
    """The report displays financial numbers directly, without model rewriting."""
    coverage = evidence['coverage']
    sections = [{'title': '公司原件补证：财务期间与单位', 'paragraphs': [
        f"本次核对 {coverage['verified']}/{coverage['required']} 份指定原件；只验证列出的字段，不能代表所有公告均已覆盖。",
        '原件为公司未经审计的中期披露，已获审阅；季度、半年及非IFRS调整后口径分别保留。金额按原件列示，未估算缺失字段。'],
        'headers': ['项目', '起止期间', '原披露值', '单位', '会计口径', '原件页码'],
        'rows': [[f['label_zh'], f['period_start']+' 至 '+f['period_end'], f['value'],
            '人民币千元' if f['unit'] == 'thousand' else '人民币百万元', f['basis'], str(f['page'])]
            for f in evidence['financial_fields']],
        'links': [{'label': d['title']+' · '+d['published_date'], 'url': d['url']} for d in evidence['documents'] if d['id'].startswith('xiaomi-results-')]}]
    sections.append({'title': '公司原件补证：每日回购', 'paragraphs': [
        '下表来自翌日披露报表第6页Section II A；没有把授权累计回购或待注销历史表重复算作当日回购。',
        '回购属于已披露公司行为，不能证明股价将上涨，也不能消除其他持续风险。'],
        'headers': ['交易日', '回购股数', '最高／港元', '最低／港元', '支付总额／港元'],
        'rows': [[b['trade_date'], str(b['shares']), b['highest_price_hkd'], b['lowest_price_hkd'], b['consideration_hkd']] for b in evidence['buybacks']],
        'links': [{'label': b['trade_date']+' 回购原件，第6页', 'url': b['source_url']+'#page=6'} for b in evidence['buybacks']]})
    if evidence.get('diagnostics'):
        sections.append({'title': '补证失败清单', 'paragraphs': [json.dumps(d, ensure_ascii=False) for d in evidence['diagnostics']]})
    return sections
