import unittest

from src.search_service import SearchResponse, SearchResult, SearchService


class SearchSourcePolicyTests(unittest.TestCase):
    def test_all_hk_symbol_forms_filter_mainland_and_unknown_syndication(self):
        rows = [SearchResult('Xiaomi earnings', 'Xiaomi profit news', url, source)
                for url, source in [
                    ('https://finance.sina.com.cn/a', '新浪'),
                    ('https://news.futunn.com/post/1', '财联社'),
                    ('https://news.futunn.com/post/2', '快讯'),
                    ('https://www.ft.com/content/test', 'Financial Times'),
                    ('https://www.reuters.com/business/test', 'Reuters'),
                ]]
        response = SearchResponse('Xiaomi', rows, 'test')
        for code in ('HK01810', '01810.HK', '1810.HK', '01810'):
            with self.subTest(code=code):
                ranked = SearchService._rank_news_response(response, stock_code=code, stock_name='小米集团',
                    prefer_chinese=False, max_results=10, log_scope='test')
                self.assertEqual({r.source for r in ranked.results}, {'Financial Times', 'Reuters'})

    def test_us_stock_sources_are_not_changed_by_hk_policy(self):
        result = SearchResult('Apple earnings', 'Apple profit news', 'https://finance.sina.com.cn/a', '新浪')
        ranked = SearchService._rank_news_response(SearchResponse('Apple', [result], 'test'), stock_code='AAPL',
            stock_name='Apple', prefer_chinese=False, max_results=10, log_scope='test')
        self.assertEqual(len(ranked.results), 1)


if __name__ == '__main__':
    unittest.main()
