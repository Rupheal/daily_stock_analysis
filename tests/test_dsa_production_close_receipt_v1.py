from scripts.dsa_production_close_receipt_v1 import build
def f():
    om=[{'code':f'{i:05d}'} for i in range(1,6)]
    um=[{'code':f'{i:05d}','channels':['SSE']} for i in range(1,46)]
    ou={'member_count':5,'full_union_verified':True,'effective_session':'2026-09-21','members':om}
    uu={'member_count':45,'members':um}
    oc={'expected_complete_session':'2026-09-21','coverage':[
      {'code':'hk00001','status':'current_valid_bar','bars':60,'latest_date':'2026-09-21'},
      {'code':'hk00002','status':'invalid_or_stale','bars':44,'latest_date':'2026-09-18'},
      *[{'code':f'hk{i:05d}','status':'current_valid_bar','bars':60,'latest_date':'2026-09-21'} for i in range(3,6)] ]}
    uc={'expected_complete_session':'2026-09-21','coverage':[
      {'code':f'hk{i:05d}','status':'current_valid_bar'} for i in range(1,46)]}
    return ou,uu,oc,uc
def test_dynamic_denominator_and_exclusion():
    ou,uu,oc,uc=f();r,p=build(ou,uu,oc,uc,'2026-09-21','a','b','c','d')
    assert r['official_O_denominator']==5 and r['O_current_valid']==4
    assert p['current_session']['operational_denominator']==4
    assert p['current_session']['excluded_unresolved'][0]['code']=='00002'
    assert r['U_current_valid']==45
