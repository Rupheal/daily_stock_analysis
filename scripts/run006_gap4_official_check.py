"""Run006 diagnostic for the four provider-only history gaps.

Consumes archived HKEX Daily Quotations pages from the prior official arbitration
artifact and freshly fetches Tencent qfq. No model calls and no production policy change.
"""
from __future__ import annotations
import argparse, hashlib, html, json, re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CODES=["HK00501","HK00638","HK00668","HK00699"]
SESSIONS=["2026-08-14","2026-08-17","2026-08-18","2026-08-19","2026-08-20","2026-08-21","2026-08-24","2026-08-25","2026-08-26","2026-08-27","2026-08-28","2026-08-31","2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11"]
LINE1=re.compile(r"^\s*\*?\s*(?P<code>\d{1,5})\s+(?P<name>.+?)\s+(?P<cur>HKD|RMB|USD)\s+(?P<prev>[0-9.]+|-)\s+(?P<ask>[0-9.]+|-)\s+(?P<high>[0-9.]+|-)\s+(?P<shares>[0-9,]+|-)\s*$")
LINE2=re.compile(r"^\s*(?P<close>[0-9.]+|-)\s+(?P<bid>[0-9.]+|-)\s+(?P<low>[0-9.]+|-)\s+(?P<turnover>[0-9,]+|-)\s*$")
TAG=re.compile(r"<[^>]+>")
def hk(x): return "HK"+str(x).upper().removeprefix("HK").zfill(5)
def n(x): return None if x=="-" else float(x.replace(",",""))
def parse(b):
    text=html.unescape(b.decode("latin1","ignore")); text=TAG.sub("",text).replace("\r",""); s=text.find("PRV.CLO./"); e=text.find("SALES RECORD",s); lines=text[s:e if e>=0 else len(text)].splitlines(); out={}
    for i,line in enumerate(lines[:-1]):
        m=LINE1.match(line)
        if not m: continue
        m2=LINE2.match(lines[i+1])
        if not m2: continue
        c=hk(m.group("code")); out[c]={"high":n(m.group("high")),"low":n(m2.group("low")),"close":n(m2.group("close")),"volume":n(m.group("shares"))}
    return out
def tqfq(code):
    sym=code.lower(); url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":f"{sym},day,,,180,qfq"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=30) as r: b=r.read(2_000_000)
    p=json.loads(b); item=(p.get("data") or {}).get(sym) or {}; rows=item.get("qfqday") or item.get("day") or []
    return hashlib.sha256(b).hexdigest(),{str(z[0]):{"open":float(z[1]),"close":float(z[2]),"high":float(z[3]),"low":float(z[4]),"volume":float(z[5])} for z in rows if isinstance(z,list) and len(z)>=6 and str(z[0]) in SESSIONS}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--hkex-pages",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    official={c:{} for c in CODES}
    for d in SESSIONS:
        p=parse((a.hkex_pages/f"hkex-{d}.htm").read_bytes())
        for c in CODES:
            if c in p: official[c][d]=p[c]
    rows=[]
    for c in CODES:
        h,t=tqfq(c); diffs=[]
        for d in SESSIONS:
            o=official[c].get(d); q=t.get(d)
            rec={"date":d,"official":o,"tencent_qfq":q}
            if o and q:
                rec["exact_hlc"] = all(abs(float(q[f])-float(o[f]))<=1e-9 for f in ("high","low","close"))
                rec["exact_volume"] = abs(float(q["volume"])-float(o["volume"]))<=1e-9
            diffs.append(rec)
        rows.append({"code":c,"official_count":len(official[c]),"tencent_count":len(t),"all_21_exact_hlc":len(official[c])==21 and len(t)==21 and all(r.get("exact_hlc") for r in diffs),"all_21_exact_volume":len(official[c])==21 and len(t)==21 and all(r.get("exact_volume") for r in diffs),"tencent_payload_sha256":h,"days":diffs})
    out={"schema_version":1,"run_id":"TRI-DSA-DAT-20260914-006-R4-GAP4-OFFICIAL","track_denominator":4,"model_http_requests":0,"paid_data_used":False,"rows":rows}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)); print("RUN006_GAP4",json.dumps([{"code":r["code"],"official":r["official_count"],"tencent":r["tencent_count"],"hlc":r["all_21_exact_hlc"],"volume":r["all_21_exact_volume"]} for r in rows]))
if __name__=="__main__": main()
