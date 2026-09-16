import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'DSA_DASHBOARD_LIVE.schema.json').read_text(encoding='utf-8'))
FEED=json.loads((ROOT/'DSA_DASHBOARD_LIVE.json').read_text(encoding='utf-8'))
HTML=(ROOT/'DSA_Dashboard_v0.18_Live_UI.html').read_text(encoding='utf-8')

def req(cond,msg):
    if not cond: raise AssertionError(msg)

def test_schema_top_level(): req(set(SCHEMA['required'])<=set(FEED),'missing top-level')
def test_u_denominator(): req(FEED['U']['denominator']==45,'U denominator')
def test_wait_valid(): req(FEED['simulation']['pending_signal']=='WAIT','WAIT')
def test_simulation_unknown_not_zero(): req(FEED['simulation']['cash']=='NOT_VERIFIED','sim cash')
def test_tokens_consistent(): req(FEED['budget']['tokens']['total']==FEED['budget']['tokens']['input']+FEED['budget']['tokens']['output'],'tokens')
def test_cost_numeric(): req(isinstance(FEED['budget']['cost'],(int,float)),'cost')
def test_no_run018_hardcode(): req('RUN018' not in HTML,'RUN018')
def test_no_workflow52_hardcode(): req('52-o-zero-http-recovery-successor' not in HTML,'wf52')
def test_no_fixed_run_id(): req('34989320785' not in HTML,'runid')
def test_single_live_feed(): req(HTML.count('DSA_DASHBOARD_LIVE.json')==1,'feed url count')
def test_no_direct_actions_api(): req('api.github.com/repos/' not in HTML,'direct API')
def test_stale_state(): req('STALE' in HTML,'stale')
def test_offline_snapshot(): req('OFFLINE SNAPSHOT' in HTML,'offline')
def test_last_validated_preservation(): req('lastValidated' in HTML,'preserve')
def test_malformed_caught(): req('catch(e)' in HTML or 'catch(err)' in HTML,'catch')
def test_history_append_view(): req('DSA_DASHBOARD_HISTORY.json' in HTML,'history')
def test_debug_drilldown(): req('CLAIM / RECOVERY' in HTML and 'PROVIDER' in HTML,'debug')
def test_secret_scan_feed(): req(not re.search(r'(?i)(api[_-]?key|client_secret|refresh_token|bearer\s+\S+)',json.dumps(FEED)),'secret')
def test_private_raw_absent(): req('raw request' not in json.dumps(FEED).lower() and 'raw response' not in json.dumps(FEED).lower(),'raw')
def test_duplicate_dom_ids():
    ids=re.findall(r'\bid="([^"]+)"',HTML);req(len(ids)==len(set(ids)),'duplicate ids')
def test_mobile_responsive(): req('@media' in HTML,'media')
def test_desktop_layout(): req('max-width' in HTML,'desktop')
def test_v018_label(): req('v0.18' in HTML,'label')
