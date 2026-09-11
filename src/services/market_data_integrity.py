"""Deterministic validation for complete daily-bar analysis."""
import math
from datetime import date


class MarketDataIntegrityError(ValueError):
    """Input cannot support a dated trading report."""


def validate_daily_context(context, expected_date=None):
    today = context.get("today") or {}
    actual = str(today.get("date") or context.get("date") or "")[:10]
    errors = []
    try:
        date.fromisoformat(actual)
    except ValueError:
        errors.append("invalid daily bar date")
    if not actual or (expected_date and actual != str(expected_date)[:10]):
        errors.append(f"daily_bar_date={actual or 'missing'}, expected={expected_date}")
    if (today.get("is_estimated") or today.get("estimated_fields")
            or today.get("is_partial_bar")):
        errors.append("estimated daily bar cannot be used as a completed session")
    values = {}
    for key in ("open", "high", "low", "close"):
        try:
            value = float(today.get(key))
            if not math.isfinite(value) or value <= 0:
                raise ValueError()
            values[key] = value
        except (ValueError, TypeError):
            errors.append(f"invalid {key}")
    if len(values) == 4:
        if not (values["low"] <= min(values["open"], values["close"])
                <= max(values["open"], values["close"]) <= values["high"]):
            errors.append("OHLC bounds inconsistent")
    previous = context.get("yesterday") or {}
    if previous and str(previous.get("date", ""))[:10] >= actual:
        errors.append("previous session must precede daily bar")
    if previous and "close" in values:
        try:
            prev = float(previous["close"])
            if not math.isfinite(prev) or prev <= 0:
                raise ValueError()
            calculated = (values["close"] / prev - 1) * 100
            if today.get("pct_chg") is not None:
                pct = float(today["pct_chg"])
                if not math.isfinite(pct) or abs(pct - calculated) > 0.05:
                    errors.append("change percentage disagrees with previous close")
        except (ValueError, TypeError, KeyError):
            errors.append("invalid previous close/change percentage")
    trend = context.get("trend_analysis") or {}
    for period in (5, 10):
        ma, bias = today.get(f"ma{period}"), trend.get(f"bias_ma{period}")
        if ma is not None and bias is not None and "close" in values:
            try:
                ma, bias = float(ma), float(bias)
                if not math.isfinite(ma) or ma <= 0 or not math.isfinite(bias):
                    raise ValueError()
                if abs((values["close"] / ma - 1) * 100 - bias) > 0.05:
                    errors.append(f"MA{period} bias disagrees with daily close")
            except (ValueError, TypeError):
                errors.append(f"invalid MA{period}/bias")
    if errors:
        raise MarketDataIntegrityError("数据验收未通过 / data validation failed: " + "; ".join(errors))
