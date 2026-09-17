#!/usr/bin/env python3
"""Build a deterministic U45 preparation ledger from frozen universe + data-only coverage.
No model calls. PREP_READY is intentionally strict and never means formal acceptance.
"""
from __future__ import annotations
import argparse,json,hashlib,re
from datetime import datetime,timezone
from pathlib import Path

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def reviewed_news_ready(code, target, reviews, evidence_sha256, decision_at):
    """Consume reviewed source evidence; parsed RSS alone never grants readiness."""
    if not isinstance(evidence_sha256,str) or not re.fullmatch('[0-9a-f]{64}',evidence_sha256):return False
    if not reviews or reviews.get('target_session')!=target or reviews.get('source_evidence_sha256')!=evidence_sha256:
        return False
    row=next((r for r in reviews.get('members',[]) if r.get('code')==code),None)
    if not row or row.get('status')!='PASS_REVIEWED_COVERAGE' or not row.get('reviewer'):
        return False
    try:
        reviewed=datetime.fromisoformat(row['reviewed_at']);decision=datetime.fromisoformat(decision_at)
        if reviewed.tzinfo is None or decision.tzinfo is None or reviewed>decision:return False
        sources=row['sources']
        if not sources or not row.get('limitations_disclosed'):return False
        for x in sources:
            at=datetime.fromisoformat(x['available_at'])
            if at.tzinfo is None or at>decision or not str(x['url']).startswith('https://') or not re.fullmatch('[0-9a-f]{64}',x['sha256']):return False
        return row.get('company_identity_verified') is True and row.get('facts_opinions_separated') is True and row.get('deduplicated') is True
    except (KeyError,TypeError,ValueError):return False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--universe',required=True);ap.add_argument('--coverage',required=True);ap.add_argument('--out',required=True);ap.add_argument('--target',required=True);ap.add_argument('--news-review');ap.add_argument('--news-evidence');ap.add_argument('--decision-at');args=ap.parse_args()
    u=load(args.universe); c=load(args.coverage); cov={str(x['code']).lower().replace('hk',''):x for x in c.get('coverage',[])}
    assert u.get('member_count')==45 and len(u.get('members',[]))==45
    reviews=load(args.news_review) if args.news_review else {}
    evidence_hash=hashlib.sha256(Path(args.news_evidence).read_bytes()).hexdigest() if args.news_evidence else None
    rows=[]
    for m in u['members']:
        code=m['code']; r=cov.get(code.lower(),{}); ident=bool(m.get('identity_verified')); price=r.get('status')=='current_valid_bar' and r.get('latest_date')==args.target; vol=price and len(r.get('latest_ohlcv') or [])==5 and (r.get('latest_ohlcv')[-1] is not None)
        executable='not_in_verified_current_southbound_buy_sell_union' not in str(m.get('execution_eligibility',''))
        news=reviewed_news_ready(code,args.target,reviews,evidence_hash,args.decision_at)
        if not ident: status='IDENTITY_BLOCKED'; reason='identity_not_verified'
        elif not executable: status='OTHER_EXPLICIT_REASON'; reason='retained_in_U45_but_not_currently_executable'
        elif not price: status='DATA_BLOCKED'; reason='fresh_target_session_price_not_current_or_missing'
        elif not vol: status='DATA_BLOCKED'; reason='fresh_target_session_volume_not_verified'
        elif not news: status='DATA_BLOCKED'; reason='fresh_per_stock_news_coverage_not_yet_verified'
        else: status='PREP_READY'; reason=None
        rows.append({'code':code,'name':m.get('official_name') or m.get('user_alias'),'identity_ready':ident,'exchange_code_mapping':'HK'+code,'current_session_target':args.target,'price_ready':price,'ohlc_ready':price,'volume_ready':vol,'latest_session_fresh':price,'provider_disagreement':'NOT_VERIFIED_IN_THIS_U45_DATA_ONLY_PASS','fallback_available':'NOT_VERIFIED','news_ready':news,'source_provenance':{'identity':'docs/dsa-u-universe.json','price_volume':'frozen-native data-only coverage','news_review':args.news_review,'news_evidence_sha256':evidence_hash},'official_current_membership':m.get('official_current_membership'),'execution_eligible':executable,'missing_reason':reason,'quality_flag':status,'deterministic_preflight_status':status})
    summary={'Universe':'45/45','Identity Ready':f"{sum(x['identity_ready'] for x in rows)}/45",'Price Ready':f"{sum(x['price_ready'] for x in rows)}/45",'Volume Ready':f"{sum(x['volume_ready'] for x in rows)}/45",'News Ready':f"{sum(x['news_ready'] for x in rows)}/45",'Full Preflight Ready':f"{sum(x['deterministic_preflight_status']=='PREP_READY' for x in rows)}/45",'Blocked':f"{sum(x['deterministic_preflight_status']!='PREP_READY' for x in rows)}/45",'Formal Accepted':'0/45'}
    out={'schema_version':'U45_PREP_LEDGER_v1','generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'universe_id':u.get('universe_id'),'target_session':args.target,'denominator':45,'formal_acceptance_denominator':45,'formal_accepted':0,'prep_is_not_formal_acceptance':True,'summary':summary,'members':rows}
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
