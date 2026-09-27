import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import dsa_simulation_journal_drive as j

def test_snapshot_name_regex():
    m=j.NAME_RE.fullmatch('DSA-DUAL-ACCOUNT-JOURNAL-C00000123-Habcdef123456.bin')
    assert m and int(m.group(1))==123 and m.group(2)=='abcdef123456'

def test_prefix_is_stable():
    assert j.PREFIX=='DSA-DUAL-ACCOUNT-JOURNAL'

def test_module_has_no_real_order_surface():
    source=(ROOT/'scripts/dsa_simulation_journal_drive.py').read_text()
    assert 'place_order(' not in source.lower()
    assert 'submit_order(' not in source.lower()
    assert 'real_orders' not in source.lower()

def test_save_contract_exposes_broker_fencing_guard():
    source=(ROOT/'scripts/dsa_simulation_journal_drive.py').read_text()
    assert 'DRIVE:DSA:SIMULATION_JOURNAL' in source
    assert 'JOURNAL_RESOURCE_GUARD_INCOMPLETE' in source

def test_transition_exact_retry_and_conflicts():
    assert j._validate_transition(2,'a'*64,2,'a'*64,'b'*64)=='IDEMPOTENT'
    with __import__('pytest').raises(j.StoreError,match='PARENT_HASH_CONFLICT'):
        j._validate_transition(3,'c'*64,2,'a'*64,'b'*64)
    with __import__('pytest').raises(j.StoreError,match='SAME_COUNT_CONFLICT'):
        j._validate_transition(2,'c'*64,2,'a'*64,'a'*64)
