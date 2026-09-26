"""Offline U research comparison. No capital caps, regime decisions or orders.

Supplied normalization/weight configuration is a frozen research candidate,
never formal Authority. No fitting, market-data retrieval or inferred flow IDs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path


def time(value):
    x=datetime.fromisoformat(value.replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('NAIVE_PIT_TIME')
    return x

def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('NONFINITE_NUMBER')
    return float(value)

def evaluate(data,contract,config):
    cutoff=time(data['cutoff']);errors={};scores={}
    if set(contract.get('engines',{}))!=set('ABCDEFG'):raise ValueError('SEVEN_ENGINES_REQUIRED')
    if contract.get('status')!='RESEARCH_ONLY_NOT_AUTHORITY' or config.get('status')!='RESEARCH_ONLY_NOT_AUTHORITY':raise ValueError('RESEARCH_CONFIG_REQUIRED')
    if not time(config['training_end'])<=time(config['frozen_at'])<cutoff:raise ValueError('TRAINING_OR_FREEZE_LEAKAGE')
    for field in ('training_dataset_sha256','training_receipt_sha256'):
        value=config.get(field,'')
        if len(value)!=64 or any(x not in '0123456789abcdef' for x in value):raise ValueError('TRAINING_PROVENANCE_REQUIRED')
    by={}
    for row in data['observations']:
        if row['field'] in by:raise ValueError('DUPLICATE_OBSERVATION')
        by[row['field']]=row
    defined={f['id'] for fields in contract['engines'].values() for f in fields}
    if sum(len(v) for v in contract['engines'].values())!=len(defined):raise ValueError('DUPLICATE_CONTRACT_FIELD')
    if set(by)-defined:raise ValueError('UNKNOWN_INPUT_FIELD')
    weights=config['weights']
    if set(weights)!=set('ABCDEFG') or any(number(v)<0 for v in weights.values()) or abs(sum(weights.values())-1)>1e-8:raise ValueError('WEIGHTS_MUST_SUM_TO_ONE')
    for engine,fields in contract['engines'].items():
        values=[];missing=[]
        for spec in fields:
            key=spec['id'];row=by.get(key)
            if not spec['candidate_required']:continue
            if not row:missing.append(key+':MISSING');continue
            try:
                if row.get('evidence_class') not in ('direct','derived_verified'):raise ValueError('NOT_OBSERVABLE')
                if row.get('unit')!=spec['unit']:raise ValueError('UNIT_MISMATCH')
                source=row['source'];hashval=source['sha256']
                if len(hashval)!=64 or any(c not in '0123456789abcdef' for c in hashval) or not source.get('url','').startswith('https://'):raise ValueError('SOURCE_REFERENCE_MISSING')
                available=time(row['available_at']);published=time(row['published_at']);observed=time(row['observed_at'])
                event=time(row['event_time'])
                if not event<=published<=available<=observed<=cutoff:raise ValueError('PIT_ORDER_OR_FUTURE')
                age=number(config['max_age_seconds'][key])
                if age<0 or (cutoff-available).total_seconds()>age:raise ValueError('STALE')
                if row['evidence_class']=='derived_verified' and not row.get('derivation_inputs'):raise ValueError('DERIVATION_LINEAGE_MISSING')
                norm=config['normalization'][key]
                mu,sd=number(norm['mean']),number(norm['std'])
                if sd<=0 or (type(norm['direction']) is not int or norm['direction'] not in (-1,1)):raise ValueError('NORMALIZATION_INVALID')
                values.append(norm['direction']*(number(row['value'])-mu)/sd)
            except (KeyError,TypeError,ValueError) as exc:
                missing.append(key+':'+str(exc))
        errors[engine]=missing
        scores[engine]=sum(values)/len(values) if values and not missing else None
    complete=all(scores[k] is not None for k in 'ABCDEFG')
    comparison=None
    if complete:
        comparison={'equal_weight_baseline':sum(scores.values())/7,
                    'frozen_weight_candidate':sum(weights[k]*scores[k] for k in 'ABCDEFG'),
                    'leave_one_engine_out':{k:sum(scores[j] for j in 'ABCDEFG' if j!=k)/6 for k in 'ABCDEFG'}}
    return {'state':'RESEARCH_SCORES_AVAILABLE' if complete else 'ABSTAIN_INCOMPLETE_OBSERVATIONS',
            'cutoff':data['cutoff'],'engine_scores':scores,'input_errors':errors,'comparison':comparison,
            'configuration_sha256':hashlib.sha256(json.dumps(config,sort_keys=True,allow_nan=False).encode()).hexdigest(),
            'source_authenticity_verified_by_this_tool':False,
            'training_statistics_recomputed_by_this_tool':False,
            'regime':None,'position_ceiling_pct':None,'formal_authority':False,
            'real_cycle_credit':0,'real_orders':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('input','contract','config','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=evaluate(*(json.loads(x.read_bytes()) for x in (a.input,a.contract,a.config)))
    if __package__:
        from .dsa_receipt_delivery_v1 import immutable, encode
    else:
        from dsa_receipt_delivery_v1 import immutable, encode
    immutable(a.out,encode(result));print(json.dumps({'state':result['state'],'formal_authority':False}))
if __name__=='__main__':main()
