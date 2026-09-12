"""Reviewed event evidence and one executable price definition for HK reports.

The registry is a reviewed checkpoint, not a live claim that a risk has ended.
Unknown event grouping is explicitly an upper bound, not independent confirmation.
"""
import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / 'docs/hk-reviewed-events.json'


def reviewed_events(code, now=None, registry_path=None):
    symbol = str(code).upper().removeprefix('HK').removesuffix('.HK').lstrip('0')
    if symbol != '1810':
        return []
    now = now or datetime.now(timezone.utc)
    data = json.loads(Path(registry_path or REGISTRY).read_text())
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported reviewed event registry')
    selected, seen = [], set()
    for event in data['events']:
        if event['id'] in seen:
            raise ValueError('Duplicate reviewed event ID')
        seen.add(event['id'])
        published = datetime.fromisoformat(event['published_at'])
        reviewed = datetime.fromisoformat(event['reviewed_at'])
        if event.get('publication_precision') == 'day':
            time_valid = len(event['published_at']) == 10 and published.date() <= reviewed.date()
        else:
            time_valid = published.tzinfo is not None and published <= reviewed
        if reviewed.tzinfo is None or not time_valid or reviewed > now:
            raise ValueError('Invalid reviewed event times')
        if not event['sources'] or event['status'] not in ('unresolved', 'context', 'resolved'):
            raise ValueError('Invalid reviewed event evidence')
        if event['status'] == 'resolved' and not event.get('resolution_source'):
            raise ValueError('Closing a risk requires resolution evidence')
        if event['status'] != 'resolved':
            selected.append(deepcopy(event))
    return selected


def attach_report_contract(context, code=None):
    events = reviewed_events(code or context.get('code'))
    if not events:
        return context
    context['hk_report_contract'] = {
        'version': 1, 'events': events,
        'required_risk_ids': [e['id'] for e in events if e['status'] == 'unresolved'],
        'coverage': '有限公开信源；未解决风险跨新闻窗口保留。未完成全部公告正文及财报核验。',
    }
    return context


def render_contract_prompt(context):
    contract = context.get('hk_report_contract')
    if not contract:
        return ''
    issuer = context.get('issuer_announcements') or {}
    return '\n### 必须遵守的结构化报告契约（优先于旧版仪表盘示例）\n' + json.dumps(
        dict(contract, issuer_announcements=issuer), ensure_ascii=False) + '''
以上是经过人工复核的证据状态，不代表完整调查或当前法律结论。发布时间不能换成复核时间。
在 dashboard.evidence_review 中输出数组；每项必须是 {"event_id":"输入ID","status":"输入status","kind":"输入kind","source_urls":["输入sources中的url"],"assessment":"你的简短评述"}。全部 required_risk_ids 必须出现；不得把报道/当事方指控当成监管裁决。证据里的公司回应未知必须保持未知。
每个事件只计一次；转载和翻译不算独立确认。不要复制原文长段或使用未提供的链接。
在 dashboard.battle_plan.execution_basis 只定义一个方案：
{"mode":"watch或conditional_long","entry_price":数字或null,"stop_price":数字或null,"position_pct":数字或null}。
watch代表观察，三个数值均填null，不发布买卖触发。conditional_long代表明确假设的条件方案，必须0<stop_price<entry_price且0<position_pct<=100，不是马上买入。没有充分条件可选择watch。
模型不要在其他叙述重复入场/止损/仓位数字。dashboard.battle_plan.sniper_points、position_strategy和dashboard.core_conclusion.position_advice一律输出{}；这些展示字段由程序依据execution_basis生成，不要自行填写。不要另给次优买入、减仓或止盈方案。
数字行情和均线可照实分析；分析不等于交易指令。财务数据待核验，基本面方向无法判断。全文约1500中文字以内，保留风险来源链接和覆盖限制。
'''


