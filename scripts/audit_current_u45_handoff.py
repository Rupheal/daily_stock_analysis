"""Per-member U evidence audit, independent of O scores; never fabricate a signal."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(universe,official,recovery,history,news,reviews,target):
    assert universe['member_count']==len(universe['members'])==45
    codes=[x['code'] for x in universe['members']];assert len(set(codes))==45
    assert official['full_union_verified'] is True and official['member_count']==len(official['members'])==660
    assert recovery['target']==history['target_session']==reviews['target_session']==target
    assert recovery['O_denominator']==660 and recovery['U_denominator']==45
    by_official={x['code']:x for x in official['members']};by_history={x['code']:x for x in history['members']}
    by_news={x['code']:x for x in news['rows']};by_review={x['code']:x for x in reviews['members']}
    rows=[]
    for member in universe['members']:
        code=member['code'];h=by_history.get(code,{});n=by_news.get(code,{});review=by_review.get(code,{})
        eligible=code in by_official
        primary=review.get('status')=='PASS_REVIEWED_COVERAGE' and review.get('company_identity_verified') is True
        failures=[]
        if not eligible:failures.append('NOT_IN_CURRENT_OFFICIAL_BUY_UNION_RETAIN_U_DENOMINATOR')
        if code not in recovery['inputs']:failures.append('NO_CURRENT_ACCEPTED_21_SESSION_INPUT_IN_THIS_CACHE')
        if not h.get('independent_history_passed'):failures.append('FULL_NATIVE_WINDOW_STRICT_HISTORY_NOT_VERIFIED')
        if not primary:failures.append('PRIMARY_ISSUER_CONTEXT_NOT_REVIEWED_IN_THIS_HANDOFF')
        # A title hit is not an event review; a bounded repurchase is not an exhaustive risk review.
        failures.extend(['FORMAL_U_SIGNAL_ARTIFACT_MISSING','U_PLAN_AND_MACRO_CAP_ACCEPTANCE_MISSING','CURRENT_ENTRY_EXECUTION_SIDECAR_MISSING'])
        rows.append({'code':code,'name':member.get('official_name') or member['user_alias'],
                     'identity_inherited_verified':bool(member.get('identity_verified')),
                     'current_buy_eligible':eligible,'lot_from_current_official':by_official.get(code,{}).get('board_lot'),
                     'feature_input_21_ready':code in recovery['inputs'],
                     'full_native_window_independent_ready':bool(h.get('independent_history_passed')),
                     'full_native_window_bars':h.get('bars'),
                     'news_retrieval_ready':bool(n.get('retrieval_ready')),
                     'reviewed_issuer_primary_evidence':primary,'primary_review_scope':review.get('coverage_scope'),
                     'full_risk_coverage_proven':False,'formal_U_signal_accepted':False,
                     'score':None,'rank':None,'entry_plan':None,'failures':failures})
    return {'run_id':'TRI-DSA-EXEC-20260917-038','track':'U','U_denominator':45,'audited_members':len(rows),
            'official_eligibility_asof':official['effective_session'],'target_session':target,
            'identity_ready':sum(x['identity_inherited_verified'] for x in rows),
            'buy_eligible':sum(x['current_buy_eligible'] for x in rows),
            'feature_input_21_ready':sum(x['feature_input_21_ready'] for x in rows),
            'strict_full_history_ready':sum(x['full_native_window_independent_ready'] for x in rows),
            'news_retrieval_ready':sum(x['news_retrieval_ready'] for x in rows),
            'bounded_primary_reviewed':sum(x['reviewed_issuer_primary_evidence'] for x in rows),
            'formal_U_accepted':0,'failure_counts':dict(Counter(y for x in rows for y in x['failures'])),
            'Top3':[],'Top10':[],'rows':rows,'model_calls':0,'fee_cny':'0','runtime_authorization_is_not_a_data_gate':True,
            'scope':'Real current per-member handoff readiness; neither a prediction nor a strategy promotion. No O scores used.',
            'qualified_signal_missing_does_not_mean_market_bearish':True,
            'not_available_for_prior_AM':True,'simulated_trades_created':0}


def main():
    p=argparse.ArgumentParser()
    for key in ['universe','official','recovery','history','news','reviews','out']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();sources={k:getattr(a,k) for k in ['universe','official','recovery','history','news','reviews']};data={k:json.loads(v.read_text()) for k,v in sources.items()}
    result=audit(**data,target=data['recovery']['target']);result['source_sha256']={k:digest(v) for k,v in sources.items()};result['audited_at']=datetime.now(timezone.utc).isoformat()
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
