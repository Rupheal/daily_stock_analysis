import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'DSA_DASHBOARD_LIVE_V019.schema.json').read_text(encoding='utf-8'))
FEED=json.loads((ROOT/'DSA_DASHBOARD_LIVE_V019.json').read_text(encoding='utf-8'))
HTML=(ROOT/'DSA_Dashboard_v0.19_Live_UI.html').read_text(encoding='utf-8')

spec=importlib.util.spec_from_file_location('dashboard_v019', ROOT/'scripts/dashboard_feed_generator_v019.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def req(cond,msg):
    if not cond:
        raise AssertionError(msg)

def test_schema_top_level():
    req(set(SCHEMA['required']) <= set(FEED), 'missing top-level')

def test_authority_required():
    req('authority' in SCHEMA['required'], 'authority')

def test_u_denominator():
    req(FEED['U']['denominator']==45, 'U denominator')

def test_data_vs_formal_are_distinct():
    req(FEED['O']['data_ready']==657 and FEED['O']['accepted']==0, 'O readiness/formal')
    req(FEED['U']['data_ready']==45 and FEED['U']['accepted']==0, 'U readiness/formal')

def test_coverage_invariants():
    req(FEED['O']['data_ready']+FEED['O']['data_isolated']==FEED['O']['denominator'], 'O coverage')
    req(FEED['U']['data_ready']+FEED['U']['data_isolated']==FEED['U']['denominator'], 'U coverage')

def test_run060_authority():
    req(FEED['authority']['source_receipt']=='docs/runtime/RUN060_RECOVERED_RESULT.json', 'Run060 receipt')
    req(FEED['authority']['evidence_session']=='2026-09-18', 'session')

def test_wait_is_not_buy():
    req(FEED['system']['overall_state']=='WAIT', 'WAIT state')
    req(FEED['O']['qualified_buy'] is False and FEED['U']['qualified_buy'] is False, 'no qualified buy')
    req(FEED['simulation']['pending_signal']=='WAIT', 'sim WAIT')

def test_zero_model_usage():
    req(FEED['budget']['actual_request_count']==0, 'request count')
    req(FEED['budget']['cost']==0, 'cost')

def test_ui_uses_v019_canonical_feed():
    req(HTML.count('DSA_DASHBOARD_LIVE_V019.json')==1, 'v019 feed URL')
    req('research/dsa-dashboard-v019-20260918' in HTML, 'branch URL')

def test_ui_requires_authority():
    req('f.authority' in HTML and 'authorityReceipt' in HTML and 'authoritySession' in HTML, 'authority UI')

def test_ui_separates_data_and_formal():
    req('O DATA READY' in HTML and 'U DATA READY' in HTML, 'data cards')
    req('O FORMAL' in HTML and 'U FORMAL' in HTML, 'formal cards')

def test_no_direct_actions_api():
    req('api.github.com/repos/' not in HTML, 'direct Actions API')

def test_no_private_raw_or_secrets():
    text=json.dumps(FEED).lower()
    req('raw request' not in text and 'raw response' not in text, 'raw content')
    req(not re.search(r'(?i)(api[_-]?key|client_secret|refresh_token|bearer\s+\S+)', json.dumps(FEED)), 'secret')

def test_generator_discovers_latest_compatible_receipt():
    f=mod.build_feed(ROOT, 'TESTSHA', '2026-09-18T13:30:00Z')
    req(f['authority']['source_receipt'].endswith('RUN060_RECOVERED_RESULT.json'), 'latest compatible receipt')
    req(f['O']['data_ready']==657 and f['O']['data_isolated']==3, 'generated O')
    req(f['U']['data_ready']==45 and f['U']['buy_eligible']==44, 'generated U')
    req(f['authority']['source_receipt_sha256']!='SHA256_DERIVED_AT_GENERATION', 'real receipt sha')

def test_generator_keeps_strategy_gate_closed():
    f=mod.build_feed(ROOT, 'TESTSHA', '2026-09-18T13:30:00Z')
    req(f['authority']['strategy_acceptance']=='NONE_FORMAL_SIGNAL_GENERATED_FALSE', 'strategy boundary')
    req(f['simulation']['eligibility']=='WAIT_NOT_ELIGIBLE_NO_FORMAL_SIGNAL', 'simulation gate')

def test_old_v018_feed_not_fetched():
    req('/DSA_DASHBOARD_LIVE.json' not in HTML, 'old live feed URL')

def test_debug_has_authority():
    req('AUTHORITY:f.authority' in HTML, 'authority debug')
