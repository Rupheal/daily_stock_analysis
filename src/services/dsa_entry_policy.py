"""Versioned, opt-in entry policy for the EXISTING DSA journal (no I/O/orders).

All source assertions must be independently accepted upstream. This module checks
structure, clocks, bounds and arithmetic; it cannot authenticate a vendor quote.
Legacy commands without a binding keep their original replay semantics. A bound
signal pins the policy for NEW entries of that account/session (including retries).
Runtime activation is deliberately outside this module and remains NOT approved.
"""
from __future__ import annotations
import copy
import json
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from src.services.dsa_prediction_ledger import canonical_hash, _aware_timestamp

HK = ZoneInfo('Asia/Hong_Kong')
POLICY = json.loads((Path(__file__).resolve().parents[2] / 'policies/DSA_SHADOW_ENTRY_POLICY_v1.0.0.json').read_text(encoding='utf-8'))
POLICY_ID = 'DSA-SHADOW-ENTRY-v1.0.0'
POLICY_HASH = canonical_hash(POLICY)
assert POLICY['policy_id'] == POLICY_ID and POLICY['runtime_activated'] is False
DECIMAL_ZERO = Decimal(0)

REASONS = {
 'WAIT_FREEZE':'等待当日早报与交易计划冻结', 'LATE_FREEZE':'早报或交易计划晚于09:25冻结',
 'NOT_MORNING':'不是当日验收通过的早报', 'SESSION_UNVERIFIED':'实际交易日未核验',
 'REFERENCE_UNVERIFIED':'参考收盘价或公司行动口径未核验', 'BEFORE_WINDOW':'尚未到09:30买入窗口',
 'WINDOW_CLOSED':'10:00买入窗口已结束；不转下午追买', 'SIGNAL_EXPIRED':'信号已失效',
 'SIGNAL_BLOCKED':'原生信号未验收或未明确允许买入', 'POLICY_REQUIRED':'本交易日已绑定新规则，不能绕回旧入口',
 'PRICE_BELOW_BAND':'低于参考价下限，不自动抄底', 'PRICE_ABOVE_BAND':'超过参考价上限，不追价',
 'EMPTY_BUY_ZONE':'原生买入区间与价格保护带没有交集', 'HIGHER_RANK_UNKNOWN':'较高排名候选尚无明确排除依据',
 'NOT_FIRST_ELIGIBLE':'不是按排名顺序选出的第一只合格候选', 'DAILY_SLOT_USED':'本账户今日已使用新开仓名额',
 'SOLD_TODAY':'同一标的当天已卖出，不再买回', 'ALREADY_HELD':'已有持仓，不新增订单加仓',
 'FEES_UNKNOWN':'费用未知，不新开仓', 'ORDER_PENDING':'已有未完成买单，不另开买单',
 'ORDER_UNAVAILABLE':'没有可执行的冻结订单或订单已取消', 'ORDER_LIMIT':'超过冻结订单价格、数量或资金上限',
 'FILL_EVIDENCE':'报价时间、可成交数量或连续交易状态证据不足', 'VALUATION_MISSING':'缺少统一时点估值，不计算虚假净值',
 'POSITION_LIMIT':'仓位数量、单票、总仓或行业限额不足', 'MINIMUM_LOTS':'首次成交不足三整手，暂不成交',
 'RISK_CHANGED':'已触发持仓风险处理，撤销剩余买单', 'UNKNOWN':'条件未满足',
 'NO_MORNING_FREEZE':'09:25前未完成合格早报冻结，当日不新开仓',
}
class Gate(ValueError):
    """Expected business rejection, retained as a NO_TRADE event."""

def dt(s):
    return _aware_timestamp(s, 'policy timestamp').astimezone(HK)

def day(s):
    return dt(s).date().isoformat()

def D(x):
    if isinstance(x, bool): raise Gate('FILL_EVIDENCE')
    try: d=Decimal(str(x))
    except Exception as exc: raise Gate('FILL_EVIDENCE') from exc
    if not d.is_finite(): raise Gate('FILL_EVIDENCE')
    return d

