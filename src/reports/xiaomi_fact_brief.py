"""A factual document built from the existing price preflight, without an LLM.

The schema deliberately has no prediction, score or execution-plan fields.
Legacy model narratives are never copied into this product.
"""
import hashlib
import html
import json
import math
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from src.services.market_data_integrity import daily_consistency_facts, validate_daily_context


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Missing numeric field: ' + name)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('Invalid numeric field: ' + name)
    return float(value)


def _timestamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    # The existing news repository serializes UTC without an offset.
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _url(value):
    parts = urlsplit(str(value))
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        raise ValueError('Invalid source URL')
    return str(value)


def build_fact_brief(preflight, mode='snapshot', generated_at=None, expected_date=None):
    """Validate the input and project only verified facts and attributed sources."""
    if mode not in ('refresh', 'snapshot'):
        raise ValueError('Unknown report mode')
    if preflight.get('passed') is not True or preflight.get('symbol', 'HK01810') != 'HK01810':
        raise ValueError('Xiaomi price preflight has not passed')
    if _number(preflight.get('overlap'), 'overlap') < 60:
        raise ValueError('Fewer than 60 independently compared sessions')
    generated = _timestamp(generated_at or datetime.now(timezone.utc).isoformat())
    prepared = _timestamp(preflight['prepared_at'])
    target = date.fromisoformat(preflight['target'])
    if target > prepared.date() or prepared > generated:
        raise ValueError('Future preflight/session')
    if mode == 'refresh' and (not expected_date or str(target) != str(expected_date)):
        raise ValueError('Fresh report requires the current completed-session date')
    if mode == 'refresh' and (generated-prepared).total_seconds() > 3600:
        raise ValueError('Preflight too old for a fresh report')
    today, yesterday = preflight['today'], preflight['yesterday']
    context = {'today': today, 'yesterday': yesterday}
    validate_daily_context(context, expected_date or target)
    validate_daily_context({'today': yesterday}, yesterday['date'])
    for row_name, row in (('today', today), ('yesterday', yesterday)):
        for field in ('open', 'high', 'low', 'close', 'ma5', 'ma10', 'ma20'):
            _number(row.get(field), row_name + '.' + field, positive=True)
        _number(row.get('volume'), row_name + '.volume')
    if today['volume'] % 1 or yesterday['volume'] % 1:
        raise ValueError('Share volumes must be integers')
    _number(today.get('volume_ratio'), 'volume_ratio')
    context['volume_change_ratio'] = today['volume']/yesterday['volume'] if yesterday['volume'] else None
    facts = daily_consistency_facts(context)
    sections = []
    sections.append({'title': '完整交易日日线', 'paragraphs': [
        f"腾讯与 Yahoo 已比较 {int(preflight['overlap'])} 个共同交易日的开高低收及成交量。",
        '腾讯前复权与 Yahoo auto_adjust 在本次共同区间吻合；不代表所有公司行动均已核验。'],
        'headers': ['项目', '值', '单位／口径'], 'rows': [
            ['日期', str(target), '香港交易日；非盘中报价'],
            *[[{'open': '开盘', 'high': '最高', 'low': '最低', 'close': '收盘'}[k], f'{today[k]:.2f}', '港元']
              for k in ('open', 'high', 'low', 'close')],
            ['前收盘', f"{yesterday['close']:.2f}", '港元'],
            ['涨跌幅', f"{facts['change_pct']:+.2f}%", '（收盘 ÷ 前收盘 − 1）× 100'],
            ['成交量', f"{today['volume']:,.0f}", '股'],
            ['相对前五日均量', f"{today['volume_ratio']:.2f} 倍", '当日成交量 ÷ 前五个完整交易日平均量'],
            ['相对前一日成交量', f"{context['volume_change_ratio']:.2f} 倍" if context['volume_change_ratio'] is not None else '无法计算',
             '当日成交量 ÷ 前一交易日成交量']]})
    ma_rows = []
    for key in ('ma5', 'ma10', 'ma20'):
        delta = round(today[key]-yesterday[key], 8)
        ma_rows.append([key.upper(), f'{yesterday[key]:.2f}', f'{today[key]:.2f}',
                        ('上升' if delta > 0 else '下降' if delta < 0 else '持平') + f' {abs(delta):.2f}',
                        '低于' if today['close'] < today[key] else '高于' if today['close'] > today[key] else '相等'])
    ordered = sorted((today[k], k.upper()) for k in ('ma5', 'ma10', 'ma20'))
    order = ordered[0][1]
    for previous, current in zip(ordered, ordered[1:]):
        order += (' = ' if current[0] == previous[0] else ' < ') + current[1]
    sections.append({'title': '均线：排列与升降分别展示',
        'paragraphs': [f'当日数值顺序：{order}。每条均线升降只与自身前一交易日比较。',
            f"收盘相对 MA5 的乖离率为 {facts['bias_ma5_pct_from_displayed_ma']:+.2f}%，按展示均线计算；不代表风险大小。"],
        'headers': ['均线', '前一日／港元', '当日／港元', '日变化／港元', '收盘相对该线'], 'rows': ma_rows})
    candle = '阳线（收盘高于开盘）' if today['close'] > today['open'] else '阴线（收盘低于开盘）' if today['close'] < today['open'] else '开收相等'
    sections.append({'title': 'K线：只描述可复算几何', 'paragraphs': [candle + '。单根形态不用于推断未来胜率或压力区。'],
        'headers': ['项目', '数值', '计算口径'], 'rows': [
            ['实体', f"{facts['candle_body']:.2f} 港元", '|收盘 − 开盘|'],
            ['上影', f"{facts['upper_shadow']:.2f} 港元", '最高 − max（开盘，收盘）'],
            ['下影', f"{facts['lower_shadow']:.2f} 港元", 'min（开盘，收盘）− 最低'],
            ['全日高低差', f"{today['high']-today['low']:.2f} 港元", '最高 − 最低'],
            ['实体占高低差', f"{facts['body_fraction_of_range']*100:.2f}%" if facts['body_fraction_of_range'] is not None else '无法计算（高低相等）', '实体 ÷（最高 − 最低）']]})
    primary = preflight.get('verified_primary_evidence') or {}
    if primary:
        from src.services.xiaomi_primary_evidence import render_primary_sections
        sections.extend(render_primary_sections(primary))
    contract = preflight.get('hk_report_contract') or {}
    news, quarantined, seen = [], [], set()
    for event in contract.get('news_events', []):
        try:
            identifier = event['event_id']
            age = (prepared-_timestamp(event['published_at'])).total_seconds()
            if not 0 <= age <= 72*3600:
                raise ValueError('outside_72_hour_window')
            if identifier in seen:
                raise ValueError('duplicate_event_id')
            urls = [_url(u) for u in event['source_urls']]
            if not urls or not event.get('source') or not event.get('title'):
                raise ValueError('missing_provenance')
            seen.add(identifier)
            # Headlines are attributed. Long scraped article summaries are not republished.
            news.append({'title': event['title'], 'paragraphs': [
                f"原媒体：{event['source']}；公开时间：{event['published_at']} UTC（数据库标准化口径）。",
                '证据类型：' + event.get('evidence_kind', '媒体报道，待原始披露核验')],
                'links': [{'label': item.get('source') or event['source'], 'url': _url(item['url'])}
                          for item in event.get('source_records', [])] or [{'label': event['source'], 'url': u} for u in urls]})
        except (KeyError, ValueError, TypeError) as exc:
            quarantined.append({'event_id': event.get('event_id'), 'reason': str(exc)})
    sections.append({'title': '近期公司报道与观点', 'paragraphs': [
        f"预检记录 {preflight.get('news_count', 0)} 篇公司文章、{len(preflight.get('origins', []))} 家原媒体；本页展示 {len(news)} 个候选事件。",
        '转载载体不另算出版机构；候选事件去重尚不完整，数量不代表独立确认。标题属于原媒体报道，不等于本程序核实全文。',
        ('仅补证表内财务字段已核对原件，其他字段保持未知。' if primary.get('financial_fields') else '财务数据未核验，基本面方向无法判断。') + '有限检索不能证明没有利空。'], 'items': news})
    risks = []
    for event in contract.get('events', []):
        if event.get('status') != 'unresolved':
            continue
        risks.append({'title': event['id'], 'paragraphs': [
            f"类型：{event['kind']}；公开时间：{event['published_at']}；最近人工核查：{event['reviewed_at']}。",
            event['summary'], '公司回应：' + event['company_response'],
            '状态沿用已复核账本；本次生成时间不代表重新核实该事件。'],
            'links': [{'label': source['publisher_group'] + '；' + source['verification'], 'url': _url(source['url'])}
                      for source in event['sources']]})
    sections.append({'title': '持续风险：不随72小时窗口消失', 'items': risks,
        'paragraphs': ['已知未解决风险按各自证据状态保留；账本不保证完整。']})
    issuer = preflight.get('issuer_announcements') or {}
    sections.append({'title': '公司公告目录', 'paragraphs': [
        f"本轮取得 {len(issuer.get('items', []))} 条目录记录；目录可读不等于全文核验完成。", issuer.get('timezone_note', '公告时间精度以原始目录为准。')],
        'items': [{'title': item['published_date'] + ' · ' + item['title'],
                   'paragraphs': ['正文核验状态：' + ('已核验' if item.get('full_text_verified') else '本次未完成全文自动核验')],
                   'links': [{'label': '公司公告原件', 'url': _url(u)} for u in item['source_urls']]}
                  for item in issuer.get('items', [])]})
    limitations = ['本版只发布行情事实、新闻索引及风险证据状态；没有买卖指令、仓位、止损或预测概率。',
        '盘中报价时间戳、全部公告正文、未列入补证的财报字段、事件去重泛化及策略有效性尚未全部验收。']
    if not news:
        limitations.append('近期公司新闻缺失或被隔离；不能将空列表解释为没有事件。')
    if not risks:
        limitations.append('持续风险账本未提供可用项目；不能解释为没有未解决风险。')
    if issuer.get('status') == 'failed':
        limitations.append('公告采集失败：' + issuer.get('error', '未记录原因'))
    diagnostics = preflight.get('news_diagnostics', [])
    if diagnostics:
        limitations.append('逐源采集诊断：' + json.dumps(diagnostics, ensure_ascii=False))
    if quarantined:
        limitations.append('新闻隔离记录：' + json.dumps(quarantined, ensure_ascii=False))
    sections.append({'title': '覆盖缺口与费用', 'paragraphs': limitations + [
        '本入口不调用模型、不启动扫描或定时任务。模型API费用为0；GitHub运行实际费用未核实。']})
    return {'schema_version': 1, 'product': 'xiaomi_fact_brief', 'symbol': 'HK01810',
        'title': '小米 HK01810｜固定事实简报', 'status': 'FACTS_READY_LIMITED_COVERAGE',
        'mode': mode, 'generated_at': generated.isoformat(), 'data_prepared_at': prepared.isoformat(),
        'session_date': str(target), 'model_http_requests': 0, 'trading_plan_enabled': False,
        'preflight_sha256': hashlib.sha256(json.dumps(preflight, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
        'facts': facts, 'sections': sections}


def render_markdown(brief):
    def clean(value):
        return str(value).replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')
    lines = ['# ' + brief['title'], '',
        f"交易日：{brief['session_date']}｜数据预检：{brief['data_prepared_at']}｜生成：{brief['generated_at']}", '',
        '运行方式：' + ('本次重新取数并核验。' if brief['mode'] == 'refresh' else '已保存预检快照回放；不代表当前行情。'), '']
    for section in brief['sections']:
        lines += ['## ' + section['title'], ''] + [clean(p) + '\n' for p in section.get('paragraphs', [])]
        if section.get('headers'):
            lines += ['| ' + ' | '.join(map(clean, section['headers'])) + ' |',
                      '| ' + ' | '.join(['---'] * len(section['headers'])) + ' |']
            lines += ['| ' + ' | '.join(map(clean, row)) + ' |' for row in section['rows']]
            lines.append('')
        lines += [clean(link['label']) + '：' + _url(link['url']) + '\n' for link in section.get('links', [])]
        for item in section.get('items', []):
            lines += ['### ' + clean(item['title']), ''] + [clean(p) + '\n' for p in item.get('paragraphs', [])]
            lines += [clean(link['label']) + '：' + link['url'] + '\n' for link in item.get('links', [])]
    return '\n'.join(lines)


def render_html(brief):
    esc = lambda value: html.escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>' + esc(brief['title']) + '</title><style>',
        'body{font:16px/1.7 system-ui,sans-serif;color:#192f43;background:#eef3f6;margin:0}main{max-width:960px;margin:32px auto;background:white;padding:36px}h1{font-size:29px}h2{border-bottom:2px solid #d7e5eb;padding-top:16px}h3{font-size:17px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d7e5eb;padding:9px;text-align:left}th{background:#eaf3f7}a{color:#145779;overflow-wrap:anywhere}p{overflow-wrap:anywhere}.meta{color:#526879;font-size:14px}.badge{background:#eaf3f7;padding:12px}@media print{body{background:white}main{padding:0;margin:0}h2,h3{break-after:avoid}tr{break-inside:avoid}}',
        '</style><main><h1>' + esc(brief['title']) + '</h1>',
        '<p class="badge">' + ('事实与受约束研究判断' if brief.get('product') == 'xiaomi_constrained_research' else '固定事实版') + '｜覆盖有限｜未启用交易方案</p>',
        '<p class="meta">交易日：' + esc(brief['session_date']) + '<br>数据预检：' + esc(brief['data_prepared_at']) + '<br>生成：' + esc(brief['generated_at']) + '</p>',
        '<p>' + ('本次重新取数并核验。' if brief['mode'] == 'refresh' else '已保存预检快照回放；不代表当前行情。') + '</p>']
    for section in brief['sections']:
        parts.append('<h2>' + esc(section['title']) + '</h2>')
        parts += ['<p>' + esc(p) + '</p>' for p in section.get('paragraphs', [])]
        if section.get('headers'):
            parts += ['<table><thead><tr>' + ''.join('<th>' + esc(h) + '</th>' for h in section['headers']) + '</tr></thead><tbody>']
            parts += ['<tr>' + ''.join('<td>' + esc(c) + '</td>' for c in row) + '</tr>' for row in section['rows']]
            parts.append('</tbody></table>')
        parts += ['<p><a rel="noreferrer" href="' + esc(_url(link['url'])) + '">' + esc(link['label']) + '</a></p>' for link in section.get('links', [])]
        for item in section.get('items', []):
            parts.append('<h3>' + esc(item['title']) + '</h3>')
            parts += ['<p>' + esc(p) + '</p>' for p in item.get('paragraphs', [])]
            parts += ['<p><a rel="noreferrer" href="' + esc(link['url']) + '">' + esc(link['label']) + '</a></p>' for link in item.get('links', [])]
    return ''.join(parts) + '</main></html>'
