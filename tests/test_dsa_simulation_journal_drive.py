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
