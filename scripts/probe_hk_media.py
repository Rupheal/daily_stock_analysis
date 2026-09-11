"""Bounded public media discovery probe; no credentials or LLM calls."""
import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def main():
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
        name,url,params=job
        result={'name':name,'requested_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
        try:
            r=requests.get(url,params=params,timeout=(8,18),headers={'User-Agent':'Mozilla/5.0'})
            result.update(status=r.status_code,url=r.url)
            if name.startswith('sina'): r.encoding=r.apparent_encoding
            (out/(name+'.txt')).write_text(r.text,encoding='utf-8')
            soup=BeautifulSoup(r.text,'html.parser')
            result['text_sample']=soup.get_text(' ',strip=True)[:16000] if name not in ('eastmoney','eastmoney_price') else r.text[:20000]
            result['scripts']=[x.get('src') for x in soup.find_all('script',src=True)][-8:]
        except Exception as exc: result['error']=str(exc)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(fetch,jobs))
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    for result in results: print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