def execution_fields(basis):
    if basis['mode'] == 'watch':
        text = '观察；本轮不启用入场、止损或仓位执行方案。'
        return {'ideal_buy': text, 'secondary_buy': text, 'stop_loss': text, 'take_profit': text}, {
            'suggested_position': text, 'entry_plan': text, 'risk_control': text}, {
            'no_position': text, 'has_position': '未取得现有持仓成本与风险预算，现有仓位处理待单独评估。'}
    entry, stop, weight = (basis[k] for k in ('entry_price', 'stop_price', 'position_pct'))
    distance = (entry-stop)/entry*100
    entry_text = f'条件方案假设入场价 {entry:.2f} 元；条件成立与否仍需复核。'
    stop_text = f'同一条件方案止损价 {stop:.2f} 元；跳空可能无法按该价成交。'
    weight_text = f'假设仓位 {weight:g}%；未指定实际投入金额。'
    risk = f'股价止损距离 {distance:.2f}%；账户名义风险 {distance*weight/100:.2f}%；不含跳空、滑点及费用，不保证最大回撤。'
    return {'ideal_buy': entry_text, 'secondary_buy': '本轮未定义第二入场方案。',
            'stop_loss': stop_text, 'take_profit': '本轮未定义止盈方案。'}, {
            'suggested_position': weight_text, 'entry_plan': entry_text, 'risk_control': risk}, {
            'no_position': entry_text + weight_text,
            'has_position': '仅适用于上述假设方案；未核验现有持仓成本。' + stop_text}


def audit_contract(result, context):
    contract = context.get('hk_report_contract')
    if not contract:
        return []
    dashboard = result.get('dashboard') or {}
    findings = []
    reviews = dashboard.get('evidence_review')
    evidence = {e['id']: e for e in contract['events']}
    acknowledged = set()
    if not isinstance(reviews, list):
        reviews = []
    for row in reviews:
        if not isinstance(row, dict) or row.get('event_id') not in evidence:
            findings.append({'code': 'unknown_evidence_id'})
            continue
        event = evidence[row['event_id']]
        urls = row.get('source_urls')
        if (row['event_id'] in acknowledged or row.get('status') != event['status']
                or row.get('kind') != event['kind'] or not isinstance(urls, list) or not urls
                or not all(u in {s['url'] for s in event['sources']} for u in urls)
                or not str(row.get('assessment') or '').strip()):
            findings.append({'code': 'evidence_state_or_provenance_mismatch', 'event_id': event['id']})
        acknowledged.add(event['id'])
    missing = set(contract['required_risk_ids']) - acknowledged
    if missing:
        findings.append({'code': 'unresolved_risk_omitted', 'event_ids': sorted(missing)})
    plan = dashboard.get('battle_plan') or {}
    basis = plan.get('execution_basis') or {}
    values = [basis.get(k) for k in ('entry_price', 'stop_price', 'position_pct')]
    number = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    valid = (basis.get('mode') == 'watch' and all(v is None for v in values)) or (
        basis.get('mode') == 'conditional_long' and all(number(v) for v in values)
        and 0 < values[1] < values[0] and 0 < values[2] <= 100)
    if not valid:
        findings.append({'code': 'invalid_structured_execution'})
    else:
        expected = execution_fields(basis)
        actual = (plan.get('sniper_points'), plan.get('position_strategy'),
                  (dashboard.get('core_conclusion') or {}).get('position_advice'))
        for name, value, generated in zip(('sniper_points', 'position_strategy', 'position_advice'), actual, expected):
            if value not in (None, {}) and value != generated:
                findings.append({'code': 'duplicate_execution_definition', 'field': name})
    return findings


def render_execution_fields(result, context):
    if not context.get('hk_report_contract'):
        return
    plan = result.dashboard['battle_plan']
    plan['sniper_points'], plan['position_strategy'], advice = execution_fields(plan['execution_basis'])
    result.dashboard.setdefault('core_conclusion', {})['position_advice'] = advice


def event_identity(item):
    """Known observed event families; other URLs remain unmerged candidates."""
    from src.services.hk_company_news import canonical_url
    text = (str(item.get('title', '')) + ' ' + str(item.get('summary', ''))).casefold()
    if 'cocktailasr' in text:
        return 'xiaomi-cocktailasr-20260910', True
    if ('sfio' in text or 'serious fraud' in text) and ('xiaomi' in text or '小米' in text):
        return 'xiaomi-india-sfio-20260909', True
    if ('anthropic' in text) and ('xiaomi' in text or '小米' in text):
        return 'xiaomi-anthropic-20260910', True
    # A single broker opinion event across observed translated republications.
    if ('里昂' in text or 'clsa' in text) and ('skynomad' in text):
        return 'xiaomi-clsa-skynomad-20260911', True
    return 'article-' + hashlib.sha256(canonical_url(item['url']).encode()).hexdigest()[:16], False


def deduplicate_events(items):
    grouped = {}
    for item in items:
        identity, reviewed = event_identity(item)
        if identity not in grouped:
            grouped[identity] = dict(item, event_id=identity, grouping_reviewed=reviewed,
                                     event_source_urls=[item['url']])
        elif item['url'] not in grouped[identity]['event_source_urls']:
            grouped[identity]['event_source_urls'].append(item['url'])
    return list(grouped.values())
