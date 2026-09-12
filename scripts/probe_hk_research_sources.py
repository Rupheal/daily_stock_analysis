"""Read-only official universe source probe; no model or trading operations."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    root = Path('probe/universe')
    root.mkdir(parents=True, exist_ok=True)
    params = {'sqlId': 'COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L', 'isPagination': 'true',
        'pageHelp.pageSize': '1000', 'pageHelp.pageNo': '1', 'pageHelp.beginPage': '1',
        'pageHelp.cacheSize': '1', 'pageHelp.endPage': '1', 'keyword': ''}
    urls = {
        'sse-list.json': 'https://query.sse.com.cn/commonQuery.do?'+urlencode(params),
        'szse-list.json': 'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1',
        'szse-list.xlsx': 'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1',
        'hkex-securities.xlsx': 'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx',
    }
    def fetch(pair):
        name, url = pair
        result = {'file': name, 'url': url, 'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer':
                'https://www.sse.com.cn/services/hkexsc/disclo/eligible/' if name.startswith('sse-') else
                'https://www.szse.cn/szhk/hkbussiness/underlylist/index.html' if name.startswith('szse-') else
                'https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en'})
            with urlopen(request, timeout=20) as response:
                data = response.read(5_000_001)
            if len(data) > 5_000_000:
                raise ValueError('Source exceeds bounded size')
            (root/name).write_bytes(data)
            result.update(status='received', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if name.endswith('.json'):
                payload = json.loads(data)
                print('OFFICIAL_SOURCE_JSON', json.dumps({'file': name, 'payload': payload}, ensure_ascii=False), flush=True)
            else:
                import io
                from openpyxl import load_workbook
                workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
                sheet = workbook.active
                sheet.reset_dimensions()  # HKEX's declared dimensions can truncate records.
                rows = list(sheet.values)
                result['rows'] = len(rows)
                result['header'] = rows[:4]
                if name == 'szse-list.xlsx':
                    print('OFFICIAL_SOURCE_TABLE', json.dumps({'file': name, 'rows': rows}, ensure_ascii=False, default=str), flush=True)
                else:
                    candidates = json.loads(Path('docs/dsa-u-universe.json').read_text())
                    codes = {c['code'] for c in candidates['members']}
                    result['u_reference_rows'] = [row for row in rows if str(row[0]).zfill(5) in codes]
        except Exception as exc:
            result.update(status='failed', error=type(exc).__name__+': '+str(exc))
        result['completed_at'] = datetime.now(timezone.utc).isoformat()
        return result
    results = list(ThreadPoolExecutor(max_workers=3).map(fetch, urls.items()))
    audit = {'model_http_requests': 0, 'complete_universe_verified': False, 'sources': results,
        'note': 'Source transport/parse probe only. Effective dates, security types, membership and union still require validation.'}
    (root/'source-probe.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
    print('UNIVERSE_SOURCE_PROBE', json.dumps(audit, ensure_ascii=False, default=str), flush=True)


if __name__ == '__main__':
    main()
