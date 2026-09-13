"""Parse HKEX Main Board Daily Quotations for a bounded PIT cohort.

Input files are official dated quotation sheets saved as dYYMMDDe.htm. The parser
uses only the QUOTATIONS section and retains page hashes plus the exact two-line
quotation snippets used for each security.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

# HKEX may prefix a quotation row with '*' (for example MINIMAX-W on 2026-08-06).
# The marker is metadata, not part of the security code; all price/volume fields
# remain subject to the same strict two-line parsing and required-field checks.
LINE1 = re.compile(r"^\s*\*?\s*(?P<code>\d{1,5})\s+(?P<name>.+?)\s+(?P<cur>HKD|RMB|USD)\s+(?P<prev>[0-9.]+|-)\s+(?P<ask>[0-9.]+|-)\s+(?P<high>[0-9.]+|-)\s+(?P<shares>[0-9,]+|-)\s*$")
LINE2 = re.compile(r"^\s*(?P<close>[0-9.]+|-)\s+(?P<bid>[0-9.]+|-)\s+(?P<low>[0-9.]+|-)\s+(?P<turnover>[0-9,]+|-)\s*$")
TAG = re.compile(r"<[^>]+>")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(text, integer=False):
    if text == "-": return None
    t=text.replace(",", "")
    return int(t) if integer else float(t)


def text_from_html(path: Path) -> str:
    raw=path.read_bytes().decode("latin1", "ignore")
    raw=html.unescape(raw)
    return TAG.sub("", raw).replace("\r", "")


def parse_page(path: Path, expected):
    text=text_from_html(path)
    marker="PRV.CLO./"
    start=text.find(marker)
    if start < 0: raise ValueError(f"quotation_header_missing:{path.name}")
    stop=text.find("SALES RECORD", start)
    section=text[start: stop if stop >= 0 else len(text)]
    lines=section.splitlines()
    found={}
    for i,line in enumerate(lines[:-1]):
        m=LINE1.match(line)
        if not m: continue
        code=m.group("code").zfill(5)
        if code not in expected: continue
        m2=LINE2.match(lines[i+1])
        if not m2: raise ValueError(f"continuation_line_missing:{path.name}:{code}")
        name=" ".join(m.group("name").split())
        expected_name=expected[code].upper()
        if expected_name not in name.upper() and name.upper() not in expected_name:
            raise ValueError(f"name_mismatch:{path.name}:{code}:{name}")
        if code in found: raise ValueError(f"duplicate_quote:{path.name}:{code}")
        found[code]={
            "code":code,"name":name,"currency":m.group("cur"),
            "previous_close":num(m.group("prev")),"closing":num(m2.group("close")),
            "ask":num(m.group("ask")),"bid":num(m2.group("bid")),
            "high":num(m.group("high")),"low":num(m2.group("low")),
            "shares_traded":num(m.group("shares"),True),"turnover":num(m2.group("turnover"),True),
            "source_page_sha256":sha(path),
            "source_snippet":line.rstrip()+"\n"+lines[i+1].rstrip()
        }
    missing=sorted(set(expected)-set(found))
    if missing: raise ValueError(f"missing_cohort_quotes:{path.name}:{','.join(missing)}")
    return found


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--cohort",type=Path,required=True)
    p.add_argument("--dates",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    cohort=json.loads(a.cohort.read_text())
    expected={m["code"]:m["english_name"] for m in cohort["members"]}
    dates=[x.strip() for x in a.dates.read_text().splitlines() if x.strip()]
    if len(dates)!=cohort["price_sessions_expected"]: raise ValueError("session_count_mismatch")
    series={c:[] for c in expected}; page_hashes={}
    for d in dates:
        compact=d.replace("-","")[2:]
        path=a.input_dir/f"d{compact}e.htm"
        if not path.exists(): raise ValueError(f"missing_page:{path.name}")
        rows=parse_page(path,expected)
        page_hashes[d]=sha(path)
        for c,row in rows.items():
            row["date"]=d
            series[c].append(row)
    for c,rows in series.items():
        if len(rows)!=len(dates): raise ValueError(f"bar_count_mismatch:{c}")
        if any(r["closing"] is None or r["high"] is None or r["low"] is None or r["shares_traded"] is None for r in rows):
            raise ValueError(f"required_market_field_missing:{c}")
    out={
      "schema_version":1,"cohort_id":cohort["cohort_id"],"decision_at":cohort["decision_at"],
      "source":"HKEX Main Board Daily Quotations","session_count":len(dates),"sessions":dates,
      "page_sha256":page_hashes,"series":series
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print("HKEX_PIT_QUOTES_OK",json.dumps({"sessions":len(dates),"members":len(series),"bars":sum(map(len,series.values()))}))

if __name__=="__main__": main()
