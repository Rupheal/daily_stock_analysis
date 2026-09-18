import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from run_hk_o_operational_shard_v3 import select_operational_members,partition_members

def data():
    members=[{'code':f'{i:05d}','official_name':str(i),'channels':['SSE']} for i in range(1,661)]
    u={'members':members}
    p={'current_session':{'official_denominator':660,'operational_denominator':657,
      'excluded_unresolved':[{'code':'00010'},{'code':'00020'},{'code':'00030'}]}}
    return u,p

def test_select_reconciles_660_to_657():
    u,p=data();rows=select_operational_members(u,p)
    assert len(rows)==657
    assert {x['code'] for x in rows}.isdisjoint({'00010','00020','00030'})
    assert rows[0]['universe_index']==0

def test_partition_covers_once_and_preserves_order():
    u,p=data();rows=select_operational_members(u,p)
    parts=[partition_members(rows,i,16) for i in range(16)]
    flat=[x for part in parts for x in part]
    assert flat==rows
    assert len({x['code'] for x in flat})==657
    assert max(len(x) for x in parts)-min(len(x) for x in parts)<=1

def test_bad_shard_rejected():
    import pytest
    u,p=data();rows=select_operational_members(u,p)
    with pytest.raises(ValueError): partition_members(rows,16,16)

def test_operational_denominator_mismatch_rejected():
    import pytest
    u,p=data();p['current_session']['operational_denominator']=658
    with pytest.raises(ValueError,match='OPERATIONAL_DENOMINATOR'):
        select_operational_members(u,p)

def test_actual_provider_command_uses_common_base():
    source=(ROOT/'scripts/run_hk_o_operational_shard_v3.py').read_text(encoding='utf-8')
    assert '[*common,"--output"' not in source
    assert '[*common_base,"--limit-cny",str(effective_cap),"--output",str(actual)]' in source
