from scripts.dsa_production_hk_sources_v1 import URLS
def test_four_required_authority_sources_are_frozen():
    assert set(URLS)=={'sse-list.json','szse-list.json','szse-list.xlsx','hkex-securities.xlsx'}
    assert 'sse.com.cn' in URLS['sse-list.json']
    assert 'szse.cn' in URLS['szse-list.json']
    assert 'hkex.com.hk' in URLS['hkex-securities.xlsx']
