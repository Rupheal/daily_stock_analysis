#!/usr/bin/env python3
"""Build a deterministic U45 preparation ledger from frozen universe + data-only coverage.
No model calls. PREP_READY is intentionally strict and never means formal acceptance.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--universe',required=True);ap.add_argument('--coverage',required=True);ap.add_argument('--out',required=True);ap.add_argument('--target',required=True);args=ap.parse_args()
    u=load(args.universe); c=load(args.coverage); cov={str(x['code']).lower().replace('hk',''):x for x in c.get('coverage',[])}
    assert u.get('member_count')==45 and len(u.get('members',[]))==45
    rows=[]
    for m in u['members']:
        code=m['code']; r=cov.get(code.lower(),{}); ident=bool(m.get('identity_verified')); price=r.get('status')=='current_valid_bar'; vol=price and len(r.get('latest_ohlcv') or [])==5 and (r.get('latest_ohlcv')[-1] is not None)
        executable='not_in_verified_current_southbound_buy_sell_union' not in str(m.get('execution_eligibility',''))
        news=False
        if not ident: status='IDENTITY_BLOCKED'; reason='identity_not_verified'
        elif not executable: status='OTHER_EXPLICIT_REASON'; reason='retained_in_U45_but_not_currently_executable'
        elif not price: status='DATA_BLOCKED'; reason='fresh_target_session_price_not_current_or_missing'
        elif not vol: status='DATA_BLOCKED'; reason='fresh_target_session_volume_not_verified'
        elif not news: status='DATA_BLOCKED'; reason='fresh_per_stock_news_coverage_not_yet_verified'
        else: status='PREP_READY'; reason=None
        rows.append({'code':code,'name':m.get('official_name') or m.get('user_alias'),'identity_ready':ident,'exchange_code_mapping':'HK'+code,'current_session_target':args.target,'price_ready':price,'ohlc_ready':price,'volume_ready':vol,'latest_session_fresh':price,'provider_disagreement':'NOT_VERIFIED_IN_THIS_U45_DATA_ONLY_PASS','fallback_available':'NOT_VERIFIED','news_ready':news,'source_provenance':{'identity':'docs/dsa-u-universe.json','price_volume':'frozen-native data-only coverage'},'official_current_membership':m.get('official_current_membership'),'execution_eligible':executable,'missing_reason':reason,'quality_flag':status,'deterministic_preflight_status':status})
    summary={'Universe':'45/45','Identity Ready':f"{sum(x['identity_ready'] for x in rows)}/45",'Price Ready':f"{sum(x['price_ready'] for x in rows)}/45",'Volume Ready':f"{sum(x['volume_ready'] for x in rows)}/45",'News Ready':f"{sum(x['news_ready'] for x in rows)}/45",'Full Preflight Ready':f"{sum(x['deterministic_preflight_status']=='PREP_READY' for x in rows)}/45",'Blocked':f"{sum(x['deterministic_preflight_status']!='PREP_READY' for x in rows)}/45",'Formal Accepted':'0/45'}
    out={'schema_version':'U45_PREP_LEDGER_v1','generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'universe_id':u.get('universe_id'),'target_session':args.target,'denominator':45,'formal_acceptance_denominator':45,'formal_accepted':0,'prep_is_not_formal_acceptance':True,'summary':summary,'members':rows}
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
