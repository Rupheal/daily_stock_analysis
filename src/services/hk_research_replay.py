"""Source-level mechanism replay and immutable observation records.

No scoring weights, trades, causal claims, or synthetic past predictions are created.
Archive data retrieved now is not proof of availability at a historical decision time.
"""
import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def parse_json_assignment(text):
    """Decode data only; never eval remote JavaScript."""
    text = text.strip().rstrip(";")
    if text.startswith("tabData ="):
        return json.loads(text.split("=", 1)[1])
    if text.startswith("jsonpCallback(") and text.endswith(")"):
        return json.loads(text[len("jsonpCallback("):-1])
    return json.loads(text)


def decimal_value(value):
    number = Decimal(str(value).replace(",", ""))
    if not number.is_finite():
        raise ValueError("Non-finite source value")
    return number


def parse_hkex_southbound(text, expected_date):
    markets = {}
    for market in parse_json_assignment(text):
        if market["market"] not in ("SSE Southbound", "SZSE Southbound"):
            continue
        if market["date"] != expected_date or market["tradingDay"] != 1:
            raise ValueError("Wrong date or non-trading source")
        if market["market"] in markets:
            raise ValueError("Duplicate Southbound channel")
        table = next(c["table"] for c in market["content"] if c["table"]["classname"] == "tradingTable")
        labels, rows = table["schema"][0], table["tr"]
        if len(labels) != len(rows):
            raise ValueError("Source schema length mismatch")
        values = {label: decimal_value(row["td"][0][0]) for label, row in zip(labels, rows)}
        buy, sell, total = [values[x] for x in ("Buy Turnover", "Sell Turnover", "Total Turnover")]
        if min(buy, sell) < 0 or abs(buy + sell - total) > Decimal("0.02"):
            raise ValueError("Buy/sell reconciliation failed")
        markets[market["market"]] = {"buy_hkd_million": str(buy), "sell_hkd_million": str(sell), "net_buy_hkd_million": str(buy-sell)}
    if set(markets) != {"SSE Southbound", "SZSE Southbound"}:
        raise ValueError("Both Southbound channels required for a combined figure")
    net = sum(Decimal(m["net_buy_hkd_million"]) for m in markets.values())
    return {"date": expected_date, "channels": markets, "net_buy_hkd_million": str(net),
            "evidence_type": "verified_channel_net_buy_turnover", "includes_etfs": True,
            "identity_scope": "Southbound channel; not institutional or ultimate investor identity",
            "source_publication_time": None, "historical_pit_verified": False}


def parse_sse_southbound(text, expected_date):
    rows = parse_json_assignment(text)["result"]
    if len(rows) != 1 or rows[0]["TRADE_DATE"] != expected_date:
        raise ValueError("Historical query returned wrong/missing date")
    values = rows[0]
    buy, sell, total = [decimal_value(values[k]) for k in ("BUY_AMOUNT", "SELL_AMOUNT", "TOTAL_AMOUNT")]
    if min(buy, sell) < 0 or abs(buy+sell-total) > Decimal("0.02"):
        raise ValueError("Rounded SSE buy/sell reconciliation failed")
    return {"date": expected_date, "channel": "SSE Southbound only", "unit": "HKD 100 million",
            "buy": str(buy), "sell": str(sell), "net_buy": str(buy-sell), "combined_southbound": None,
            "includes_etfs": True, "historical_pit_verified": False}


def parse_fred_csv(raw, series, start="2025-04-01", end="2026-09-11"):
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames != ["observation_date", series]:
        raise ValueError("FRED series/header mismatch")
    observations = []
    seen = set()
    for row in reader:
        day = row["observation_date"]
        datetime.strptime(day, "%Y-%m-%d")
        if day in seen:
            raise ValueError("Duplicate observation date")
        seen.add(day)
        if not start <= day <= end:
            continue
        value = row[series]
        observations.append({"date": day, "value": None if value in ("", ".") else str(decimal_value(value))})
    if not observations:
        raise ValueError("No observations in requested range")
    if [r["date"] for r in observations] != sorted(r["date"] for r in observations):
        raise ValueError("Unsorted observations")
    return observations


