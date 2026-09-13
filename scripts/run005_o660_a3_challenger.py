"""Freeze the premarket Run005 A3_NO_VOLATILITY O660 Challenger ranking.

Uses the exact Run004 O660 universe, native database and strict integrity denominator,
but removes only `realized_vol20_ann_pct` from each model fact set. The Champion is
not modified or replaced. No future outcome data is read or persisted.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts import run004_pool_safe_deepseek as base
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope

CHALLENGER_ID = "RUN005_A3_NO_VOLATILITY_OOS_CHALLENGER_V1"
OMITTED = {"realized_vol20_ann_pct"}


def execute(args, post_json=base._post_json):
    out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
    universe,integrity,members,coverage,db_hash=base.load_inputs(args.db,args.universe,args.integrity,args.target,args.track)
    universe_hash=base.file_sha256(args.universe); integrity_hash=base.file_sha256(args.integrity)
    candidates=[]; isolated=[]
    for code in members:
        row=coverage[code]
        if row.get('status')!='passed_21_observed_daily_bars':
            isolated.append({'code':code,'reason':'b1_'+str(row.get('reason') or 'isolated')}); continue
        try:
            facts=base.technical_features(args.db,code,args.target)
            facts={k:v for k,v in facts.items() if k not in OMITTED}
            if 'realized_vol20_ann_pct' in facts: raise AssertionError('volatility_feature_leak')
            candidates.append((code,facts))
        except Exception as exc:
            isolated.append({'code':code,'reason':'feature_gate:'+type(exc).__name__})
    input_projection=[{'code':c,'features':f,'feature_sha256':canonical_hash(f)} for c,f in candidates]
    input_hash=canonical_hash(input_projection)
    config={
      'challenger_id':CHALLENGER_ID,'base_model_contract':'RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1',
      'omitted_fields':sorted(OMITTED),'model':args.model,'max_tokens':base.MAX_OUTPUT_TOKENS,
      'temperature':0,'thinking':'disabled','response_format':'json_object','max_requests':args.max_requests,'max_cny':args.max_cny,
      'reason_codes':sorted(base.REASON_CODES),
    }
    config_hash=canonical_hash(config)
    api_key=os.getenv('DEEPSEEK_API_KEY')
    if not api_key and not args.dry_run: raise RuntimeError('missing_deepseek_api_key')
    safe=[]; requests=0; cost_total=0.0; usage_total={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
    started=datetime.now(timezone.utc).isoformat()
    for code,facts in candidates:
        body=base.request_object(args.model,facts); reserve=base.conservative_request_reserve_cny(body)
        if requests>=args.max_requests:
            isolated.append({'code':code,'reason':'request_limit'}); continue
        if cost_total+reserve>args.max_cny:
            isolated.append({'code':code,'reason':'budget_guard'}); continue
        if args.dry_run:
            result={'score':50,'stance':'neutral','confidence':'low','reason_codes':['insufficient_edge']}; response_model=args.model
            usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}; cost=0.0
        else:
            requests+=1
            try:
                provider=post_json(base.API_URL,body,api_key)
                result,response_model,usage=base.parse_provider_response(provider)
            except Exception as exc:
                isolated.append({'code':code,'reason':'model_failure:'+str(exc)[:80]}); cost_total+=reserve; continue
            cost=base.usage_peak_cost_cny(usage)
            if cost<=0: cost=reserve
        cost_total+=cost
        for k in usage_total: usage_total[k]+=int((usage or {}).get(k) or 0)
        row={'code':code,'score':result['score'],'stance':result['stance'],'confidence':result['confidence'],'reason_codes':result['reason_codes'],'feature_sha256':canonical_hash(facts),'model':response_model or args.model,'usage':{k:int((usage or {}).get(k) or 0) for k in usage_total},'peak_cost_estimate_cny':round(cost,8)}
        row['result_sha256']=canonical_hash({k:row[k] for k in ('code','score','stance','confidence','reason_codes','feature_sha256','model')})
        safe.append(row)
    safe.sort(key=lambda r:(-r['score'],r['code'])); ranked=[dict(r,rank=i+1) for i,r in enumerate(safe)]; isolated.sort(key=lambda r:r['code'])
    env=build_ranking_envelope(members,ranked,isolated,as_of=args.target,claimed_scope='partial_with_isolations' if isolated else 'full_pool_complete')
    ranking_sha=canonical_hash([{'code':r['code'],'rank':r['rank'],'score':r['score'],'result_sha256':r['result_sha256']} for r in ranked])
    payload_sha=canonical_hash({'ranked':ranked,'isolated':isolated,'envelope':env})
    finished=datetime.now(timezone.utc).isoformat()
    package={
      'schema_version':1,'run_id':args.run_id,'challenger_id':CHALLENGER_ID,'status':'LIVE_OOS_CHALLENGER_FROZEN_BEFORE_MARKET_OUTCOME',
      'generated_at':finished,'as_of':args.target,'track':args.track,'model':args.model,'universe_id':universe.get('universe_id'),
      'denominator':len(members),'ranked_count':len(ranked),'isolated_count':len(isolated),'model_http_requests':requests,
      'omitted_fields':sorted(OMITTED),'ranked':ranked,'isolated':isolated,'ranking_envelope':env,
      'hashes':{'database_sha256':db_hash,'universe_file_sha256':universe_hash,'integrity_file_sha256':integrity_hash,'input_sha256':input_hash,'config_sha256':config_hash,'prediction_payload_sha256':payload_sha,'ranking_sha256':ranking_sha},
      'usage':usage_total,'cost':{'basis':'peak price estimate; not actual invoice','estimated_peak_cny':round(cost_total,8),'actual_cny':None,'hard_cap_cny':args.max_cny},
      'privacy':{'raw_provider_response_saved':False,'prompt_saved':False,'reasoning_saved':False},'outcome_data_read':False,'champion_replaced':False,'started_at':started,
    }
    p=out/'a3-o660-challenger.json'; p.write_text(json.dumps(package,ensure_ascii=False,indent=2))
    record={'run_id':args.run_id,'generated_at':finished,'as_of':args.target+'T16:00:00+08:00','universe_sha256':universe_hash,'input_sha256':input_hash,'model_version':args.model,'config_sha256':config_hash,'prediction_payload_sha256':payload_sha,'ranking_sha256':ranking_sha,'status':'LIVE_OOS_CHALLENGER_FROZEN_BEFORE_MARKET_OUTCOME'}
    ledger=freeze_prediction(out/'prediction-ledger',record)
    manifest={'run_id':args.run_id,'challenger_id':CHALLENGER_ID,'ranking_sha256':ranking_sha,'prediction_file_sha256':base.file_sha256(p),'ledger_file':ledger.name,'ledger_file_sha256':base.file_sha256(ledger),'denominator':len(members),'ranked_count':len(ranked),'isolated_count':len(isolated),'model_http_requests':requests,'estimated_peak_cny':round(cost_total,8),'outcome_data_read':False,'champion_replaced':False}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('RUN005_A3_O660_CHALLENGER_FROZEN',json.dumps(manifest,separators=(',',':')))
    return package


def parser():
    p=argparse.ArgumentParser(); p.add_argument('--db',required=True); p.add_argument('--universe',required=True); p.add_argument('--integrity',required=True); p.add_argument('--output',required=True); p.add_argument('--target',default='2026-09-11'); p.add_argument('--track',default='O'); p.add_argument('--model',default='deepseek-v4-flash'); p.add_argument('--run-id',required=True); p.add_argument('--max-requests',type=int,default=407); p.add_argument('--max-cny',type=float,default=3.0); p.add_argument('--dry-run',action='store_true'); return p

if __name__=='__main__': execute(parser().parse_args())
