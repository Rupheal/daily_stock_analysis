"""Offline historical source replay; preserves absent data and all seven engines."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.hk_research_replay import parse_fred_csv, parse_hkex_southbound, parse_sse_southbound

SERIES = {
    'SP500': ('A', 'index points; price index, not total return'),
    'NASDAQCOM': ('A', 'index points; price index'),
    'VIXCLS': ('A', 'index points; close'),
    'DGS10': ('B', 'percent; constant maturity yield'),
    'DGS2': ('B', 'percent; constant maturity yield'),
    'NIKKEI225': ('C', 'index points; Japanese close, not Asian opening quote'),
    'DEXJPUS': ('C', 'JPY per USD; daily reference, not intraday'),
    'DEXCHUS': ('D', 'onshore CNY per USD; NOT offshore CNH'),
    'DCOILBRENTEU': ('E', 'USD per barrel; Brent spot, not futures'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results, daily, monthly = [], {}, []
    for series, (engine, unit) in SERIES.items():
        result = {'series': series, 'engine': engine, 'unit': unit,
                  'url': 'https://fred.stlouisfed.org/series/'+series,
                  'historical_pit_verified': False, 'vintage_status': 'downloaded_now; first publication archive unavailable'}
        try:
            raw = (args.sources/(series+'.csv')).read_bytes()
            observations = parse_fred_csv(raw.decode(), series)
            result.update(status='parsed', sha256=hashlib.sha256(raw).hexdigest(), rows=len(observations),
                          nonmissing=sum(r['value'] is not None for r in observations),
                          first_date=observations[0]['date'], last_date=observations[-1]['date'])
            daily[series] = {r['date']: r['value'] for r in observations}
            months = defaultdict(list)
            for row in observations:
                if row['value'] is not None:
                    months[row['date'][:7]].append(row)
            for month, values in months.items():
                first, last = values[0], values[-1]
                a, b = Decimal(first['value']), Decimal(last['value'])
                monthly.append({'series': series, 'month': month, 'first_observed_date': first['date'],
                                'last_observed_date': last['date'], 'first_value': str(a), 'last_value': str(b),
                                'change_in_source_units': str(b-a), 'observations': len(values),
                                'label': 'first-to-last available observation, not full calendar-month return'})
        except Exception as exc:
            result.update(status='failed', error=type(exc).__name__+': '+str(exc))
        results.append(result)
    flows = []
    for path in sorted(args.sources.glob('flow-*.js'))+sorted(args.sources.glob('sse-flow-*.jsonp')):
        record = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        try:
            code = path.stem.split('-')[-1]
            day = code[:4]+'-'+code[4:6]+'-'+code[6:]
            decoder = parse_sse_southbound if path.name.startswith('sse-') else parse_hkex_southbound
            record.update(status='parsed', facts=decoder(path.read_text(), day))
        except Exception as exc:
            record.update(status='failed', error=str(exc))
        flows.append(record)
    diagnostic = []
    sp, vix = daily.get('SP500', {}), daily.get('VIXCLS', {})
    previous = None
    for day in sorted(set(sp)|set(vix)):
        current = (sp.get(day), vix.get(day))
        # A missing series is not forward-filled or dropped from the coverage audit.
        if None in current:
            diagnostic.append({'date': day, 'status': 'incomplete_observation'})
            continue
        if previous:
            prev_day, prev_sp, prev_vix = previous
            delta_sp = (Decimal(current[0])/Decimal(prev_sp)-1)*100
            delta_vix = Decimal(current[1])-Decimal(prev_vix)
            diagnostic.append({'date': day, 'previous_joint_observation': prev_day,
                               'sp500_change_pct': str(delta_sp), 'vix_change_points': str(delta_vix),
                               'same_us_session_sp_down_vix_up': delta_sp < 0 and delta_vix > 0,
                               'status': 'descriptive_co_movement; not HK-time-available signal'})
        previous = (day, *current)
    missing = {
        'A': ['SOX and sector breadth', 'historical exact availability'],
        'B': ['real rates and contemporaneous Fed expectations', 'vintage timestamps'],
        'C': ['TOPIX/KOSPI/KOSDAQ/KRW and Asian opening snapshots'],
        'D': ['HSI/HSTECH/CSI300 verified historical series', 'CNH and HIBOR histories'],
        'E': ['WTI/gold and dated war-event classifications'],
        'F': ['complete primary speech catalogue', '15-minute/Asia-open/stock confirmations'],
        'G': ['complete two-channel daily history', 'verified foreign/local/passive investor flows'],
    }
    variants = [{'variant': 'full' if engine is None else 'without_'+engine,
                 'removed_engine': engine, 'strategy_metrics': None,
                 'status': 'not_estimable; no frozen tradable strategy or complete PIT inputs'} for engine in [None, *missing]]
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'scope': '2025-04-01 through 2026-09-11; source/clock/coverage mechanism replay only',
              'series_denominator': len(SERIES), 'series_parsed': sum(x['status']=='parsed' for x in results),
              'series': results, 'monthly_observations': monthly, 'flow_records': flows,
              'us_joint_diagnostics': diagnostic, 'engines_denominator': 7, 'engine_gaps': missing,
              'point_in_time_historical_predictions': 0, 'strategy_validated': False,
              'macro_regime': None, 'position_limit': None, 'quantitative_weights': None,
              'baseline_and_ablation': variants,
              'baseline_requirements': ['HSI price benchmark with identical sessions', 'cash benchmark with currency/rate assumptions',
                                        'O vs U system comparison separately; different universes and inputs'],
              'returns_after_costs': None, 'drawdown': None, 'historical_orders': [],
              'conclusion': 'Evidence supports source-level historical observations, not predictive or trading validity.'}
    (args.output/'mechanism-replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ('scope','series_parsed','series_denominator','point_in_time_historical_predictions','strategy_validated')},ensure_ascii=False))


if __name__ == '__main__':
    main()
