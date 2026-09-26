"""Synthetic candidate statistics; no calibrated model or market evidence."""
import copy,json
from pathlib import Path
import pytest
from scripts.dsa_u_observable_candidate_v1 import evaluate


def fixture():
    c=json.loads((Path(__file__).resolve().parents[1]/'docs/runtime/dsa-u-observable-input-contract-v1.json').read_bytes())
    fields=[r for rows in c['engines'].values() for r in rows if r['candidate_required']]
    rows=[{'field':r['id'],'unit':r['unit'],'value':1,'evidence_class':r['evidence_class'],
        'source':{'url':'https://example.test/synthetic','sha256':'a'*64},'derivation_inputs':['synthetic-hash'],
        'event_time':'2026-09-24T08:00:00+08:00','published_at':'2026-09-24T08:10:00+08:00',
        'available_at':'2026-09-24T08:11:00+08:00','observed_at':'2026-09-24T08:12:00+08:00'} for r in fields]
    cfg={'status':'RESEARCH_ONLY_NOT_AUTHORITY','training_end':'2026-09-22T00:00:00+08:00',
         'frozen_at':'2026-09-23T00:00:00+08:00','training_dataset_sha256':'b'*64,'training_receipt_sha256':'c'*64,
         'weights':dict.fromkeys('ABCDEFG',1/7),'max_age_seconds':{r['id']:3600 for r in fields},
         'normalization':{r['id']:{'mean':0,'std':1,'direction':1} for r in fields}}
    return {'cutoff':'2026-09-24T09:00:00+08:00','observations':rows},c,cfg


def test_comparison_is_only_research_and_ablation(tmp_path):
    d,c,cfg=fixture();r=evaluate(d,c,cfg)
    assert r['state']=='RESEARCH_SCORES_AVAILABLE'
    assert r['comparison']['equal_weight_baseline']==1
    assert len(r['comparison']['leave_one_engine_out'])==7
    assert r['position_ceiling_pct'] is None and r['formal_authority'] is False
    assert r['real_cycle_credit']==0

@pytest.mark.parametrize('case',['missing','future','stale','unit','inference','nan','lineage'])
def test_bad_observation_abstains_without_zero_imputation(case):
    d,c,cfg=fixture();row=d['observations'][0]
    if case=='missing':d['observations'].pop(0)
    if case=='future':row['observed_at']='2026-09-24T09:01:00+08:00'
    if case=='stale':cfg['max_age_seconds'][row['field']]=1
    if case=='unit':row['unit']='unknown'
    if case=='inference':row['evidence_class']='inference'
    if case=='nan':row['value']=float('nan')
    if case=='lineage':row['evidence_class']='derived_verified';del row['derivation_inputs']
    r=evaluate(d,c,cfg)
    assert r['state']=='ABSTAIN_INCOMPLETE_OBSERVATIONS' and r['comparison'] is None
    assert r['engine_scores']['A'] is None

@pytest.mark.parametrize('case',['training','weights','duplicate'])
def test_invalid_experiment_rejected(case):
    d,c,cfg=fixture()
    if case=='training':cfg['training_end']='2026-09-25T00:00:00+08:00'
    if case=='weights':cfg['weights']['A']=1
    if case=='duplicate':d['observations'].append(copy.deepcopy(d['observations'][0]))
    with pytest.raises(ValueError):evaluate(d,c,cfg)