def integer(x):
    v=D(x)
    if v != v.to_integral_value() or v <= 0: raise Gate('FILL_EVIDENCE')
    return int(v)

def ev(x, no_later_than=None):
    if not isinstance(x,dict) or x.get('verified') is not True or not x.get('source') or not re.fullmatch('[0-9a-f]{64}',str(x.get('sha256',''))):
        raise Gate('FILL_EVIDENCE')
    if no_later_than is not None:
        if not x.get('at') or dt(x['at']) > dt(no_later_than): raise Gate('FILL_EVIDENCE')

def band(s, code):
    b=s['entry_policy'];r=b['references'].get(code)
    if not isinstance(r,dict):raise Gate('REFERENCE_UNVERIFIED')
    try:
        ev(r,b['frozen_at'])
        if r.get('code') != code: raise Gate('REFERENCE_UNVERIFIED')
        if r['session']!=b['calendar']['previous_session'] or day(r['at'])!=r['session']: raise Gate('REFERENCE_UNVERIFIED')
        if r.get('comparable_basis') is not True or r.get('corporate_actions_verified') is not True or r.get('price_basis')!='execution_raw_comparable':raise Gate('REFERENCE_UNVERIFIED')
        p=D(r['close'])
        if p<=0: raise Gate('REFERENCE_UNVERIFIED')
        lo,hi=p*D('0.990'),p*D('1.015')
        z=b.get('native_buy_zones',{}).get(code)
        if z is not None:
            ev(z,b['frozen_at'])
            if z.get('code') != code: raise Gate('REFERENCE_UNVERIFIED')
            a,c=D(z['lower']),D(z['upper'])
            if a<=0 or c<a: raise Gate('REFERENCE_UNVERIFIED')
            lo,hi=max(lo,a),min(hi,c)
        if lo>hi: raise Gate('EMPTY_BUY_ZONE')
        return lo,hi
    except Gate: raise
    except (KeyError,TypeError,ValueError) as exc: raise Gate('REFERENCE_UNVERIFIED') from exc

def check_binding(s,cmd):
    b=s['entry_policy']
    if b.get('policy_id')!=POLICY_ID or b.get('policy_sha256')!=POLICY_HASH:
        raise ValueError('unknown or mutated entry policy binding')
    try:
        session=b['session'];f=dt(b['frozen_at']);cal=b['calendar']
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',session):raise Gate('SESSION_UNVERIFIED')
        ev(cal,b['frozen_at'])
        datetime.fromisoformat(cal['previous_session'])
        if cal.get('session')!=session or cal.get('is_trading_day') is not True or cal['previous_session']>=session or f.weekday()>=5:raise Gate('SESSION_UNVERIFIED')
        if day(s['cutoff'])!=session or day(s['available_at'])!=session or f.date().isoformat()!=session or day(cmd['at'])!=session:raise Gate('NOT_MORNING')
        if b.get('report_session')!='AM' or b.get('morning_report_accepted') is not True:raise Gate('NOT_MORNING')
        # Command append/freeze itself must be timely, not just a user-supplied label.
        if f.time()>time(9,25) or dt(cmd['at']).time()>time(9,25):raise Gate('LATE_FREEZE')
        if not dt(s['available_at'])<=f<=dt(cmd['at']):raise Gate('LATE_FREEZE')
        if not dt(cmd['at'])<=dt(cmd['recorded_at']) or dt(cmd['recorded_at']).time()>time(9,25) or day(cmd['recorded_at'])!=session:raise Gate('LATE_FREEZE')
        refs=b['references']
        if not isinstance(refs,dict):raise Gate('REFERENCE_UNVERIFIED')
        # Keep partial U evidence visible; per-candidate reference gates are applied
        # when it is considered. Missing Top1 data is never an exclusion.
        if not s.get('passed'):raise Gate('SIGNAL_BLOCKED')
        return None
    except Gate as exc:return str(exc)
    except (KeyError,TypeError,ValueError):return 'REFERENCE_UNVERIFIED'

def _ledger():
    from src.services import dsa_simulation_ledger as l
    return l

def _meta(a):
    return a.setdefault('entry_control',{'sessions':{},'signal_gates':{},'orders':{},'liquidity_used':{}})

