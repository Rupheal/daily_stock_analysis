"""Direct public-data volume-unit probe; no model, secret, or raw payload output."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import statistics
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0"}


def get_json(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    req = Request(url, headers=UA)
    with urlopen(req, timeout=20) as r:
        return json.load(r)


def tencent():
    p = get_json("https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
                 {"param": "hk01810,day,,,180,qfq"})
    item = (p.get("data") or {}).get("hk01810") or {}
    rows = item.get("qfqday") or item.get("day") or []
    return {str(r[0]): float(r[5]) for r in rows if isinstance(r, list) and len(r) >= 6}


def yahoo():
    p = get_json("https://query2.finance.yahoo.com/v8/finance/chart/1810.HK",
                 {"range": "6mo", "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"})
    result = ((p.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    volumes = quote.get("volume") or []
    hk = ZoneInfo("Asia/Hong_Kong")
    out = {}
    for ts, volume in zip(timestamps, volumes):
        if volume is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(hk).date().isoformat()
        out[day] = float(volume)
    events = result.get("events") or {}
    split_count = len(events.get("splits") or {})
    return out, split_count


def main():
    tq = tencent()
    yh, split_count = yahoo()
    overlap = sorted(set(tq) & set(yh))
    ratios = [tq[d] / yh[d] for d in overlap if yh[d] != 0]
    exact = [d for d in overlap if tq[d] == yh[d]]
    report = {
        "schema": "dsa-xiaomi-direct-volume-unit-v1",
        "model_http_requests": 0,
        "tencent_semantics_under_test": "HK row[5] as returned by qfq endpoint",
        "yahoo_semantics_under_test": "chart quote.volume",
        "tencent_rows": len(tq),
        "yahoo_rows": len(yh),
        "overlap_rows": len(overlap),
        "tencent_last": max(tq) if tq else None,
        "yahoo_last": max(yh) if yh else None,
        "exact_match_rows": len(exact),
        "mismatch_rows": len(overlap) - len(exact),
        "yahoo_split_events_in_range": split_count,
        "ratio_median_tencent_over_yahoo": round(statistics.median(ratios), 6) if ratios else None,
        "ratio_min": round(min(ratios), 6) if ratios else None,
        "ratio_max": round(max(ratios), 6) if ratios else None,
        "ratio_latest": round(tq[overlap[-1]] / yh[overlap[-1]], 6) if overlap and yh[overlap[-1]] else None,
        "ratio_near_1_rows": sum(abs(x - 1) <= 0.000001 for x in ratios),
        "ratio_near_100_rows": sum(abs(x - 100) <= 0.0001 for x in ratios),
        "ratio_near_0_01_rows": sum(abs(x - 0.01) <= 0.000001 for x in ratios),
        "raw_payload_disclosed": False,
        "values_disclosed": False,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
