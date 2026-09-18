import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from aggregate_o_formal_ranking_v3 import aggregate

def base():
    universe={'members':[
      {'code':'00001','official_name':'A'},
      {'code':'00002','official_name':'B'},
      {'code':'00003','official_name':'C'},
      {'code':'00004','official_name':'D'},
      {'code':'00005','official_name':'E'},
      {'code':'00006','official_name':'F'},
    ]}
    policy={'current_session':{'session':'2026-09-18','official_denominator':6,'operational_denominator':5,
      'excluded_unresolved':[{'code':'00006'}]}}
    return universe,policy

def row(code,score,action='watch',eligible=True,status='CORE_ACCEPTED'):
    return {'code':code,'status':status,'ranking_eligible':eligible,
      'strategy_core':{'sentiment_score':score,'action':action,'decision_type':'hold',
                       'action_family':'buy' if action=='buy' else 'hold'},
      'strategy_core_sha256':'a'*64,'raw_result_sha256':'b'*64,
      'narrative_release_status':'QUARANTINED'}

def test_complete_ranking_and_stable_tie():
    u,p=base()
    src={'members':[row('00001',50),row('00002',70,'buy'),row('00003',70,'buy'),row('00004',60),row('00005',40)]}
    o=aggregate(u,p,[('s',src)])
    assert o['state']=='PASS_O_FORMAL_CORE_RANKING_TOP3'
    assert [x['code'] for x in o['Top3']]==['00002','00003','00004']
    assert o['qualified_buy_in_Top3']==2
    assert o['ranking_eligible_count']==5
    assert o['formal_signal_generated'] is False

def test_narrative_quarantine_does_not_exclude():
    u,p=base();src={'members':[row(f'0000{i}',50+i) for i in range(1,6)]}
    o=aggregate(u,p,[('s',src)])
    assert o['ranking_eligible_count']==5
    assert all(x['narrative_release_status']=='QUARANTINED' for x in o['Top3'])

def test_core_reject_is_explicit_exclusion_not_missing():
    u,p=base()
    rows=[row('00001',70),row('00002',60),row('00003',50),row('00004',40),
          {'code':'00005','status':'CORE_REJECTED_NO_RETRY','ranking_eligible':False,'failure_code':'HARD'}]
    o=aggregate(u,p,[('s',{'members':rows})])
    assert o['state']=='PASS_O_FORMAL_CORE_RANKING_TOP3'
    assert o['additional_excluded_count']==1
    assert o['missing_count']==0

def test_missing_prevents_formal_completion():
    u,p=base();src={'members':[row('00001',70),row('00002',60),row('00003',50)]}
    o=aggregate(u,p,[('s',src)])
    assert o['state']=='PARTIAL_O_FORMAL_CORE_PROCESSING'
    assert o['missing_count']==2
    assert o['formal_O_ranking_generated'] is False

def test_duplicate_code_fails():
    import pytest
    u,p=base()
    with pytest.raises(ValueError,match='DUPLICATE'):
        aggregate(u,p,[('a',{'members':[row('00001',60)]}),('b',{'members':[row('00001',61)]})])

def test_base_excluded_row_fails():
    import pytest
    u,p=base()
    with pytest.raises(ValueError,match='BASE_EXCLUDED'):
        aggregate(u,p,[('a',{'members':[row('00006',60)]})])

def test_shared_unprocessed_blocks_closure_and_is_not_exclusion():
    u,p=base()
    rows=[row('00001',70),row('00002',60),row('00003',50),
          {'code':'00004','status':'SHARED_FAILURE_UNPROCESSED','ranking_eligible':False,'failure_code':'DRIVE'},
          {'code':'00005','status':'SKIPPED_AFTER_SHARED_STOP','ranking_eligible':False,'failure_code':'SHARED_STOP'}]
    o=aggregate(u,p,[('s',{'members':rows})])
    assert o['state']=='PARTIAL_O_FORMAL_CORE_PROCESSING'
    assert o['missing_count']==2
    assert o['shared_unprocessed_count']==2
    assert o['additional_excluded_count']==0

def test_prior_formal_ranking_can_feed_continuation_without_missing_rows():
    u,p=base()
    prior={
      'ranking':[
        {'code':'00001','sentiment_score':70,'action':'buy','decision_type':'buy','action_family':'buy',
         'strategy_core_sha256':'a'*64,'raw_result_sha256':'b'*64,'provider_response_sha256':'c'*64,
         'narrative_release_status':'QUARANTINED'},
        {'code':'00002','sentiment_score':60,'action':'buy','decision_type':'buy','action_family':'buy',
         'strategy_core_sha256':'d'*64,'raw_result_sha256':'e'*64,'provider_response_sha256':'f'*64,
         'narrative_release_status':'QUARANTINED'},
      ],
      'additional_exclusions':[
        {'code':'00003','status':'EXCLUDED_PREFLIGHT_NO_RESCUE','failure_code':'DATA'}
      ]
    }
    continuation={'members':[row('00004',50),row('00005',40)]}
    o=aggregate(u,p,[('prior',prior),('new',continuation)])
    assert o['state']=='PASS_O_FORMAL_CORE_RANKING_TOP3'
    assert o['missing_count']==0
    assert o['ranking_eligible_count']==4
    assert o['additional_excluded_count']==1
    assert [x['code'] for x in o['Top3']]==['00001','00002','00004']

def test_proven_unsent_nameerror_is_missing_not_excluded():
    u,p=base()
    rows=[
      row('00001',70),row('00002',60),row('00003',50),row('00004',40),
      {'code':'00005','status':'EXCLUDED_AFTER_CLAIM_NO_RETRY','ranking_eligible':False,
       'failure_code':'NameError','claim_persisted':True,
       'model_http_requests_confirmed':0,'model_http_requests_possible':1,
       'provider_response_sha256':None}
    ]
    o=aggregate(u,p,[('s',{'members':rows})])
    assert o['state']=='PARTIAL_O_FORMAL_CORE_PROCESSING'
    assert o['missing_operational_members']==['00005']
    assert o['shared_unprocessed_count']==1
    assert o['shared_unprocessed'][0]['status']=='PROVEN_UNSENT_RUNNER_BUG'
    assert o['additional_excluded_count']==0