def window(at,session):
    if day(at)!=session or dt(at).time()>=time(10):raise Gate('WINDOW_CLOSED')
    if dt(at).time()<time(9,30):raise Gate('BEFORE_WINDOW')

def expire_orders(a,cmd):
    if 'entry_control' not in a:return
    for o in a['entry_control']['orders'].values():
        if o['status'] in ('PENDING','PARTIAL') and (day(cmd['at'])>o['session'] or (day(cmd['at'])==o['session'] and dt(cmd['at']).time()>=time(10))):
            o['status']='CANCELLED';o['cancel_reason']='WINDOW_CLOSED'
            _ledger().record(a,cmd,'ENTRY_CANCEL',order_id=o['id'],code=o['code'],reason='WINDOW_CLOSED',
                effective_at=o['session']+'T10:00:00+08:00',remaining_qty=o['qty']-o['filled_qty'])

def used(a,session):
    return {e['code'] for e in a['events'] if e['kind']=='BUY' and day(e['at'])==session}

def sold(a,code,session):
    return any(e['kind']=='SELL' and e.get('code')==code and day(e['at'])==session for e in a['events'])

def signal_for(a,cmd):
    sig=a['signals'].get(cmd.get('signal_id'))
    if not sig or not sig['original'].get('entry_policy'):raise Gate('POLICY_REQUIRED')
    s=sig['original'];b=s['entry_policy'];m=_meta(a)
    if not s.get('passed'):raise Gate('SIGNAL_BLOCKED')
    reason=m['signal_gates'].get(s['id'])
    if reason:raise Gate(reason)
    if day(cmd['at'])!=b['session'] or dt(cmd['at']).time()>=time(10):raise Gate('WINDOW_CLOSED')
    if dt(cmd['at'])>=dt(s['valid_until']):raise Gate('SIGNAL_EXPIRED')
    if dt(cmd['at'])<=dt(s['available_at']):raise Gate('BEFORE_WINDOW')
    return s

def select(a,s,cmd):
    top=sorted(s['top3'],key=lambda r:(r['rank'],r['code']))[:3]
    excluded=cmd.get('excluded',{})
    for r in top:
        code=r['code']
        if code in a['positions']:continue
        if code in excluded:
            x=excluded[code]
            try:ev(x,cmd['at'])
            except Gate:raise Gate('HIGHER_RANK_UNKNOWN')
            if x.get('code')!=code or x.get('eligible') is not False:raise Gate('HIGHER_RANK_UNKNOWN')
            reason=x.get('reason')
            if reason in ('ABOVE_BAND','BELOW_BAND'):
                lo,hi=band(s,code)
                if day(x['at'])!=s['entry_policy']['session'] or dt(x['at']).time()<time(9,30):raise Gate('HIGHER_RANK_UNKNOWN')
                p=D(x.get('price'))
                if not ((reason=='ABOVE_BAND' and p>hi) or (reason=='BELOW_BAND' and p<lo)):raise Gate('HIGHER_RANK_UNKNOWN')
            elif reason=='NATIVE_NON_BUY':
                if r.get('action')=='BUY':raise Gate('HIGHER_RANK_UNKNOWN')
            elif reason not in ('SUSPENDED','NOT_BUYABLE','INDUSTRY_CAP'):raise Gate('HIGHER_RANK_UNKNOWN')
            continue
        if code!=cmd['code']:raise Gate('NOT_FIRST_ELIGIBLE')
        if r.get('action')!='BUY' or r.get('buyable_verified') is not True:raise Gate('SIGNAL_BLOCKED')
        band(s,code)
        return r
    raise Gate('NOT_FIRST_ELIGIBLE')

