import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'docs/runtime/O_UNRESOLVED_EXCLUSION_POLICY.json').read_text(encoding='utf-8'))
NEXT=json.loads((ROOT/'docs/DSA_NEXT_ACTIONS.json').read_text(encoding='utf-8'))

def test_policy_active():
    assert POLICY['status']=='ACTIVE_USER_DIRECTIVE'
    assert POLICY['policy_id']=='DSA-O-UNRESOLVED-EXCLUSION-v1'

def test_current_reconciliation():
    cur=POLICY['current_session']
    assert cur['official_denominator']==660
    assert cur['operational_denominator']==657
    assert cur['formal_O_denominator']==657
    assert cur['excluded_count']==3
    assert cur['operational_denominator']+cur['excluded_count']==cur['official_denominator']

def test_current_three_are_excluded():
    codes=[x['code'] for x in POLICY['current_session']['excluded_unresolved']]
    assert codes==['00853','02172','02252']
    assert 'No further rescue attempts' in POLICY['current_session']['action']

def test_no_repeated_or_paid_rescue():
    op=POLICY['operational_universe']
    assert op['maximum_additional_model_free_confirmation_cycles_per_symbol_per_session']==1
    assert op['paid_model_calls_for_status_rescue']==0
    assert op['repeated_special_rescue_prohibited'] is True
    assert op['exclusion_blocks_formal_acceptance'] is False

def test_reentry_is_passive():
    assert 'normal scheduled/current-session refresh' in POLICY['operational_universe']['reentry_rule']

def test_next_actions_uses_operational_denominator():
    g4=next(x for x in NEXT['next_actions'] if x['id']=='G4')
    assert (
        'OPERATIONAL657' in g4['status']
        or 'O_FORMAL_PARTIAL_' in g4['status']
        or 'O_FORMAL_TOP3_PASS_' in g4['status']
    )
    assert g4['current_unresolved_exclusion_policy']=='docs/runtime/O_UNRESOLVED_EXCLUSION_POLICY.json'
    den=NEXT['operating_rules']['o_20260918_denominators']
    assert den['official']==660
    assert den['operational']==657
    assert den['formal_acceptance_denominator']==657
    assert g4['current_unresolved_exclusion_policy']=='docs/runtime/O_UNRESOLVED_EXCLUSION_POLICY.json'
    den=NEXT['operating_rules']['o_20260918_denominators']
    assert den['official']==660
    assert den['operational']==657
    assert den['formal_acceptance_denominator']==657

def test_boundaries_unchanged():
    b=POLICY['boundaries']
    assert b['modifies_original_O_prompt_or_scoring'] is False
    assert b['model_calls_added']==0
    assert b['schedule_changes']==0
    assert b['main_merge'] is False
    assert b['real_orders']==0
