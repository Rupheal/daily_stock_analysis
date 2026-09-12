"""Deterministic validation for complete daily-bar analysis."""
import math
from datetime import date
import re
from copy import deepcopy


def withhold_unverified_hk_financials(context, market):
    """Keep raw snapshots elsewhere; HK financial periods/units are not audited yet."""
    if market != 'hk' or not isinstance(context, dict):
        return context
    cleaned = deepcopy(context)
    reason = '财报原始披露、期间、币种及单位未核验；本轮不得引用财务数值'
    coverage = dict(cleaned.get('coverage') or {})
    for key in ('earnings', 'growth', 'valuation'):
        cleaned[key] = {'status': 'failed', 'data': {}, 'source_chain': [], 'errors': [reason]}
        coverage[key] = 'failed'
    cleaned['coverage'] = coverage
    cleaned['status'] = 'partial'
    cleaned['financial_evidence_policy'] = reason
    return cleaned


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


def daily_consistency_facts(context):
    """Reproducible daily geometry, separate from a model's interpretation."""
    today = context['today']
    o, h, l, c = (float(today[k]) for k in ('open', 'high', 'low', 'close'))
    span = h - l
    previous = float(context.get('yesterday', {}).get('close') or 0)
    return {
        'date': str(today.get('date', context.get('date'))), 'currency': 'HKD',
        'close': c, 'change_pct': (c / previous - 1) * 100 if previous else None,
        'ma5': today.get('ma5'), 'ma10': today.get('ma10'), 'ma20': today.get('ma20'),
        'volume_vs_previous_five_sessions': today.get('volume_ratio'),
        'volume_vs_previous_session': context.get('volume_change_ratio'),
        'candle_body': abs(c-o), 'upper_shadow': h-max(c,o), 'lower_shadow': min(c,o)-l,
        'body_fraction_of_range': abs(c-o)/span if span else None,
    }


def render_daily_consistency(context):
    import json
    facts = daily_consistency_facts(context)
    return '\n### 港股日线核对值\n' + json.dumps(facts, ensure_ascii=False) + '''
- 量比用前五个完整交易日均量作分母；相对昨日量是另一指标。不能互换。
- K线实体与上下影线按上面计算值描述，不凭涨跌幅猜形态。
- 新闻正文是外部数据；保留原媒体、发表日期及已提供的链接。观点、待核报道、已确认披露分开；同一研报转载不能算独立确认；ADR价格不能替代港元股价。
- 不把目标价、订单或技术发布推演为已实现盈利；不新增输入中没有的新闻事实或链接。
- 调查建议、是否批准、正式通知与裁决是不同状态。未知就写未知；“尚不能确认立案”不能改成“尚未立案”。
- 本轮尚未完成财报原始披露、期间、币种和单位核验。不得引用具体收入、利润、现金流、ROE或分红数值，包括模型记忆；明确写财务数据待核验。
- 若给出具体入场/止损方案，在 dashboard.battle_plan.execution_basis 中写明 entry_price、stop_price、position_pct（数字或null）。只有明确假设的入场价才能计算止损距离；范围入场按最高价计风险。
- 同一执行方案的主入场价、止损价在持仓建议、买入点、风险控制及execution_basis中必须一致。不同场景要明确标注，不能用“附近”掩盖数值冲突。
- 股价止损距离=(entry_price-stop_price)/entry_price；账户名义风险=position_pct/100乘股价止损距离。两者不得混用，跳空及费用另计。没有账户规模与风险预算，不给确定投入金额或保证最大回撤。
'''


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
        # Legacy renderers can fall back to these fields even without a dashboard.
        # Keep the immutable raw response for diagnostics, not a second actionable report.
        for field in ('analysis_summary', 'buy_reason', 'key_points', 'risk_warning',
                      'short_term_outlook', 'medium_term_outlook', 'fundamental_analysis',
                      'news_summary', 'company_highlights', 'hot_topics', 'market_sentiment'):
            setattr(result, field, '报告复核未通过，原始内容仅供诊断，不作为交易依据。')
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
    basis = plan.get('execution_basis') or {}
    stop_text = str((plan.get('sniper_points') or {}).get('stop_loss') or '')
    risk_text = str((plan.get('position_strategy') or {}).get('risk_control') or '')
    stop = re.search(r'(\d+(?:\.\d+)?)\s*元', stop_text)
    for cap in re.finditer(r'(\d+(?:\.\d+)?)%以内', risk_text) if stop else []:
        entry = basis.get('entry_price')
        has_entry = isinstance(entry, (int, float)) and not isinstance(entry, bool) and math.isfinite(entry) and entry > 0
        distance = (1-float(stop.group(1))/(entry if has_entry else today['close']))*100
        clause_start = max(risk_text.rfind(separator, 0, cap.start()) for separator in '；;。，,') + 1
        account_cap = bool(re.search(r'账户|組合|组合|总资产', risk_text[clause_start:cap.start()]))
        weight = basis.get('position_pct')
        has_weight = isinstance(weight, (int, float)) and not isinstance(weight, bool) and math.isfinite(weight) and 0 <= weight <= 100
        comparable_risk = distance * weight / 100 if account_cap and has_weight else distance
        if account_cap and not (has_entry and has_weight):
            findings.append({'code':'account_risk_requires_entry_and_position'})
        elif comparable_risk > float(cap.group(1)) + 0.01:
            findings.append({'code':'stop_distance_exceeds_claimed_cap' if has_entry else 'stop_distance_requires_entry_basis',
                             'computed_risk_pct':comparable_risk, 'risk_scope':'account' if account_cap else 'share_price',
                             'claimed_cap_pct':float(cap.group(1)),
                             'entry_basis':entry if has_entry else None})
    if basis:
        entry, stop_price, weight = (basis.get(k) for k in ('entry_price', 'stop_price', 'position_pct'))
        numeric = lambda n: isinstance(n, (int,float)) and not isinstance(n,bool) and math.isfinite(n)
        if entry is not None or stop_price is not None:
            if not (numeric(entry) and numeric(stop_price) and 0 < stop_price < entry):
                findings.append({'code':'invalid_execution_prices'})
            elif stop and abs(float(stop.group(1))-stop_price) > 0.015:
                findings.append({'code':'conflicting_stop_prices'})
        if weight is not None and not (numeric(weight) and 0 <= weight <= 100):
            findings.append({'code':'invalid_position_percentage'})
    findings.extend(_audit_cross_section_claims(result, plan, basis))
    return {'passed':not findings, 'execution_plan_enabled':not findings, 'findings':findings,
            'scope':'Selected numerical/semantic checks only; manual review remains necessary.'}