def funds(a,config,s,selected,at):
    l=_ledger();rules=config['rules']
    marks=a['marks']
    a['marks']=copy.deepcopy(marks)
    try:
        for q in a['marks'].values():
            if dt(q['at'])==dt(at):q['at']=at
        nav=l.portfolio_value(a,at)
    except (ValueError,KeyError) as exc:raise Gate('VALUATION_MISSING') from exc
    finally:a['marks']=marks
    invested=nav-D(a['cash']);code=selected['code']
    own=a['positions'].get(code)
    own_mv=D(0) if not own else D(own['qty'])*D(a['marks'][code]['price'])*D(a['marks'][code]['cny_per_hkd'])
    industry=sum(D(p['qty'])*D(a['marks'][k]['price'])*D(a['marks'][k]['cny_per_hkd']) for k,p in a['positions'].items() if p['industry']==selected['industry'])
    cap=min(D(rules['total_cap']),D(s.get('total_cap',rules['total_cap'])),D('.60'))
    return max(D(0),min(D(rules['ticket_cny'])- (D(own['cost_cny']) if own else 0),
       D('60000')-(D(own['cost_cny']) if own else 0),nav*min(D(rules['ticket_cap']),D('.20'))-own_mv,
       nav*cap-invested,nav*D(rules['industry_cap'])-industry,D(a['cash'])))

def create_order(a,config,cmd):
    m=_meta(a);s=signal_for(a,cmd);b=s['entry_policy'];session=b['session']
    if dt(cmd['at']).time()>=time(10):raise Gate('WINDOW_CLOSED')
    if dt(cmd['at'])<dt(b['frozen_at']):raise Gate('WAIT_FREEZE')
    if used(a,session):raise Gate('DAILY_SLOT_USED')
    if sold(a,cmd['code'],session):raise Gate('SOLD_TODAY')
    if cmd['code'] in a['positions']:raise Gate('ALREADY_HELD')
    if any(o['status'] in ('PENDING','PARTIAL') for o in m['orders'].values()):raise Gate('ORDER_PENDING')
    r=select(a,s,cmd);o=cmd['order'];oid=o['id']
    if oid in m['orders']:raise ValueError('immutable order ID conflict')
    if len(a['positions'])>=min(config['rules']['max_positions'],3):raise Gate('POSITION_LIMIT')
    lo,hi=band(s,r['code']);limit=D(o['limit_price']);qty=integer(o['qty'])
    if not lo<=limit<=hi:raise Gate('ORDER_LIMIT')
    q=cmd['quote'];ev(q,cmd['at'])
    if q.get('code') != cmd['code']:raise Gate('FILL_EVIDENCE')
    try:_,fx=_ledger().quote_price(q,cmd['at'])
    except ValueError as exc:raise Gate('FILL_EVIDENCE') from exc
    lot=integer(q['lot_size'])
    if q.get('lot_verified') is not True or qty%lot:raise Gate('FILL_EVIDENCE')
    if qty<3*lot:raise Gate('MINIMUM_LOTS')
    fee=o.get('fee_reserve_cny')
    if fee is None:raise Gate('FEES_UNKNOWN')
    fee=D(fee)
    if fee<0:raise Gate('FEES_UNKNOWN')
    fee_evidence=cmd.get('fee_evidence')
    try:
        ev(fee_evidence,cmd['at'])
        if fee_evidence.get('currency')!='CNY' or D(fee_evidence.get('amount_cny'))!=fee:raise Gate('FEES_UNKNOWN')
    except (Gate,TypeError,AttributeError) as exc:raise Gate('FEES_UNKNOWN') from exc
    budget=funds(a,config,s,r,cmd['at'])
    if qty*limit*fx+fee>budget:raise Gate('POSITION_LIMIT')
    if dt(cmd['recorded_at'])<dt(cmd['at']):raise Gate('FILL_EVIDENCE')
    m['orders'][oid]={'id':oid,'signal_id':s['id'],'code':r['code'],'session':session,'at':cmd['at'],
        'qty':qty,'filled_qty':0,'lot':lot,'limit_price':str(limit),'budget_cny':str(budget),
        'spent_cny':'0','fees_cny':'0','fee_reserve_cny':str(fee),'status':'PENDING','selected':copy.deepcopy(r),
        'frozen_order_hash':canonical_hash(cmd),'policy_id':POLICY_ID,'policy_sha256':POLICY_HASH}
    _ledger().record(a,cmd,'ENTRY_ORDER',order_id=oid,signal_id=s['id'],code=r['code'],qty=qty,
        reference_price=b['references'][r['code']]['close'],lower=str(lo),upper=str(hi))

