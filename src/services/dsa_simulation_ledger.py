"""Deterministic simulation journal. No network, model calls or broker orders.

Inputs must be independently verified by the caller. Monetary state is rebuilt
from hash-linked commands; a repeated command ID is a no-op, not another fill.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import os
import tempfile

from src.services.dsa_prediction_ledger import canonical_hash, _aware_timestamp


def dec(x):
    n = Decimal(str(x))
    if not n.is_finite():
        raise ValueError('nonfinite number')
    return n


def stamp(x):
    return _aware_timestamp(x, 'timestamp')


def new_journal(config):
    if set(config['accounts']) != {'U', 'O'}:
        raise ValueError('exactly U/O accounts required')
    return {'schema_version': 1, 'config': copy.deepcopy(config),
            'config_hash': canonical_hash(config), 'commands': []}


def initial(config):
    return {k: {'cash': str(dec(v)), 'positions': {}, 'signals': {},
                'events': [], 'last_at': None, 'marks': {}, 'nav_history': [], 'fees_known': True}
            for k, v in config['accounts'].items()}


def evidence(item):
    if item.get('verified') is not True or not item.get('source') or not item.get('sha256'):
        raise ValueError('verified evidence required')
    if len(item['sha256']) != 64:
        raise ValueError('evidence sha256 required')


def record(a, cmd, kind, **kw):
    a['events'].append({'event_id': f"{cmd['id']}:{len(a['events'])}",
                        'command_id': cmd['id'], 'at': cmd['at'], 'kind': kind, **kw})


def quote_price(q, at):
    evidence(q)
    if stamp(q['at']) > stamp(at) or q.get('tradable') is not True:
        raise ValueError('future/nontradable quote')
    if q.get('adjustment') != 'raw':
        raise ValueError('execution requires raw price')
    price, fx = dec(q['price']), dec(q['cny_per_hkd'])
    if price <= 0 or fx <= 0:
        raise ValueError('invalid price or FX')
    evidence(q['fx_evidence'])
    if stamp(q['fx_evidence']['at']) > stamp(q['at']):
        raise ValueError('future FX')
    return price, fx


def portfolio_value(a, at):
    total = dec(a['cash'])
    for code, p in a['positions'].items():
        q = a['marks'].get(code)
        if not q or q['at'] != at:
            raise ValueError('current valuation marks missing')
        price, fx = quote_price(q, at)
        total += dec(p['qty']) * price * fx
    return total


def sell(a, cmd, p, qty, price, fx, reason, fees):
    if qty <= 0:
        return
    gross = dec(qty) * price * fx
    fee = dec(fees) if fees is not None else Decimal(0)
    if fee < 0:
        raise ValueError('negative fee')
    a['fees_known'] &= fees is not None
    cost = dec(p['cost_cny']) * dec(qty) / dec(p['qty'])
    a['cash'] = str(dec(a['cash']) + gross - fee)
    p['cost_cny'] = str(dec(p['cost_cny']) - cost)
    p['qty'] -= qty
    record(a, cmd, 'SELL', code=p['code'], trade_id=p['trade_id'], qty=qty,
           price=str(price), fx=str(fx), fee_cny=fees,
           pnl_cny=str(gross-fee-cost), reason=reason)
    if not p['qty']:
        del a['positions'][p['code']]


def apply_command(state, config, cmd):
    a = state[cmd['account']]
    at = stamp(cmd['at'])
    if a['last_at'] and at < stamp(a['last_at']):
        raise ValueError('out-of-order command')
    kind = cmd['kind']
    rules = config['rules']
    if kind == 'SIGNAL':
        s = copy.deepcopy(cmd['signal'])
        if stamp(s['cutoff']) > stamp(s['available_at']) or stamp(s['available_at']) > at:
            raise ValueError('signal time inversion')
        if s['id'] in a['signals']:
            if a['signals'][s['id']]['original'] != s:
                raise ValueError('immutable signal ID conflict')
            return
        if s.get('scope') != 'forward_simulation':
            raise ValueError('research/real scope cannot enter simulation')
        if s.get('passed'):
            evidence(s)
            if s['covered'] != s['denominator'] or s['denominator'] <= 0:
                raise ValueError('incomplete coverage cannot be full-pool signal')
            if cmd['account'] == 'U' and s['denominator'] != config['u_denominator']:
                raise ValueError('U universe mismatch')
            if cmd['account'] == 'O' and (s.get('engine') != 'original_native_dsa' or
                    s.get('upstream_commit') != config['o_upstream_commit']):
                raise ValueError('custom adapter is not original DSA')
            if s.get('data_news_plan_verified') is not True:
                raise ValueError('data/news/plan acceptance missing')
        a['signals'][s['id']] = {'original': s, 'filled': False, 'attempts': []}
        record(a, cmd, 'SIGNAL' if s.get('passed') else 'WAIT', signal_id=s['id'],
               reason=s.get('reason', ''), evidence_hash=canonical_hash(s))
    elif kind == 'MARK':
        for code, q in cmd['quotes'].items():
            quote_price(q, cmd['at'])
            a['marks'][code] = copy.deepcopy(q)
        nav=portfolio_value(a,cmd['at'])
        a['nav_history'].append({'at':cmd['at'],'nav_cny':str(nav)})
        record(a, cmd, 'MARK',nav_cny=str(nav))
    elif kind == 'ENTRY':
        sig = a['signals'][cmd['signal_id']]
        s = sig['original']
        if sig['filled'] or not s.get('passed'):
            record(a, cmd, 'NO_TRADE', reason='signal_blocked_or_already_filled')
            return
        if stamp(cmd['at']) <= stamp(s['available_at']):
            raise ValueError('entry before signal availability')
        if s.get('valid_until') and at > stamp(s['valid_until']):
            record(a,cmd,'NO_TRADE',reason='signal_expired')
            return
        q = cmd['quote']
        price, fx = quote_price(q, cmd['at'])
        if q['at'] != cmd['at']:
            raise ValueError('entry must use execution time')
        if q.get('first_eligible_price_verified') is not True:
            raise ValueError('first eligible tradable price unverified')
        if q.get('mode') == 'daily_open':
            if q.get('next_session_verified') is not True or q.get('session') != s.get('next_session'):
                raise ValueError('next trading session unverified')
        elif q.get('mode') != 'tick':
            raise ValueError('execution mode unsupported')
        code = cmd['code']
        # Fallback candidates must carry explicit exclusion evidence for higher ranks.
        top = sorted(s['top3'], key=lambda x: (x['rank'], x['code']))
        selected = None
        for candidate in top[:3]:
            if candidate['code'] in a['positions']:
                continue
            if candidate['code'] in cmd.get('excluded', {}):
                evidence(cmd['excluded'][candidate['code']])
                continue
            selected = candidate
            break
        if not selected or selected['code'] != code:
            raise ValueError('not first eligible Top3 candidate')
        if selected.get('action') != 'BUY' or not selected.get('buyable_verified'):
            record(a, cmd, 'NO_TRADE', reason='native_action_or_eligibility')
            return
        if len(a['positions']) >= rules['max_positions']:
            record(a, cmd, 'NO_TRADE', reason='position_count_cap')
            return
        nav = portfolio_value(a, cmd['at'])
        invested = nav-dec(a['cash'])
        industry = selected['industry']
        industry_value = sum(dec(p['qty'])*dec(a['marks'][c]['price'])*dec(a['marks'][c]['cny_per_hkd'])
                             for c,p in a['positions'].items() if p['industry']==industry)
        cap = min(dec(rules['total_cap']), dec(s.get('total_cap', rules['total_cap'])))
        budget = min(dec(rules['ticket_cny']), nav*dec(rules['ticket_cap']),
                     nav*cap-invested, nav*dec(rules['industry_cap'])-industry_value,
                     dec(a['cash']))
        fee = cmd.get('fee_cny')
        # Unknown entry fees block sizing rather than inventing zero-cost purchases.
        if fee is None:
            record(a, cmd, 'NO_TRADE', reason='entry_fee_unknown')
            return
        fee = dec(fee)
        if fee < 0:
            raise ValueError('negative fee')
        lot = int(q['lot_size'])
        if lot <= 0 or lot != q['lot_size'] or not q.get('lot_verified'):
            raise ValueError('board lot unverified')
        qty = max(0,int(((budget-fee)/(price*fx*lot)).to_integral_value(rounding=ROUND_FLOOR))*lot)
        if qty < 3*lot:
            record(a, cmd, 'NO_TRADE', reason='less_than_three_lots_for_thirds')
            return
        cost = dec(qty)*price*fx+fee
        trade_id = canonical_hash([cmd['account'],s['id'],code])
        p = {'code':code,'trade_id':trade_id,'qty':qty,'original_qty':qty,
             'lot':lot,'industry':industry,'entry_price':str(price),'cost_cny':str(cost),
             'entry_at':cmd['at'],'entry_score':selected.get('score'),
             'entry_rank':selected['rank'],'stage':0,'outside3':0,'outside10':0,
             'rank_snapshots':[],'exit_pending':False,'processed_bars':[], 'alerts':[]}
        a['positions'][code] = p
        a['cash'] = str(dec(a['cash'])-cost)
        sig['filled'] = True
        record(a,cmd,'BUY',code=code,trade_id=trade_id,qty=qty,price=str(price),
               fx=str(fx),fee_cny=str(fee),signal_id=s['id'])
    elif kind == 'RANK':
        evidence(cmd)
        if cmd.get('complete_comparable_snapshot') is not True:
            record(a,cmd,'RANK_UNKNOWN',reason='incomplete_or_incomparable_ranking')
            return
        for code,p in a['positions'].items():
            if cmd['snapshot_id'] in p['rank_snapshots']:
                continue
            row = cmd['ranks'].get(code)
            if row is None:
                record(a,cmd,'RANK_UNKNOWN',code=code,reason='missing_stock_not_rank_decay')
                continue
            rank= row['rank'];score=row.get('score')
            p['rank_snapshots'].append(cmd['snapshot_id'])
            p['outside3'] = p['outside3']+1 if rank>3 else 0
            p['outside10'] = p['outside10']+1 if rank>10 else 0
            loss = (Decimal(1)-dec(score)/dec(p['entry_score'])) if score is not None and p['entry_score'] and dec(p['entry_score'])>0 else Decimal(0)
            severe = p['outside10']>=2 or (loss>=dec(rules['severe_score_drop']) and rank>p['entry_rank']) or row.get('action')=='NO' or row.get('verified_material_negative') is True
            moderate = p['outside3']>=2 or loss>=dec(rules['moderate_score_drop'])
            if severe and p['stage']==2:
                p['exit_pending']=True
                p['exit_pending_at']=cmd['at']
            record(a,cmd,'RANK_SEVERE' if severe else 'RANK_WARNING' if moderate else 'RANK_NORMAL',code=code)
    elif kind == 'BAR':
        code=cmd['code']
        if code not in a['positions']:
            record(a,cmd,'NO_POSITION',code=code)
            return
        p=a['positions'][code];b=cmd['bar'];evidence(b)
        if b['id'] in p['processed_bars']:
            return
        if p.get('last_bar_close') and stamp(b['open_at']) <= stamp(p['last_bar_close']):
            raise ValueError('overlapping bar would repeat price path')
        if stamp(b['close_at'])>at or stamp(b['open_at'])<stamp(p['entry_at']):
            raise ValueError('bar unavailable or includes time before entry')
        if b.get('adjustment')!='raw' or b.get('corporate_actions_verified') is not True:
            raise ValueError('raw bar/corporate action verification required')
        if b.get('corporate_action'):
            record(a,cmd,'BLOCKED_CORPORATE_ACTION',code=code)
            return
        if b.get('suspended'):
            record(a,cmd,'WAIT_SUSPENDED',code=code)
            return
        o,h,l,c = (dec(b[k]) for k in ('open','high','low','close'))
        if not (0<l<=min(o,c)<=max(o,c)<=h):
            raise ValueError('invalid OHLC')
        evidence(b['fx_evidence']);fx=dec(b['cny_per_hkd'])
        if fx<=0 or stamp(b['fx_evidence']['at'])>stamp(b['open_at']):
            raise ValueError('invalid/future bar FX')
        p['processed_bars'].append(b['id'])
        p['last_bar_close']=b['close_at']
        entry=dec(p['entry_price']);stop=entry*(Decimal(1)-dec(rules['stop'])) if p['stage']==0 else entry
        fees=cmd.get('fee_cny_by_exit',{})
        if p['exit_pending'] and stamp(b['open_at']) > stamp(p['exit_pending_at']):
            sell(a,cmd,p,p['qty'],o,fx,'RANK_EXIT',fees.get('RANK_EXIT'))
        elif l<=stop:
            sell(a,cmd,p,p['qty'],min(o,stop),fx,'STOP',fees.get('STOP'))
        else:
            for stage,target in ((0,dec(rules['tp1'])),(1,dec(rules['tp2']))):
                if p['stage']==stage and h>=entry*(Decimal(1)+target):
                    qty=(p['original_qty']//(3*p['lot']))*p['lot']
                    reason=f'TP{stage+1}'
                    sell(a,cmd,p,qty,max(o,entry*(Decimal(1)+target)),fx,reason,fees.get(reason))
                    p['stage']+=1
                    # With daily bars, after TP1 a return to breakeven may have happened.
                    if l<=entry and code in a['positions']:
                        sell(a,cmd,p,p['qty'],entry,fx,'AMBIGUOUS_BREAKEVEN',fees.get('AMBIGUOUS_BREAKEVEN'))
                        break
            if code in a['positions']:
                for pct in range(20,1001,10):
                    if h>=entry*(Decimal(1)+Decimal(pct)/100) and pct not in p['alerts']:
                        p['alerts'].append(pct);record(a,cmd,'RUNNER_REVIEW',code=code,gain_pct=pct)
        record(a,cmd,'BAR_PROCESSED',code=code,bar_id=b['id'],daily_order_policy='stop_first_then_conservative_breakeven')
    else:
        raise ValueError('unsupported command')
    a['last_at']=cmd['at']


def replay(journal):
    if canonical_hash(journal['config'])!=journal['config_hash']:
        raise ValueError('configuration mutated')
    state=initial(journal['config']);parent=journal['config_hash'];ids=set()
    for item in journal['commands']:
        cmd=item['command']
        if cmd['id'] in ids or item['parent']!=parent or item['hash']!=canonical_hash({'parent':parent,'command':cmd}):
            raise ValueError('journal hash/ID conflict')
        ids.add(cmd['id']);apply_command(state,journal['config'],cmd);parent=item['hash']
    return state


def append(journal, cmd):
    replay(journal)
    for item in journal['commands']:
        if item['command']['id']==cmd['id']:
            if item['command']!=cmd:
                raise ValueError('immutable command ID conflict')
            return journal
    result=copy.deepcopy(journal)
    parent=result['commands'][-1]['hash'] if result['commands'] else result['config_hash']
    item={'parent':parent,'command':copy.deepcopy(cmd)};item['hash']=canonical_hash(item)
    result['commands'].append(item);replay(result)
    return result


def save_atomic(path, journal, expected_hash=None):
    """CAS protects a local checkout. Remote persistence must ALSO use version CAS."""
    import fcntl
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with Path(str(path)+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        current=canonical_hash(json.loads(path.read_text())) if path.exists() else None
        if current!=expected_hash:
            raise ValueError('journal changed; reload and replay, never overwrite')
        replay(journal)
        fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.journal-')
        try:
            with os.fdopen(fd,'w') as handle:
                json.dump(journal,handle,ensure_ascii=False,indent=2,allow_nan=False)
                handle.flush();os.fsync(handle.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)


def summary(journal):
    state=replay(journal);out={}
    for key,a in state.items():
        buys=[e for e in a['events'] if e['kind']=='BUY'];sells=[e for e in a['events'] if e['kind']=='SELL']
        closed={}
        for e in sells:
            closed[e['trade_id']]=closed.get(e['trade_id'],Decimal(0))+dec(e['pnl_cny'])
        for p in a['positions'].values():closed.pop(p['trade_id'],None)
        wins=sum(v>0 for v in closed.values());losses=sum(v<0 for v in closed.values())
        peak=dec(journal['config']['accounts'][key]);mdd=Decimal(0)
        for row in a['nav_history']:
            nav=dec(row['nav_cny']);peak=max(peak,nav);mdd=max(mdd,(peak-nav)/peak)
        out[key]={'cash_cny':a['cash'],'positions':a['positions'],'buy_count':len(buys),
                  'sell_count':len(sells),'wait_count':sum(e['kind'] in ('WAIT','NO_TRADE') for e in a['events']),
                  'realized_pnl_cny':str(sum((dec(e['pnl_cny']) for e in sells),Decimal(0))),
                  'net_performance_verified':a['fees_known'],
                  'closed_trades':len(closed),
                  'win_rate':str(Decimal(wins)/len(closed)) if closed and a['fees_known'] else None,
                  'loss_rate':str(Decimal(losses)/len(closed)) if closed and a['fees_known'] else None,
                  'sampled_nav_max_drawdown':str(mdd) if a['nav_history'] and a['fees_known'] else None,
                  'nav_history':a['nav_history'],
                  'reason':'sampled NAV drawdown only; missing fees makes net metrics N/A',
                  'events':a['events']}
    return {'scope':'forward_simulation','config_hash':journal['config_hash'],
            'journal_hash':canonical_hash(journal),'accounts':out,'real_orders':0}
