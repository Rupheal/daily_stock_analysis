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
    if context.get('company_news_evidence') is not None:
        context['hk_report_contract']['news_events'] = deepcopy(context['company_news_evidence'])
    return context


def render_contract_prompt(context):
    contract = context.get('hk_report_contract')
    if not contract:
        return ''
    issuer = context.get('issuer_announcements') or {}
    text = '\n### 必须遵守的结构化报告契约（优先于旧版仪表盘示例）\n' + json.dumps(
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
    if 'news_events' in contract:
        text += '''
本轮还启用确定性行情与新闻展示：顶层ma_analysis、news_summary以及dashboard.intelligence.latest_news均输出空字符串，dashboard.intelligence.positive_catalysts输出[]。这些字段由程序从核验值和news_events生成，包含原媒体、公开时间、URL和证据类型。其他分析只给观点，不重复新闻细节或未经核验的“公告已证明”事实。
顶层data_sources也输出空字符串。来源声明由程序生成；已隔离的财务数值及旧来源链均不能重新成为证据。
在dashboard.news_review中逐个给出news_events的event_id与assessment（只写观点，不能添加新事实数字）。每个事件只能出现一次。程序将观点与输入中的媒体报道/券商预测明确分开，完整保留逐事件引用。
均线排列是同一天不同周期的大小关系，均线升降必须分别比较各自前一交易日，按下面计算值描述。如果昨日和今日收盘均低于各自MA5，只能说从下方接近或远离MA5，不能写成从均线上方缩量回踩。
乖离率只是价格距离指标，不可写“无追高风险”“零风险”；低乖离不等于无交易风险。
'''
        text += '\n均线逐日变化核验值：' + verified_ma_text(context)
    return text


def verified_ma_text(context):
    today, yesterday = context['today'], context.get('yesterday') or {}
    parts = []
    for key in ('ma5', 'ma10', 'ma20'):
        if today.get(key) is None:
            continue
        value = float(today[key])
        label = f'{key.upper()} {value:.2f} 港元'
        if yesterday.get(key) is not None:
            delta = value-float(yesterday[key])
            label += f'，较前一交易日{("上升" if delta > 0 else "下降" if delta < 0 else "持平")} {abs(delta):.2f} 港元'
        parts.append(label)
    return '；'.join(parts)+'。排列与各条均线的日变化是不同指标。'


def verified_news_text(context, reviews):
    opinions = {r['event_id']: r['assessment'] for r in reviews}
    lines = []
    for event in context['hk_report_contract']['news_events']:
        sources = event.get('source_records')
        citations = ' ; '.join(f"{s['source']}: {s['url']}" for s in sources) if sources else ' ; '.join(event['source_urls'])
        lines.append(f"[{event['evidence_kind']}] {event['source']} / {event['published_at']} UTC / {event['title']}\n"
                     f"输入摘要：{event['summary']}\n模型观点：{opinions[event['event_id']]}\n来源：" + citations)
    return '\n\n'.join(lines)


def verified_source_text(context):
    return (f"日线日期 {context['today']['date']}，对应本轮已校验的日线输入；"
            '新闻原媒体、公开时间和链接见逐事件引用；风险原件可得性见证据账本；'
            '财务数据及其旧来源链已隔离，未作为基本面数值依据；'
            '未采用缺失的realtime_quote；公告目录不等于逐份正文核验。')


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
    if 'news_events' in contract:
        news_reviews = dashboard.get('news_review')
        expected_ids = {e['event_id'] for e in contract['news_events']}
        valid_reviews = isinstance(news_reviews, list) and all(isinstance(r, dict)
            and r.get('event_id') in expected_ids and str(r.get('assessment') or '').strip() for r in news_reviews)
        if not valid_reviews or {r['event_id'] for r in news_reviews} != expected_ids or len(news_reviews) != len(expected_ids):
            findings.append({'code': 'company_news_review_incomplete'})
        else:
            rendered = verified_news_text(context, news_reviews)
            intelligence = dashboard.get('intelligence') or {}
            for name, actual, expected in [('ma_analysis', result.get('ma_analysis'), verified_ma_text(context)),
                    ('data_sources', result.get('data_sources'), verified_source_text(context)),
                    ('news_summary', result.get('news_summary'), rendered),
                    ('latest_news', intelligence.get('latest_news'), rendered)]:
                if actual not in (None, '', expected):
                    findings.append({'code': 'duplicate_verified_fact_definition', 'field': name})
            if intelligence.get('positive_catalysts') not in (None, []):
                findings.append({'code': 'unattributed_media_fact_definition'})
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
    if 'news_events' in context['hk_report_contract']:
        result.ma_analysis = verified_ma_text(context)
        result.news_summary = verified_news_text(context, result.dashboard['news_review'])
        result.dashboard.setdefault('intelligence', {})['latest_news'] = result.news_summary
        result.dashboard['intelligence']['positive_catalysts'] = []
        result.data_sources = verified_source_text(context)


def event_identity(item):
    """Only reviewed source URLs/dates share an event; later updates stay visible."""
    from src.services.hk_company_news import canonical_url
    url = canonical_url(item['url'])
    day = str(item.get('published_at') or '')[:10]
    registry = json.loads((REGISTRY.parent/'hk-reviewed-news-groups.json').read_text())
    matches = [group['id'] for group in registry['groups']
               if url in group['urls'] and day in group['publication_dates']]
    if len(matches) > 1:
        raise ValueError('Conflicting reviewed event groups')
    if matches:
        return matches[0], True
    return 'article-' + hashlib.sha256((url+'|'+day).encode()).hexdigest()[:16], False


def deduplicate_events(items):
    grouped = {}
    for item in items:
        identity, reviewed = event_identity(item)
        if identity not in grouped:
            grouped[identity] = dict(item, event_id=identity, grouping_reviewed=reviewed,
                                     event_source_urls=[item['url']],
                                     event_source_records=[{'source': item.get('source', 'unknown'),
                                                            'url': item['url']}])
        elif item['url'] not in grouped[identity]['event_source_urls']:
            grouped[identity]['event_source_urls'].append(item['url'])
            grouped[identity]['event_source_records'].append({'source': item.get('source', 'unknown'), 'url': item['url']})
    return list(grouped.values())