def fill_order(a,config,cmd):
    s=signal_for(a,cmd);session=s['entry_policy']['session'];window(cmd['at'],session)
    m=_meta(a);o=m['orders'].get(cmd.get('order_id'))
    if not o or o['status'] not in ('PENDING','PARTIAL') or o['signal_id']!=s['id'] or cmd['code']!=o['code']:raise Gate('ORDER_UNAVAILABLE')
    code=o['code'];p=a['positions'].get(code)
    if sold(a,code,session):raise Gate('SOLD_TODAY')
    if used(a,session) and not (o['filled_qty'] and p and p.get('entry_order_id')==o['id']):raise Gate('DAILY_SLOT_USED')
    if p and (p.get('entry_order_id')!=o['id'] or p['stage']!=0 or p['qty']!=p['original_qty']):raise Gate('RISK_CHANGED')
    q=cmd['quote'];ev(q,cmd['at'])
    if q.get('code') != cmd['code']:raise Gate('FILL_EVIDENCE')
    if q.get('mode')!='tick' or q.get('session_phase')!='continuous' or q.get('quote_kind')!='firm_ask':raise Gate('FILL_EVIDENCE')
    try:
        if not dt(o['at'])<dt(q['at'])==dt(cmd['at'])<=dt(q['received_at'])<=dt(cmd['recorded_at']):raise Gate('FILL_EVIDENCE')
        price,fx=_ledger().quote_price(q,cmd['at'])
    except (ValueError,KeyError) as exc:raise Gate('FILL_EVIDENCE') from exc
    if q.get('first_eligible_price_verified') is not True or q.get('quantity_verified') is not True or q.get('lot_verified') is not True:raise Gate('FILL_EVIDENCE')
    lot=integer(q.get('lot_size'));qty=integer(cmd['fill_qty']);avail=integer(q.get('available_qty'))
    if lot!=o['lot'] or qty%lot or qty>avail or qty>o['qty']-o['filled_qty']:raise Gate('ORDER_LIMIT')
    if not o['filled_qty'] and qty<3*lot:raise Gate('MINIMUM_LOTS')
    liq=canonical_hash([code,dt(q['at']).isoformat(),q['source'],q['sha256'],str(price)])
    if m['liquidity_used'].get(liq,0)+qty>avail:raise Gate('FILL_EVIDENCE')
    lo,hi=band(s,code)
    if price<lo:raise Gate('PRICE_BELOW_BAND')
    if price>hi:raise Gate('PRICE_ABOVE_BAND')
    if price>D(o['limit_price']):raise Gate('ORDER_LIMIT')
    fee=cmd.get('fee_cny')
    if fee is None:raise Gate('FEES_UNKNOWN')
    fee=D(fee)
    if fee<0:raise Gate('FEES_UNKNOWN')
    fee_evidence=cmd.get('fee_evidence')
    try:
        ev(fee_evidence,cmd['at'])
        if fee_evidence.get('currency')!='CNY' or D(fee_evidence.get('amount_cny'))!=fee:raise Gate('FEES_UNKNOWN')
    except (Gate,TypeError,AttributeError) as exc:raise Gate('FEES_UNKNOWN') from exc
    cost=qty*price*fx+fee
    if D(o['fees_cny'])+fee>D(o['fee_reserve_cny']) or D(o['spent_cny'])+cost>D(o['budget_cny']):raise Gate('ORDER_LIMIT')
    # Current fill quote is usable only for this security at this valuation instant.
    # The other positions still require explicit same-time MARK inputs.
    old=a['marks'].get(code)
    if p:a['marks'][code]=copy.deepcopy(q)
    try:budget=funds(a,config,s,o['selected'],cmd['at'])
    finally:
        if p:
            if old is None:a['marks'].pop(code,None)
            else:a['marks'][code]=old
    if cost>budget or (not p and len(a['positions'])>=min(config['rules']['max_positions'],3)):raise Gate('POSITION_LIMIT')
    if not p:
        _ledger().book_buy(a,cmd,s,o['selected'],qty,lot,price,fx,fee)
        p=a['positions'][code];p['entry_order_id']=o['id'];p['entry_policy_id']=POLICY_ID
        p['entry_policy_sha256']=POLICY_HASH
    else:
        # Same immutable order only. Existing sell/valuation/summary functions are reused.
        p['entry_price']=str((D(p['entry_price'])*p['qty']+price*qty)/(p['qty']+qty))
        p['qty']+=qty;p['original_qty']+=qty;p['cost_cny']=str(D(p['cost_cny'])+cost)
        a['cash']=str(D(a['cash'])-cost)
        _ledger().record(a,cmd,'BUY',code=code,trade_id=p['trade_id'],qty=qty,price=str(price),fx=str(fx),fee_cny=str(fee),signal_id=s['id'])
    p['last_fill_at']=cmd['at']
    a['events'][-1].update(order_id=o['id'],policy_id=POLICY_ID)
    a['marks'][code]=copy.deepcopy(q)
    a['signals'][s['id']]['filled']=True
    o['filled_qty']+=qty;o['spent_cny']=str(D(o['spent_cny'])+cost);o['fees_cny']=str(D(o['fees_cny'])+fee)
    o['status']='FILLED' if o['filled_qty']==o['qty'] else 'PARTIAL';m['liquidity_used'][liq]=m['liquidity_used'].get(liq,0)+qty

