"""Independent U member dossiers and conditional approved-policy plans.

Separates factual/report coverage, U decisions, and live execution. A missing
ask is an execution blocker, not proof that a researched stock failed analysis.
This deterministic layer does not invent a BUY, ranking, macro regime or flow.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

VERSION='U_INHERITED_MEMBER_REPORT_v1'


def clock(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('TIMEZONE_REQUIRED')
    return d


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def indicator_facts(rows):
    if len(rows)<21 or len({r['date'] for r in rows})!=len(rows):raise ValueError('HISTORY_WINDOW_INVALID')
    if rows!=sorted(rows,key=lambda r:r['date']):raise ValueError('HISTORY_UNSORTED')
    c=[float(r['close']) for r in rows];v=[float(r['volume']) for r in rows]
    if any(not math.isfinite(x) or x<=0 for x in c) or any(not math.isfinite(x) or x<0 for x in v):raise ValueError('INVALID_FACTS')
    out={'close':c[-1],'return_1d_pct':(c[-1]/c[-2]-1)*100,
         'return_5d_pct':(c[-1]/c[-6]-1)*100,'return_20d_pct':(c[-1]/c[-21]-1)*100,
         **{'ma'+str(n):sum(c[-n:])/n for n in (5,10,20)},
         'volume_shares':v[-1],'volume_vs_previous5':v[-1]/(sum(v[-6:-1])/5) if sum(v[-6:-1]) else None,
         'observed_support20':min(float(r['low']) for r in rows[-20:]),
         'observed_resistance20':max(float(r['high']) for r in rows[-20:]),
         'turnover_hkd':None,'turnover_reason':'Provider amount lacks independent actual-turnover proof; close*volume is not used.',
         'rsi14':None,'macd':None,'indicator_history_count':len(rows)}
    # Wilder seed is explicit and reproducible. MACD needs at least26+9-1 bars.
    changes=[b-a for a,b in zip(c,c[1:])];gain=sum(max(x,0) for x in changes[:14])/14;loss=sum(max(-x,0) for x in changes[:14])/14
    for x in changes[14:]: gain=(gain*13+max(x,0))/14;loss=(loss*13+max(-x,0))/14
    out['rsi14']=50. if gain==loss==0 else 100. if loss==0 else 100-100/(1+gain/loss)
    out['rsi_seed']='Wilder average seeded with first14 changes in this disclosed window; not long-history equivalent.'
    if len(c)>=34:
        def ema(values,n):
            x=sum(values[:n])/n;result=[None]*(n-1)+[x]
            for z in values[n:]:x+=(2/(n+1))*(z-x);result.append(x)
            return result
        e12,e26=ema(c,12),ema(c,26);dif=[a-b for a,b in zip(e12[25:],e26[25:])]
        signal=ema(dif,9)[-1];out['macd']={'dif':dif[-1],'signal':signal,'histogram_2x':2*(dif[-1]-signal),'seed':'SMA-seeded EMA12/26 and EMA9'}
    else:out['macd_missing_reason']='FEWER_THAN34_VERIFIED_BARS; no fabricated MACD'
    out['trend']='BULLISH_MA_ORDER' if out['ma5']>out['ma10']>out['ma20'] else 'BEARISH_MA_ORDER' if out['ma5']<out['ma10']<out['ma20'] else 'MIXED_MA_ORDER'
    return out


def policy_plan(close,lot,policy):
    band=policy['price_band'];limits=policy['retained_disciplines']
    if policy['policy_id']!='DSA-SHADOW-ENTRY-v1.0.0' or limits['no_add_to_existing_position'] is not True:
        raise ValueError('UNSUPPORTED_APPROVED_POLICY')
    c=Decimal(str(close));low=c*Decimal(band['minimum_multiplier']);high=c*Decimal(band['maximum_multiplier'])
    return {'state':'CONDITIONAL_POLICY_PLAN_NOT_BUY_SIGNAL','policy_id':policy['policy_id'],
        'reference_daily_close':str(c),'reference_price_time':None,
        'entry_policy_envelope_hkd':[str(low),str(high)],'executable_buy_zone':None,
        'band_semantics':'Intersect with a separately accepted U buy zone, comparable raw price basis and valid future AM window. No tick rounding or fill is inferred.',
        'first_buy':'One accepted U Top3 candidate only; execute approved intersection during Entry-v1 window.',
        'second_buy':None,'add_condition':'PROHIBITED_FOR_FROZEN_SHADOW_ACCOUNT',
        'cash_ticket_ceiling_cny':'60000','single_security_nav_cap_pct':20,'account_gross_cap_pct':60,
        'max_positions':3,'max_new_securities_per_session':1,'position_pct_now':0,
        'macro_constrained_position_pct':None,'board_lot':lot,'minimum_entry_lots':3,
        'sizing':'Largest multiple of3 board lots within min(CNY60000,20%NAV,remaining60%gross cap,remaining macro cap), including verified FX and fees; no value until evidence is available.',
        'hard_stop':{'basis':'actual_fill_price','multiplier':'0.98','sell':'all_remaining','gap':'actual worse executable price, never guaranteed loss limit'},
        'tp1':{'basis':'actual_fill_price','multiplier':'1.05','sell':'one_third_original_integer_lots'},
        'tp2':{'basis':'actual_fill_price','multiplier':'1.10','sell':'one_third_original_integer_lots'},
        'runner':{'sell':'accepted_rank_decay_confirmation_then_future_executable_quote','milestones':'20%,30%,40%... alerts only'},
        'hold_window':'5–20 actual trading days research observation; not an automatic time stop',
        'requires_before_signal':['accepted_U_BUY_and_rank','accepted_U_buy_zone','verified_macro_cap','timely_AM_freeze','comparable_price_basis'],
        'requires_at_execution':['timestamped_firm_ask_after_signal_and_order','ask_quantity_units','tradability','verified_fees','verified_FX','board_lot'],
        'real_account_holdings':'NOT_PROVIDED_NOT_INFERRED','fills_created':0}


def build(universe,official,facts,recovery,history,readiness,news,reviews,capital,policy,asof):
    cut=clock(asof);target=recovery['target']
    if cut>datetime.now(timezone.utc):raise ValueError('FUTURE_ASOF')
    if len(universe['members'])!=universe['member_count'] or universe['member_count']!=45:raise ValueError('U_DENOMINATOR_MISMATCH')
    if official['effective_session']<target or not official['full_union_verified']:raise ValueError('OFFICIAL_INPUT_INVALID')
    for d,k in ((facts,'generated_at'),(news,'generated_at'),(history,'collected_at')):
        if clock(d[k])>cut:raise ValueError('FUTURE_INPUT')
    om={r['code']:r for r in official['members']};fm={r['code']:r for r in facts['rows']};nm={r['code']:r for r in news['rows']};hm={r['code']:r for r in readiness['members']};rv={r['code']:r for r in reviews['members']}
    cs=next((x for x in capital['sources'] if x['source']=='hkex' and x['status']=='VERIFIED' and x['data']['as_of_date']==target and clock(x['first_observed_at'])<=cut),None)
    rows=[]
    for m in universe['members']:
        code=m['code'];base={'code':code,'name':m['user_alias'],'status':'INPUT_ISOLATED','action':'NO_TRADE',
            'score':None,'rank':None,'facts':None,'plan':None,'findings':[],'data_session':target,
            'report_available_at':asof,'formal_buy_accepted':False,'O_results_used':False}
        if code not in om:
            base.update(status='ACCEPTED_INELIGIBILITY_DISPOSITION',findings=['NOT_IN_CURRENT_BUY_UNION_RETAINED_IN45'])
            rows.append(base);continue
        try:
            r=recovery['inputs'][code]['rows'];source_window='Run00621'
            if hm.get(code,{}).get('independent_history_passed'):
                native=history['histories'][code]['native']
                if all(abs(float(a['close'])-float(b['close']))<=.005 for a,b in zip(native[-21:],r)):
                    r=native;source_window='Run033_independently_checked_full_window'
            derived=indicator_facts(r)
            if r[-1]['date']!=target or fm[code]['market_session']!=target:raise ValueError('TARGET_MISMATCH')
            f=fm[code]['facts']
            for key in ('close','ma5','ma10','ma20'):
                if abs(derived[key]-f[key])>.00500001:raise ValueError('FACT_RECOMPUTATION_CONFLICT')
            n=nm.get(code,{});review=rv.get(code,{})
            primary=review.get('status')=='PASS_REVIEWED_COVERAGE' and clock(review['reviewed_at'])<=cut
            news_status='VERIFIED_BOUNDED_ISSUER_EVENT' if primary else 'LIMITED_SEARCH_NO_VERIFIED_RECENT_EVENT' if n.get('retrieval_ready') else 'SEARCH_UNAVAILABLE'
            flow=cs['data']['top10_union'].get(code) if cs else None
            capital_row={'status':flow['status'] if flow else 'NOT_DISCLOSED_IN_TOP10' if cs else 'SOURCE_UNAVAILABLE',
                'net_buy_hkd':flow['net_buy_hkd'] if flow else None,'channel_coverage':flow['channel_coverage'] if flow else 0,
                'channels':flow['channels'] if flow else {},'source_locator':cs['source_locator'] if cs else None,
                'source_sha256':cs['sha256'] if cs else None,'available_at':cs['first_observed_at'] if cs else None,
                'date':target,'persistence':'ONE_SESSION_ONLY_NOT_A_TREND','ultimate_investor_identity':'NOT_PROVEN'}
            base.update(status='BOUNDED_FACT_REPORT_VERIFIED',action='OBSERVE',facts=derived,
                history_source=source_window,history_bars=len(r),
                news={'state':news_status,'retrieval_ready':bool(n.get('retrieval_ready')),
                      'verified_source_urls':[s['url'] for s in review.get('sources',[])] if primary else [],
                      'title_hits_unverified':len(n.get('unique_recent_relevant_items',[])),
                      'scope':'Bounded evidence only. Absence of a verified event is not evidence of no adverse news.'},
                capital=capital_row,plan=policy_plan(f['close'],om[code]['board_lot'],policy),
                findings=['FULL_U_MODEL_REVIEW_NOT_YET_PRODUCED','MACRO_CAP_NOT_YET_VERIFIED'],
                evidence_ids=['price:'+code,'technical:'+code,'news-status:'+code,'capital-status:'+code,'policy:Entry-v1'])
        except (KeyError,ValueError,TypeError) as exc:
            base['findings']=[str(exc) if isinstance(exc,ValueError) else type(exc).__name__]
        rows.append(base)
    return {'schema_version':VERSION,'run_id':'TRI-DSA-EXEC-20260917-041','track':'U','U_denominator':45,
        'asof':asof,'generated_at':datetime.now(timezone.utc).isoformat(),'target_session':target,'members':rows,
        'coverage':{'dispositions_written':len(rows),'bounded_factual_reports_verified':sum(r['status']=='BOUNDED_FACT_REPORT_VERIFIED' for r in rows),
            'ineligible_dispositions':sum(r['status']=='ACCEPTED_INELIGIBILITY_DISPOSITION' for r in rows),
            'conditional_policy_plans':sum(r['plan'] is not None for r in rows),'full_U_model_reviews':0,'qualified_BUY':0,'simulated_fills':0},
        'Top3':[],'Top10':[],'model_requests':0,'fee_cny':'0',
        'macro':{'regime':None,'verified_position_cap_pct':None,'missing_engines':['A','B','C','D_complete','E','F'],
            'G_market_net_buy_hkd':cs['data']['net_buy_hkd'] if cs else None,
            'not_a_market_bearish_judgment':True},
        'legacy_metric':{'Run038_formal_accepted':0,'meaning':'Missing end-to-end signal artifact, not45 independent model rejections. Old receipt unchanged.'},
        'classification_notice':'This is real factual-report/conditional-policy-plan coverage, not full strategy acceptance, production promotion or45 BUY signals.',
        'entry_authorization':'Existing authority unchanged; execution evidence is checked only downstream of a valid signal.'}


def main():
    p=argparse.ArgumentParser()
    names=['universe','official','facts','recovery','history','readiness','news','reviews','capital','policy']
    for k in names:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--asof',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    paths={k:getattr(a,k) for k in names};d={k:json.loads(v.read_text()) for k,v in paths.items()}
    # Revalidate actual capital bytes, not just a receipt's success flag.
    for row in d['capital']['sources']:
        if row.get('artifact') and sha(a.capital.parent/row['artifact'])!=row['sha256']:raise ValueError('CAPITAL_RAW_HASH_MISMATCH')
    result=build(**d,asof=a.asof);result['input_sha256']={k:sha(v) for k,v in paths.items()}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x') as handle:json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result['coverage']))

if __name__=='__main__':main()
