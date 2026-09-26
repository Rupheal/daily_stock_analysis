"""Normalized synthetic notices; these tests establish no actual membership."""
import copy,json
import pytest
from scripts.dsa_effective_membership_v1 import reconcile,sha


def fixture(tmp_path):
    (tmp_path/'notice.txt').write_text('synthetic source')
    ref={'file':'notice.txt','sha256':sha((tmp_path/'notice.txt').read_bytes()),'url':'https://example.test/notice','observed_at':'2026-09-26T09:00:00+08:00'}
    contract={'base_effective_session':'2026-09-24','list_update_date':'2026-09-24','covered_through_session':'2026-09-28',
      'baseline_evidence':ref,'coverage_evidence':ref,'service_calendar':{'source':ref,'covered_from':'2026-09-24','covered_through':'2026-09-28','sessions':['2026-09-24','2026-09-28']},'amendments':[]}
    p={'target_session':'2026-09-28','cutoff':'2026-09-26T10:00:00+08:00','channels':{'SSE':copy.deepcopy(contract),'SZSE':copy.deepcopy(contract)}}
    event={'id':'fixture-add','published_at':'2026-09-24T17:00:00+08:00','effective_rule':'NEXT_SERVICE_DAY','effective_session':'2026-09-28','source':ref,
      'changes':[{'code':'01196','action':'ADD','row':{'SECURITY_CODE':'01196','TRADE_FLAG':'1','SECURITY_TYPE':'股票','ABBR_CN':'fixture'}}]}
    p['channels']['SSE']['amendments']=[event]
    return [{'SECURITY_CODE':'00001','TRADE_FLAG':'1'}],[['证券代码','中文简称','英文简称'],['00001','fixture','fixture']],p


def test_effective_next_service_day_preserves_base(tmp_path):
    s,z,p=fixture(tmp_path);before=copy.deepcopy((s,z,p))
    a,b,r=reconcile(s,z,tmp_path,'2026-09-28',p)
    assert {x['SECURITY_CODE'] for x in a}=={'00001','01196'}
    assert not r['formal_acceptance'] and (s,z,p)==before

@pytest.mark.parametrize('case',['wrong_day','gap','duplicate','unknown','source_drift','after_cutoff','missing_channel','identity'])
def test_reconciliation_refuses_ambiguous_sources(tmp_path,case):
    s,z,p=fixture(tmp_path);e=p['channels']['SSE']['amendments'][0]
    if case=='wrong_day':e['effective_session']='2026-09-25'
    if case=='gap':p['channels']['SZSE']['covered_through_session']='2026-09-24'
    if case=='duplicate':p['channels']['SSE']['amendments'].append(copy.deepcopy(e))
    if case=='unknown':e['changes'][0]['action']='GUESS_BUYABLE'
    if case=='source_drift':(tmp_path/'notice.txt').write_text('changed')
    if case=='after_cutoff':p['cutoff']='2026-09-25T10:00:00+08:00'
    if case=='missing_channel':del p['channels']['SZSE']
    if case=='identity':e['changes'][0]={'code':'00001','action':'REPLACE_IDENTITY','before':{},'row':{}}
    with pytest.raises((ValueError,KeyError)):reconcile(s,z,tmp_path,'2026-09-28',p)

@pytest.mark.parametrize('action',['REMOVE','SELL_ONLY'])
def test_removed_channel_does_not_erase_other_channel(tmp_path,action):
    s,z,p=fixture(tmp_path);p['channels']['SSE']['amendments'][0]['changes']=[{'code':'00001','action':action}]
    a,b,r=reconcile(s,z,tmp_path,'2026-09-28',p)
    assert b[1][0]=='00001'
    assert r['excluded_or_sell_only'][0]['action']==action
    assert not a if action=='REMOVE' else a[0]['TRADE_FLAG']=='2'

def test_actual_snapshot_entry_emits_only_candidate(tmp_path,monkeypatch):
    from openpyxl import Workbook
    from scripts import dsa_daily_market_snapshot_v1 as snapshot
    import hashlib
    archive=tmp_path/'archive';archive.mkdir()
    s,z,p=fixture(archive)
    s[0].update(UPDATE_DATE='2026-09-24',SECURITY_TYPE='股票',ABBR_CN='fixture')
    (archive/'sse-list.json').write_text(json.dumps({'result':s,'pageHelp':{'total':1,'pageCount':1}}))
    (archive/'szse-list.json').write_text(json.dumps([{'metadata':{'subname':'2026-09-24','recordcount':1}}]))
    w=Workbook();sh=w.active
    for row in z:sh.append(row)
    w.save(archive/'szse-list.xlsx')
    w=Workbook();sh=w.active;sh.append(['securities']);sh.append(['Updated as at 28/09/2026'])
    sh.append(['Stock Code','Name of Securities','Category','Sub-Category','Board Lot'])
    for code in ('00001','01196'):
        row=[code,'fixture','Equity','Equity Securities',100,'ISIN']+[None]*10+['HKD'];sh.append(row)
    w.save(archive/'hkex-securities.xlsx')
    # Mock only external transport; exercise real snapshot -> freeze -> reconcile.
    class Response:
        def __init__(self,raw):self.content=raw
        def raise_for_status(self):pass
    byurl={v:(archive/k).read_bytes() for k,v in snapshot.URLS.items()}
    monkeypatch.setattr(snapshot.requests,'get',lambda url,**kwargs:Response(byurl[url]))
    for channel,name in [('SSE','sse-list.json'),('SZSE','szse-list.xlsx')]:
        p['channels'][channel]['baseline_evidence']={**p['channels'][channel]['baseline_evidence'],'file':name,'sha256':sha((archive/name).read_bytes())}
    out=tmp_path/'out';out.mkdir()
    p['source_archive']='archive'
    proof=tmp_path/'proof.json';proof.write_text(json.dumps(p))
    u=tmp_path/'u.json';u.write_text(json.dumps({'member_count':45,'members':[{'code':f'{x:05}'} for x in range(1,46)]}))
    r=snapshot.build('2026-09-28',u,out,effective_evidence=proof)
    assert r['formal_universe_available'] is False and r['candidate_O_denominator']==2
    assert not (out/'O_UNIVERSE.json').exists()
    candidate=json.loads((out/'O_UNIVERSE_CANDIDATE.json').read_text())
    assert candidate['full_union_verified'] is False
    assert candidate['identity_master']['asof_session']=='2026-09-28'
