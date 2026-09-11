from src.services.market_data_integrity import company_news_matches


def test_market_tag_is_not_company_evidence():
    item = dict(title='其他港股公司发布公告', summary='', scope_type='market', market='hk',
                published_at='2026-09-11', url='https://example.com/news')
    assert not company_news_matches(item, 'HK01810', '小米集团-W')
    item['title'] = '小米集团发布公告'
    assert company_news_matches(item, 'HK01810', '小米集团-W')
    item['published_at'] = None
    assert not company_news_matches(item, 'HK01810', '小米集团-W')


def test_reviewed_symbol_evidence_requires_matching_company():
    item = dict(scope_type='symbol', scope_value='1810.HK', title='Reviewed company event',
                published_at='2026-09-11', url='https://example.com/news')
    assert company_news_matches(item, 'HK01810', '小米集团-W')
    item['scope_value'] = '0700.HK'
    assert not company_news_matches(item, 'HK01810', '小米集团-W')
