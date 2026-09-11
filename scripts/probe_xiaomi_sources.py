"""Read-only Xiaomi source evidence. Never imports or calls an LLM."""
import argparse
import importlib.metadata
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def save(name, value):
    out = Path('probe')
    out.mkdir(exist_ok=True)
    payload = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'result': value}
    (out / f'{name}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(name, json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['quote', 'history', 'news', 'native'])
    args = parser.parse_args()
    if args.mode != 'native':
        from openbb import obb
        print('openbb_version', importlib.metadata.version('openbb'), flush=True)
        try:
            if args.mode == 'quote':
                data = obb.equity.price.quote('1810.HK', provider='yfinance')
            elif args.mode == 'history':
                end = datetime.now(timezone.utc).date() + timedelta(days=1)
                data = obb.equity.price.historical(
                    '1810.HK', provider='yfinance', start_date=str(end-timedelta(days=100)),
                    end_date=str(end), adjustment='splits_and_dividends')
            else:
                data = obb.news.company('1810.HK', provider='yfinance')
            save('openbb_' + args.mode, data.to_dataframe().reset_index().to_dict('records'))
        except Exception as exc:
            save('openbb_' + args.mode, {'error': str(exc)})
        return
    import requests
    from src.services.intelligence_service import IntelligenceService
    service = IntelligenceService()
    save('native_news', {'refresh': service.refresh_auto_sources(force=True),
                         'hk': service.list_items(scope_type='market', market='hk', published_days=3, page_size=100),
                         'global': service.list_items(scope_type='market', market='global', published_days=3, page_size=100)})
    urls = {
        'tencent_history': 'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk01810,day,,,100,qfq',
        'tencent_quote': 'https://qt.gtimg.cn/q=r_hk01810',
        'sina_quote': 'https://hq.sinajs.cn/list=rt_hk01810',
        'xiaomi_ir': 'https://ir.mi.com/news-events/announcements',
        'sina_news': 'https://stock.finance.sina.com.cn/hkstock/go.php/CompanyNews/page/1/code/01810.html',
    }
    for name, url in urls.items():
        try:
            response = requests.get(url, timeout=20, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'})
            response.raise_for_status()
            if name in ('tencent_quote', 'sina_quote', 'sina_news'):
                response.encoding = 'gb18030'
            try:
                body = response.json()
            except ValueError:
                body = response.text
            save(name, {'url': url, 'status': response.status_code, 'body': body})
        except Exception as exc:
            save(name, {'url': url, 'error': str(exc)})


if __name__ == '__main__':
    main()
