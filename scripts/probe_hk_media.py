"""Bounded public media transport probe; no model credentials or LLM calls."""
import concurrent.futures
import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup


def probe_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network-label', default='current-egress',
                        help='Operator label only; not verified IP geolocation')
    parser.add_argument('--repeats', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--proxy-env', help='Name of an environment variable containing a trusted HTTPS proxy URL')
    args = parser.parse_args(argv)
    proxy = None
    if args.proxy_env:
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', args.proxy_env):
            parser.error('Invalid proxy environment variable name')
        proxy = os.environ.get(args.proxy_env, '')
        parsed = urlsplit(proxy)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment:
            parser.error('A trusted HTTPS proxy endpoint must be configured in the selected environment variable')
    return args, proxy


def main(argv=None):
    args, proxy = probe_options(argv)
    eastmoney = {'uid':'','keyword':'小米集团','type':['cmsArticleWebOld'], 'client':'web',
                 'clientType':'web','clientVersion':'curr', 'param':{'cmsArticleWebOld':{
                 'searchScope':'default','sort':'time','pageIndex':1,'pageSize':30,'preTag':'','postTag':''}}}
    jobs = [
        ('eastmoney','https://search-api-web.eastmoney.com/search/jsonp',{'cb':'callback','param':json.dumps(eastmoney,ensure_ascii=False)}),
        ('sina','https://search.sina.com.cn/',{'q':'小米集团','c':'news','sort':'time'}),
        ('sina_stock','https://stock.finance.sina.com.cn/hkstock/quotes/01810.html',None),
        ('futu','https://www.futunn.com/stock/01810-HK/news',None),
        ('cls','https://www.cls.cn/searchPage',{'keyword':'小米'}),
        ('eastmoney_price','https://push2his.eastmoney.com/api/qt/stock/kline/get',{'secid':'116.01810','klt':'101','fqt':'1','beg':'20260601','end':'20260912','fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'}),
    ]
    out=Path('probe/media'); out.mkdir(parents=True,exist_ok=True)
    def fetch(job):
        name,url,params,attempt=job
        result={'name':name,'requested_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),
                'attempt':attempt, 'network_label':args.network_label,
                'transport':'explicit_https_proxy' if proxy else 'runner_environment',
                'egress_location_verified':False}
        started = time.monotonic()
        try:
            options = {'proxies':{'https':proxy}} if proxy else {}
            with requests.get(url,params=params,timeout=(8,18),headers={'User-Agent':'Mozilla/5.0'},
                              stream=True, **options) as r:
                result.update(status=r.status_code,url=r.url,response_headers_ms=round(r.elapsed.total_seconds()*1000))
                chunks, size = [], 0
                for chunk in r.iter_content(8192):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ValueError('Probe response exceeds size limit')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                result['decoded_response_bytes'] = len(raw)
                try: body = raw.decode('utf-8')
                except UnicodeDecodeError: body = raw.decode('gb18030')
                suffix = '' if args.repeats == 1 else f'-{attempt}'
                (out/(name+suffix+'.txt')).write_text(body,encoding='utf-8')
                soup=BeautifulSoup(body,'html.parser')
                result['text_sample']=soup.get_text(' ',strip=True)[:16000] if name not in ('eastmoney','eastmoney_price') else body[:20000]
                result['scripts']=[x.get('src') for x in soup.find_all('script',src=True)][-8:]
        except Exception as exc:
            # Proxy exceptions can contain credentials. Keep only the exception class.
            result['error_type']=type(exc).__name__
        result['total_ms'] = round((time.monotonic()-started)*1000)
        return result
    jobs = [(name,url,params,attempt) for attempt in range(1,args.repeats+1) for name,url,params in jobs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(fetch,jobs))
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    for result in results: print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
