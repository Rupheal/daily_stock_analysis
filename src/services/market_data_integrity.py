"""Deterministic validation for complete daily-bar analysis."""
import math
from datetime import date
import re


def company_news_matches(item, code, name):
    """Require dated, linked company evidence; market tags alone are insufficient."""
    if not item.get('published_at') or not str(item.get('url', '')).startswith(('https://', 'http://')):
        return False
    if item.get('scope_type') == 'symbol':
        canonical = lambda value: str(value).upper().removeprefix('HK').removesuffix('.HK').lstrip('0')
        if canonical(item.get('scope_value', '')) == canonical(code):
            return True
    text = str(item.get('title', '')) + ' ' + str(item.get('summary', ''))
    digits = str(code).upper().removeprefix('HK').removesuffix('.HK')
    company = re.sub(r'[-－](?:W|Ｗ|SW|B)$', '', str(name), flags=re.I).strip()
    return bool((company and company.lower() in text.lower())
                or (digits.isdigit() and re.search(r'(?<!\d)' + re.escape(digits) + r'(?!\d)', text)))


class MarketDataIntegrityError(ValueError):
    """Input cannot support a dated trading report."""


def enforce_daily_report(result, context):
    """Reject unsafe HK outputs before history/signals/notifications are published."""
    try:
        audit = audit_daily_report(result.to_dict(), context)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        audit = {'passed': False, 'findings': [{'code': 'unverifiable_report', 'reason': str(exc)}]}
    result.report_quality_audit = audit
    if not audit['passed']:
        result.success = False
        result.error_message = '报告复核未通过：' + ', '.join(x['code'] for x in audit['findings'])
        # Failed results may still be serialized by callers. Remove execution fields.
        result.dashboard = None
        result.operation_advice = '数据或报告待复核，暂停交易结论'
        result.decision_type = 'hold'
        result.action = None
        result.action_label = None
    return audit


def audit_daily_report(result, context):
    """Audit report claims against daily evidence without another model call.

    This is an acceptance gate, not a comprehensive natural-language verifier.
    Findings require withholding the generated execution plan.
    """
    today = context['today']
    dashboard = result.get('dashboard') or {}
    perspective = dashboard.get('data_perspective') or {}
    findings = []
    position = perspective.get('price_position') or {}
    for key, expected in [('current_price', today['close'])] + [(key, today[key]) for key in ('ma5','ma10','ma20') if key in today]:
        actual = position.get(key)
        if actual is not None and abs(float(actual)-float(expected)) > 0.015:
            findings.append({'code':'price_indicator_mismatch', 'field':key, 'actual':actual, 'expected':expected})
    ratio = (perspective.get('volume_analysis') or {}).get('volume_ratio')
    if isinstance(ratio, (int,float)) and today.get('volume_ratio') is not None:
        if abs(ratio - today['volume_ratio']) > 0.015:
            findings.append({'code':'volume_ratio_semantics', 'reported':ratio,
                             'expected_previous_five_session_ratio':today['volume_ratio'],
                             'previous_session_ratio':context.get('volume_change_ratio')})
    body = abs(today['close']-today['open'])
    span = today['high']-today['low']
    upper = today['high']-max(today['close'],today['open'])
    lower = min(today['close'],today['open'])-today['low']
    pattern = result.get('pattern_analysis') or ''
    if span > 0 and '实体较小' in pattern and body/span > 0.5:
        findings.append({'code':'candle_body_claim', 'body_fraction':body/span})
    if '上下影线均较长' in pattern and upper < body and lower < body:
        findings.append({'code':'candle_shadow_claim', 'body':body, 'upper_shadow':upper, 'lower_shadow':lower})
    plan = dashboard.get('battle_plan') or {}
    stop_text = str((plan.get('sniper_points') or {}).get('stop_loss') or '')
    risk_text = str((plan.get('position_strategy') or {}).get('risk_control') or '')
    stop = re.search(r'(\d+(?:\.\d+)?)\s*元', stop_text)
    cap = re.search(r'(\d+(?:\.\d+)?)%以内', risk_text)
    if stop and cap:
        distance = (1-float(stop.group(1))/today['close'])*100
        if distance > float(cap.group(1)) + 0.01:
            findings.append({'code':'stop_distance_requires_entry_basis',
                             'distance_from_last_close_pct':distance, 'claimed_cap_pct':float(cap.group(1)),
                             'note':'No single agreed entry price; the stated cap is not established by this stop.'})
    return {'passed':not findings, 'execution_plan_enabled':not findings, 'findings':findings,
            'scope':'Selected numerical/semantic checks only; manual review remains necessary.'}


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