def before_command(state,config,cmd):
    a=state[cmd['account']];kind=cmd['kind']
    expire_orders(a,cmd)
    if kind=='BAR':
        p=a['positions'].get(cmd.get('code'))
        if p and p.get('entry_policy_id')==POLICY_ID and dt(cmd['bar']['open_at'])<dt(p.get('last_fill_at',p['entry_at'])):
            raise ValueError('bar begins before latest partial fill; cannot apply pre-fill path to later quantity')
    if kind=='SIGNAL':
        s=cmd['signal']
        if s.get('entry_policy'):
            reason=check_binding(s,cmd)  # hash tampering is an error, not a gate.
            return False
        return False
    m=a.get('entry_control',{})
    if kind=='ENTRY' and not a['signals'].get(cmd.get('signal_id'),{}).get('original',{}).get('entry_policy'):
        if day(cmd['at']) not in m.get('sessions',{}):return False
        _ledger().record(a,cmd,'NO_TRADE',reason='POLICY_REQUIRED');a['last_at']=cmd['at'];return True
    handles=kind in ('ENTRY_ORDER','ENTRY_CANCEL','ENTRY_CLOCK') or (kind=='ENTRY' and a['signals'].get(cmd.get('signal_id'),{}).get('original',{}).get('entry_policy'))
    if not handles:return False
    before=copy.deepcopy(a)
    try:
        if kind=='ENTRY_ORDER':create_order(a,config,cmd)
        elif kind=='ENTRY':fill_order(a,config,cmd)
        elif kind=='ENTRY_CLOCK':_ledger().record(a,cmd,'ENTRY_CLOCK',reason='OBSERVATION_ONLY')
        elif kind=='ENTRY_CANCEL':
            o=_meta(a)['orders'].get(cmd.get('order_id'))
            if not o:raise Gate('ORDER_UNAVAILABLE')
            if o['status'] in ('PENDING','PARTIAL'):
                o['status']='CANCELLED';o['cancel_reason']='OWNER_OR_EXECUTOR_CANCEL'
                _ledger().record(a,cmd,'ENTRY_CANCEL',order_id=o['id'],code=o['code'],reason=o['cancel_reason'],remaining_qty=o['qty']-o['filled_qty'])
    except (Gate,KeyError,TypeError) as exc:
        reason=str(exc) if isinstance(exc,Gate) else 'FILL_EVIDENCE'
        a.clear();a.update(before)
        _ledger().record(a,cmd,'NO_TRADE',reason=reason,code=cmd.get('code'),policy_id=POLICY_ID)
    a['last_at']=cmd['at']
    return True

