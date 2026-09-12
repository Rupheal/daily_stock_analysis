"""Regional-source boundaries, publication time and failure isolation."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.services.hk_company_news import (
    approved_news_origin, etnet_candidates, parse_etnet_article,
    parse_regional_rss, refresh_company_news, select_company_evidence,
)

NOW = datetime(2026, 9, 12, 8, tzinfo=timezone.utc)
ETNET = 'https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news_detail.php?code=1810&newsid=example'


def rss_item(title='小米業績公告', date='Fri, 11 Sep 2026 15:04:00 +0800', url=ETNET):
    return f'<item><title>{title}</title><pubDate>{date}</pubDate><link>{url.replace("&", "&amp;")}</link><description>小米公司新聞摘要</description></item>'


class RegionalSourceTests(unittest.TestCase):
    def test_syndication_does_not_change_origin_or_admit_unknown_publisher(self):
        item = dict(url='https://news.futunn.com/post/1', source='财联社')
        self.assertIsNone(approved_news_origin(item))
        for source in ['快讯', 'PR Newswire', 'DoNews', 'Reuters fake']:
            self.assertIsNone(approved_news_origin(dict(item, source=source)))
        self.assertEqual(approved_news_origin(dict(item, source='道琼斯')), ('Dow Jones', 'US'))
        self.assertEqual(approved_news_origin(dict(item, source='Reuters'))[0], 'Reuters')
        self.assertIsNone(approved_news_origin(dict(item, url='https://www.etnet.com.hk.evil.example/a')))

    def test_cached_mainland_records_cannot_reenter_hk_context(self):
        rows = [dict(title='小米监管调查', source='财联社', url='https://news.futunn.com/post/1'),
                dict(title='小米业绩', source='AASTOCKS', url='https://finance.sina.com.cn/a'),
                dict(title='Xiaomi earnings', source='道琼斯', url='https://news.futunn.com/post/2')]
        self.assertEqual(select_company_evidence(rows, 6, require_approved_origin=True), rows[2:])

    def test_rss_rejects_undated_naive_future_old_and_unapproved_links(self):
        xml = '<rss><channel>' + ''.join([
            rss_item(), rss_item(date=''), rss_item(date='Fri, 11 Sep 2026 15:04:00'),
            rss_item(date='Sun, 13 Sep 2026 15:04:00 +0800'),
            rss_item(date='Mon, 01 Sep 2025 15:04:00 +0800'),
            rss_item(url='https://finance.sina.com.cn/story'),
        ]) + '</channel></rss>'
        rows = parse_regional_rss(xml, '《經濟通》新聞', 'hk01810', '小米集团', NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['published_at'], datetime(2026, 9, 11, 7, 4))
        self.assertFalse(json.loads(rows[0]['raw_payload'])['independent_confirmation'])

    def test_html_login_page_is_not_a_successful_feed(self):
        with self.assertRaises(ValueError):
            parse_regional_rss('<html><body>Sign in</body></html>', 'FT', '01810', '小米', NOW)

    def test_etnet_candidates_use_article_date_and_company_code(self):
        good = '<div class="DivArticleList"><p class="date">11/09/2026 15:04</p><a href="quote_news_detail.php?code=1810&amp;newsid=one">小米新聞</a></div>'
        content = good + good.replace('code=1810', 'code=700') + good.replace('11/09/2026', '01/01/2025')
        urls = etnet_candidates(content, 'hk01810', '小米集团', NOW)
        self.assertEqual(len(urls), 1)
        self.assertIn('newsid=one', urls[0])

    def test_etnet_article_requires_body_and_explicit_minute(self):
        html = '<div class="DivArticleList"><p class="date">11/09/2026 12:34</p><h1 class="ArticleHdr">《券商精點》小米評級</h1></div><div id="NewsContent"><p itemprop="articleBody">分析師預測小米盈利</p></div>'
        row = parse_etnet_article(html, ETNET, 'hk01810', '小米集团', NOW)
        self.assertEqual(row['published_at'], datetime(2026, 9, 11, 4, 34))
        self.assertIn('观点/预测', row['summary'])
        self.assertIsNone(parse_etnet_article(html.replace('12:34', ''), ETNET, '01810', '小米', NOW))
        self.assertIsNone(parse_etnet_article(html.replace('articleBody', 'missing'), ETNET, '01810', '小米', NOW))

    def test_failed_primary_does_not_silently_fetch_mainland_backup(self):
        saved, requested = [], []
        service = SimpleNamespace(repo=SimpleNamespace(upsert_items=lambda rows: saved.extend(rows) or len(rows)))
        xml = '<rss><channel>' + rss_item() + '</channel></rss>'
        def fetch(service, url):
            requested.append(url)
            if 'section=editor' in url:
                return xml
            raise TimeoutError('source unavailable')
        with patch('src.services.hk_company_news.fetch_public', side_effect=fetch):
            result = refresh_company_news(service, 'hk01810', '小米集团', now=NOW)
        self.assertEqual(result['accepted'], 1)
        self.assertTrue(any('error' in d for d in result['diagnostics']))
        self.assertFalse(any('sina' in url or 'eastmoney' in url or 'cls.cn' in url for url in requested))
        self.assertEqual(json.loads(saved[0]['raw_payload'])['source_policy'], 'hk-us-europe')


if __name__ == '__main__':
    unittest.main()