def admits_point_in_time(evidence, decision_at):
    """No inferred midnight publication; archive retrieval is not a vintage record."""
    if not evidence.get("historical_pit_verified") or not evidence.get("available_at"):
        return False
    decision, available = datetime.fromisoformat(decision_at), datetime.fromisoformat(evidence["available_at"])
    if not decision.tzinfo or not available.tzinfo:
        raise ValueError("Timezone-aware availability required")
    return available <= decision


def freeze_observation(directory, record):
    """Content-addressed original; exclusive creation prevents silent overwrite."""
    record = dict(record)
    if not record.get("rules_sha256") or not record.get("input_sha256") or not record.get("available_at"):
        raise ValueError("Rules/input hashes and actual report availability are required")
    at = datetime.fromisoformat(record["available_at"])
    if not at.tzinfo or at > datetime.now(timezone.utc):
        raise ValueError("Invalid report availability")
    record_hash = canonical_hash(record)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (record_hash + ".json")
    with target.open("x") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def append_observation_outcome(original, horizon, sessions, observed_at, reference_close):
    """Evaluate observation returns on actual supplied complete HK sessions.

    This is a reference-price observation, not simulated fills or strategy P&L.
    Unmatured outcomes stay absent; never fabricate dates or prices to fill them.
    """
    original = Path(original)
    record = json.loads(original.read_text())
    if original.stem != canonical_hash(record):
        raise ValueError("Frozen observation was modified")
    if horizon not in (1, 3, 5, 10, 20):
        raise ValueError("Unsupported observation horizon")
    at, observed = datetime.fromisoformat(record["available_at"]), datetime.fromisoformat(observed_at)
    if not observed.tzinfo or observed > datetime.now(timezone.utc):
        raise ValueError("Outcome observation must be timezone-aware and not future")
    future = []
    seen = set()
    previous = None
    for session in sessions:
        opening = datetime.fromisoformat(session["open_at"])
        closing = datetime.fromisoformat(session["close_at"])
        if not opening.tzinfo or not closing.tzinfo or closing <= opening:
            raise ValueError("Invalid actual session times")
        if session["date"] in seen or (previous and opening <= previous):
            raise ValueError("Duplicate or unordered actual HK sessions")
        seen.add(session["date"])
        previous = opening
        if opening > at and closing <= observed:
            if not session.get("calendar_verified") or not session.get("price_verified"):
                raise ValueError("Unverified session/price cannot mature an outcome")
            future.append(session)
    if len(future) < horizon:
        return {"status": "waiting", "horizon": horizon, "complete_verified_sessions": len(future)}
    if [s.get("sequence_from_report") for s in future] != list(range(1, len(future)+1)):
        raise ValueError("Actual HK calendar must be complete from the first session after report")
    if decimal_value(reference_close) != decimal_value(record["reference_close"]):
        raise ValueError("Reference close must match the frozen observation")
    if decimal_value(reference_close) <= 0:
        raise ValueError("Reference close must be positive")
    end = future[horizon-1]
    if decimal_value(end["close"]) <= 0:
        raise ValueError("End close must be positive")
    result = {"observation_sha256": original.stem, "horizon": horizon, "end_session": end["date"],
              "observed_at": observed_at, "reference_close": str(reference_close), "end_close": str(end["close"]),
              "reference_return_pct": str((decimal_value(end["close"])/decimal_value(reference_close)-1)*100),
              "kind": "reference_price_observation_only", "strategy_return": None, "fees": None,
              "session_input_sha256": canonical_hash(sessions)}
    target = original.with_name(original.stem + f".h{horizon}.json")
    with target.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return result