def after_command(state,config,cmd):
    a=state[cmd['account']]
    if cmd['kind']=='SIGNAL' and cmd['signal'].get('entry_policy'):
        s=cmd['signal'];m=_meta(a);b=s['entry_policy']
        m['sessions'][b['session']]=POLICY_ID;m['signal_gates'][s['id']]=check_binding(s,cmd)
        if m['signal_gates'][s['id']]:_ledger().record(a,cmd,'ENTRY_WAIT',signal_id=s['id'],reason=m['signal_gates'][s['id']],policy_id=POLICY_ID)
    if cmd['kind']=='BAR' and 'entry_control' in a:
        for o in a['entry_control']['orders'].values():
            p=a['positions'].get(o['code'])
            if o['filled_qty'] and o['status']=='PARTIAL' and (not p or p['stage']!=0 or p['qty']!=p['original_qty']):
                o['status']='CANCELLED';o['cancel_reason']='RISK_CHANGED'
                _ledger().record(a,cmd,'ENTRY_CANCEL',order_id=o['id'],code=o['code'],reason='RISK_CHANGED',remaining_qty=o['qty']-o['filled_qty'])

def frontend_status(journal,account,as_of):
    """Read-only, time-filtered display state. No writes or fabricated cancels.

    Verify the entire original chain first; then project only commands whose event
    and observation times were available at the requested instant. The original
    journal is never rehashed or altered to create this projection.
    """
    l=_ledger();l.replay(journal)
    visible=l.initial(journal['config'])
    for item in journal['commands']:
        c=item['command']
        if dt(c['at'])<=dt(as_of) and dt(c.get('recorded_at',c['at']))<=dt(as_of):
            l.apply_command(visible,journal['config'],c)
    a=visible[account];session=day(as_of)
    ss=[v['original'] for v in a['signals'].values() if v['original'].get('entry_policy',{}).get('session')==session]
    rows=[];gate='WAIT_FREEZE';slots=len(used(a,session));t=dt(as_of).time()
    if ss:
        s=max(ss,key=lambda s:dt(s['entry_policy']['frozen_at']));gate=a['entry_control']['signal_gates'].get(s['id'])
        for r in s.get('top3',[]):
            try:
                lo,hi=band(s,r['code']);ref=s['entry_policy']['references'][r['code']]['close']
                rows.append({'ticker':r['code'],'reference':ref,'lower':str(lo),'upper':str(hi)})
            except Gate:rows.append({'ticker':r['code'],'reference':None,'lower':None,'upper':None})
        if slots:gate='FILLED'
        elif not gate:
            gate='WINDOW_CLOSED' if t>=time(10) else 'SIGNAL_EXPIRED' if dt(as_of)>=dt(s['valid_until']) else 'BEFORE_WINDOW' if t<time(9,30) else 'IN_WINDOW'
    elif t>=time(10):gate='WINDOW_CLOSED'
    elif t>time(9,25):gate='NO_MORNING_FREEZE'
    last=[e for e in a['events'] if day(e['at'])==session and e['kind'] in ('NO_TRADE','ENTRY_WAIT','ENTRY_CANCEL')]
    orders=[]
    for o in a.get('entry_control',{}).get('orders',{}).values():
        if o['session']!=session:continue
        expired=t>=time(10) and o['status'] in ('PENDING','PARTIAL')
        orders.append({'order_id':o['id'],'ticker':o['code'],'filled_qty':o['filled_qty'],'total_qty':o['qty'],
            'state':'EXPIRED_AWAITING_CANCEL_RECEIPT' if expired else o['status'],
            'cancel_recorded':o['status']=='CANCELLED','expired_by_clock':expired})
    return {'policy_id':POLICY_ID,'approval':'OWNER_APPROVED_POLICY','runtime_activated':False,
        'freeze_deadline':'09:25','window':'09:30—10:00','as_of':as_of,'state':gate,
        'label':{'FILLED':'已成交','IN_WINDOW':'窗口内，仍须满足完整成交条件'}.get(gate,REASONS.get(gate,gate)),
        'daily_slots_used':slots,'daily_slots_limit':1,'references':rows,'orders':orders,
        'last_reason':REASONS.get(last[-1]['reason'],last[-1]['reason']) if last else None}
