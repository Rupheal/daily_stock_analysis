"""Clock-ordered descriptive replay of cached prices, never a strategy backtest.

Each US observation maps once to the first later observed Hong Kong session.
Archive vintages and publication times remain unverified; no PIT or OOS claim.
"""
import argparse
from bisect import bisect_right
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.services.hk_research_replay import parse_fred_csv, append_observation_outcome


def valid_price_rows(payload, symbol):
    if payload.get('symbol') != symbol:
        raise ValueError('Historical symbol mismatch')
    rows, seen = [], set()
    for raw in payload['rows']:
        day = raw['Date'][:10]
        datetime.strptime(day,'%Y-%m-%d')
        if day in seen or (rows and day <= rows[-1]['date']):
            raise ValueError('Duplicate or unsorted historical prices')
        seen.add(day)
        values={k:Decimal(str(raw[k])) for k in ['Open','High','Low','Close','Volume']}
        if not all(x.is_finite() for x in values.values()):
            raise ValueError('Non-finite historical value')
        if not 0 < values['Low'] <= min(values['Open'],values['Close']) <= max(values['Open'],values['Close']) <= values['High'] or values['Volume']<0:
            raise ValueError('Invalid historical OHLCV')
        rows.append({'date':day,**{k.lower():str(v) for k,v in values.items()}})
    return rows


def clock_pairs(hk_rows, sp, vix):
    """Keep the most recent US observation before each HK session, once only."""
    days=sorted(d for d in set(sp)&set(vix) if sp[d] is not None and vix[d] is not None)
    used, pairs, excluded=set(),[],[]
    for row in hk_rows:
        # Strict date inequality avoids using a later US close in the HK morning.
        index=bisect_right(days,row['date'])-1
        if index>=0 and days[index]==row['date']:
            index-=1
        if index<1:
            excluded.append({'date':row['date'],'reason':'insufficient_prior_US_history'});continue
        latest,prior=days[index],days[index-1]
        if latest in used:
            excluded.append({'date':row['date'],'reason':'US_observation_already_used'});continue
        used.add(latest)
        sp_change=(Decimal(sp[latest])/Decimal(sp[prior])-1)*100
        vix_change=Decimal(vix[latest])-Decimal(vix[prior])
        pairs.append({'hk_date':row['date'],'us_date':latest,'prior_us_date':prior,
                      'sp500_change_pct':str(sp_change),'vix_change_points':str(vix_change),
                      'sp_down_vix_up':sp_change<0 and vix_change>0,
                      'hsi_open_to_close_pct':str((Decimal(row['close'])/Decimal(row['open'])-1)*100),
                      'historical_pit_verified':False,'kind':'clock_ordered_archival_co_movement'})
    return pairs,excluded


def describe(rows):
    if not rows:
        return {'n':0,'mean_pct':None,'positive_fraction':None}
    values=[Decimal(r['hsi_open_to_close_pct']) for r in rows]
    return {'n':len(values),'mean_pct':str(sum(values)/len(values)),
            'positive_fraction':str(Decimal(sum(v>0 for v in values))/len(values)),
            'min_pct':str(min(values)),'max_pct':str(max(values))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--observations',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    files=['HSI-history-log.json','1810.HK-history-log.json','SP500.csv','VIXCLS.csv']
    hashes={n:hashlib.sha256((args.sources/n).read_bytes()).hexdigest() for n in files}
    hsi=valid_price_rows(json.loads((args.sources/files[0]).read_text()),'^HSI')
    xiaomi=valid_price_rows(json.loads((args.sources/files[1]).read_text()),'1810.HK')
    if [x['date'] for x in hsi] != [x['date'] for x in xiaomi]:
        raise ValueError('Historical price date sets differ')
    series={name:{r['date']:r['value'] for r in parse_fred_csv((args.sources/(name+'.csv')).read_text(),name)} for name in ['SP500','VIXCLS']}
    pairs,excluded=clock_pairs(hsi,series['SP500'],series['VIXCLS'])
    summaries=[]
    for year in ['2025','2026','all']:
        rows=[r for r in pairs if year=='all' or r['hk_date'].startswith(year)]
        for group in [True,False]:
            summaries.append({'period':year,'sp_down_vix_up':group,**describe([r for r in rows if r['sp_down_vix_up']==group])})
    # Source-date event windows: not historical order entries or causal effects.
    events=[]
    for day in ['2025-04-02','2025-04-09','2025-05-12']:
        future=[i for i,r in enumerate(hsi) if r['date']>day]
        start=future[0] if future else None
        for horizon in [1,3,5,10,20]:
            end=None if start is None else start+horizon-1
            event={'source_date':day,'horizon':horizon,'availability_time_verified':False,
                   'causal_effect':None,'strategy_return':None}
            if end is None or end>=len(hsi):
                event['status']='missing_observation_window'
            else:
                event.update(status='descriptive_only',start_session=hsi[start]['date'],end_session=hsi[end]['date'])
                for name,rows in [('hsi',hsi),('xiaomi',xiaomi)]:
                    event[name+'_open_to_end_close_pct']=str((Decimal(rows[end]['close'])/Decimal(rows[start]['open'])-1)*100)
            events.append(event)
    now=datetime.now(timezone.utc).isoformat()
    outcomes=[]
    for original in sorted(args.observations.glob('*.json')):
        if '.h' in original.stem:continue
        record=json.loads(original.read_text())
        # No verified post-freeze session exists in this historical source set.
        if any(r['date']>record['available_at'][:10] for r in hsi):
            raise ValueError('New observation prices require verified actual session metadata')
        for horizon in [1,3,5,10,20]:
            outcomes.append(append_observation_outcome(original,horizon,[],now,record['reference_close']))
    report={'generated_at':now,'source_hashes':hashes,'hsi_rows':len(hsi),'xiaomi_rows':len(xiaomi),
            'unique_pairs':len(pairs),'excluded':excluded,'period_group_summaries':summaries,
            'pairs':pairs,'event_windows':events,'forward_observations':outcomes,
            'status':'DESCRIPTIVE_REPLAY_ONLY','genuine_out_of_sample_results':0,'historical_pit_predictions':0,
            'strategy_return':None,'net_return':None,'numeric_regime_weights':None,
            'limits':['Source dates are not verified availability timestamps.',
                      '2025/2026 are retrospective stability slices; both already inspected, neither a held-out validation set.',
                      'Groups describe archived co-movement, not causal attribution or a calibrated prediction.',
                      'Returns are open-to-close reference changes, not fills, costs or strategy P&L.',
                      'US holidays reuse no signal; HK date set is observed prices, not independently certified complete calendar.']}
    (args.output/'clock-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:report[k] for k in ['status','hsi_rows','unique_pairs','period_group_summaries','forward_observations']},ensure_ascii=False))


if __name__=='__main__':main()