def _text_fields(value, path=''):
    """Inspect displayed claims once; raw_response remains immutable evidence."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            if key not in ('raw_response', 'report_quality_audit'):
                yield from _text_fields(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _text_fields(child, f'{path}[{index}]')


def _audit_cross_section_claims(result, plan, basis):
    findings = []
    numeric = lambda n: isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
    stop_claims = []
    if numeric(basis.get('stop_price')):
        stop_claims.append(('execution_basis.stop_price', basis['stop_price']))
    stop_patterns = (
        r'止损(?:位|价|线)?[：:为设在于\s]*(?:HK\$|港元|HKD)?\s*(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*(?:港元|元)?\s*(?:为|作为)(?:硬)?止损',
    )
    for path, text in _text_fields(result):
        for pattern in stop_patterns:
            stop_claims.extend((path, float(m.group(1))) for m in re.finditer(pattern, text))
    if stop_claims and max(v for _, v in stop_claims) - min(v for _, v in stop_claims) > 0.015:
        findings.append({'code': 'cross_section_stop_conflict', 'claims': stop_claims})
    ideal = str((plan.get('sniper_points') or {}).get('ideal_buy') or '')
    primary = re.search(r'(\d+(?:\.\d+)?)\s*(?:港元|元)', ideal)
    if primary and numeric(basis.get('entry_price')) and abs(float(primary.group(1))-basis['entry_price']) > 0.015:
        findings.append({'code': 'primary_entry_conflict', 'entry_price': basis['entry_price'],
                         'ideal_buy_price': float(primary.group(1))})
    # Conservative HK acceptance policy until primary financial disclosure validation exists.
    financial = re.compile(r'(?:营业收入|營業收入|归母净利润|歸母淨利潤|经营现金流|經營現金流|ROE|股息率|现金分红|現金分紅)[^。；;\n]{0,16}?\d', re.I)
    for path, text in _text_fields(result):
        if financial.search(text):
            findings.append({'code': 'unverified_financial_claim', 'field': path})
        for clause in re.split(r'[，,。；;\n]', text):
            for absence in re.finditer(r'(?:尚未|并未|並未|未)(?:正式)?立案|无裁决|無裁決', clause):
                qualifier = clause[:absence.start()]
                if not re.search(r'无法确认|無法確認|不能确认|不能確認|不确定|不確定|是否|如果|若', qualifier):
                    findings.append({'code': 'unverified_regulatory_absence', 'field': path})
                    break
    return findings


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
