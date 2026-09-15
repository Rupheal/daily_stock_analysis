"""Model-free HK daily-volume cross-provider calibration.

Uses only public Tencent HK qfq K-lines and Yahoo chart data. Emits aggregate
statistics and per-symbol coverage/status only; never prints raw price/volume
payloads, credentials, prompts, or model content.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import statistics
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0"}
HK = ZoneInfo("Asia/Hong_Kong")

# Deliberately liquid, diversified members already present in the frozen U45.
SAMPLE = [
    ("00700", "TENCENT"),
    ("03690", "MEITUAN-W"),
    ("09988", "BABA-W"),
    ("01211", "BYD COMPANY"),
    ("01810", "XIAOMI-W"),
    ("00981", "SMIC"),
    ("03968", "CM BANK"),
    ("02899", "ZIJIN MINING"),
    ("02318", "PING AN"),
    ("00939", "CCB"),
    ("00883", "CNOOC"),
    ("00388", "HKEX"),
    ("00941", "CHINA MOBILE"),
    ("02020", "ANTA SPORTS"),
]


def get_json(url, params=None, attempts=3):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    last = None
    for i in range(attempts):
        try:
            req = Request(url, headers=UA)
            with urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as exc:  # public-data transport only; details are not emitted
            last = exc
            if i + 1 < attempts:
                time.sleep(0.5 * (i + 1))
    raise RuntimeError(type(last).__name__ if last else "PUBLIC_FETCH_FAILED")


def tencent(code):
    symbol = "hk" + code
    payload = get_json(
        "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
        {"param": f"{symbol},day,,,180,qfq"},
    )
    item = (payload.get("data") or {}).get(symbol) or {}
    rows = item.get("qfqday") or item.get("day") or []
    out = {}
    malformed = 0
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            malformed += 1
            continue
        try:
            out[str(row[0])] = float(row[5])
        except Exception:
            malformed += 1
    return out, malformed


def yahoo(code):
    ticker = str(int(code)) + ".HK"
    payload = get_json(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
        {"range": "6mo", "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"},
    )
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    volumes = quote.get("volume") or []
    out = {}
    malformed = 0
    for ts, volume in zip(timestamps, volumes):
        if volume is None:
            malformed += 1
            continue
        try:
            day = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(HK).date().isoformat()
            out[day] = float(volume)
        except Exception:
            malformed += 1
    split_days = set()
    for event in (result.get("events") or {}).get("splits", {}).values():
        ts = event.get("date")
        if ts is None:
            continue
        try:
            split_days.add(datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(HK).date().isoformat())
        except Exception:
            pass
    return out, split_days, malformed


def percentile(values, q):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def main():
    aggregate = {
        "stocks_requested": len(SAMPLE),
        "stocks_comparable": 0,
        "provider_unavailable": 0,
        "provider_stale": 0,
        "malformed_stocks": 0,
        "overlap_sessions": 0,
        "valid_nonzero_sessions": 0,
        "zero_volume_sessions": 0,
        "corporate_action_sessions": 0,
        "exact_match_sessions": 0,
        "mismatch_sessions": 0,
        "latest_session_mismatch": 0,
        "historical_session_mismatch": 0,
        "near_100x_sessions": 0,
        "near_0_01x_sessions": 0,
    }
    deviations = []
    ratios = []
    rows = []

    for code, name in SAMPLE:
        row = {"code": code, "name": name, "status": "pending"}
        try:
            tq, tm = tencent(code)
            yh, split_days, ym = yahoo(code)
        except Exception as exc:
            aggregate["provider_unavailable"] += 1
            row.update(status="provider_unavailable", error_type=type(exc).__name__)
            rows.append(row)
            continue

        if not tq or not yh:
            aggregate["provider_unavailable"] += 1
            row.update(status="provider_unavailable", tencent_rows=len(tq), yahoo_rows=len(yh))
            rows.append(row)
            continue

        overlap = sorted(set(tq) & set(yh))
        if not overlap:
            aggregate["malformed_stocks"] += 1
            row.update(status="no_overlap", tencent_last=max(tq), yahoo_last=max(yh), malformed_rows=tm + ym)
            rows.append(row)
            continue

        aggregate["stocks_comparable"] += 1
        aggregate["overlap_sessions"] += len(overlap)
        if max(tq) != max(yh):
            aggregate["provider_stale"] += 1

        latest = overlap[-1]
        exact = mismatch = latest_mismatch = historical_mismatch = corporate = zeros = valid = 0
        for day in overlap:
            tv, yv = tq[day], yh[day]
            if day in split_days:
                corporate += 1
                aggregate["corporate_action_sessions"] += 1
                continue
            if not math.isfinite(tv) or not math.isfinite(yv):
                continue
            if tv == 0 or yv == 0:
                zeros += 1
                aggregate["zero_volume_sessions"] += 1
                continue
            valid += 1
            aggregate["valid_nonzero_sessions"] += 1
            ratio = tv / yv
            dev = abs(ratio - 1.0)
            ratios.append(ratio)
            deviations.append(dev)
            if tv == yv:
                exact += 1
                aggregate["exact_match_sessions"] += 1
            else:
                mismatch += 1
                aggregate["mismatch_sessions"] += 1
                if day == latest:
                    latest_mismatch += 1
                    aggregate["latest_session_mismatch"] += 1
                else:
                    historical_mismatch += 1
                    aggregate["historical_session_mismatch"] += 1
            if 90 <= ratio <= 110:
                aggregate["near_100x_sessions"] += 1
            if 0.009 <= ratio <= 0.011:
                aggregate["near_0_01x_sessions"] += 1

        if tm + ym:
            aggregate["malformed_stocks"] += 1
        row.update(
            status="comparable",
            tencent_rows=len(tq),
            yahoo_rows=len(yh),
            overlap_sessions=len(overlap),
            tencent_last=max(tq),
            yahoo_last=max(yh),
            same_provider_last=(max(tq) == max(yh)),
            valid_nonzero_sessions=valid,
            exact_match_sessions=exact,
            mismatch_sessions=mismatch,
            latest_session_mismatch=latest_mismatch,
            historical_session_mismatch=historical_mismatch,
            corporate_action_sessions=corporate,
            zero_volume_sessions=zeros,
            malformed_rows=tm + ym,
        )
        rows.append(row)

    comparable = aggregate["valid_nonzero_sessions"]
    exact_rate = (aggregate["exact_match_sessions"] / comparable) if comparable else None
    report = {
        "schema": "dsa-hk-volume-cross-provider-calibration-v1",
        "model_http_requests": 0,
        "sample_basis": "14 liquid diversified members from frozen U45; split sessions isolated, unavailable/stale/malformed retained in denominators",
        "tencent_semantics": "HK qfq endpoint row[5] as returned; repository currently interprets as shares",
        "yahoo_semantics": "Yahoo chart quote.volume; split events requested and isolated",
        "aggregate": aggregate,
        "exact_match_rate": round(exact_rate, 8) if exact_rate is not None else None,
        "ratio_median_tencent_over_yahoo": round(statistics.median(ratios), 8) if ratios else None,
        "absolute_relative_deviation_p95": round(percentile(deviations, 0.95), 8) if deviations else None,
        "absolute_relative_deviation_p99": round(percentile(deviations, 0.99), 8) if deviations else None,
        "absolute_relative_deviation_max": round(max(deviations), 8) if deviations else None,
        "per_symbol_coverage": rows,
        "raw_payload_disclosed": False,
        "raw_prices_or_volumes_disclosed": False,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
