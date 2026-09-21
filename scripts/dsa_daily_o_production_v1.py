#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor,as_completed
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path
import httpx
from dsa_daily_formal_packet_v1 import build_o
from aggregate_o_formal_ranking_v3 import aggregate
from finalize_o_formal_acceptance_v3 import finalize

UPSTREAM='089d9d26d68f8b839ea5a74a3784e4402925f8b7'
DAILY_MAX=Decimal('65.70')
PER_MEMBER=Decimal('0.10')

def run(cmd,cwd=None,env=None,timeout=None):
    subprocess.check_call(cmd,cwd=cwd,env=env,timeout=timeout)

def provider_capacity():
    with httpx.Client(timeout=20) as c:
        r=c.get('https://api.deepseek.com/user/balance',headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']});r.raise_for_status();d=r.json()
    rows=[x for x in d.get('balance_infos',[]) if x.get('currency')=='CNY']
    if not d.get('is_available') or len(rows)!=1:return 0
    bal=Decimal(rows[0]['total_balance']);usable=max(Decimal('0'),min(bal-Decimal('0.50'),DAILY_MAX))
    return int((usable/PER_MEMBER).to_integral_value(rounding=ROUND_FLOOR))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--research-root',type=Path,required=True);ap.add_argument('--original-root',type=Path,required=True)
    ap.add_argument('--target-session',required=True);ap.add_argument('--snapshot-dir',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args();root=a.research_root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    od=a.snapshot_dir/'O_UNIVERSE.json'
    data=out/'market'
    run([sys.executable,str(root/'scripts/run_hk_native_data_probe.py'),'--checkout',str(a.original_root.resolve()),'--universe',str(od),'--scope','O_full_pool_data_only','--expected-date',a.target_session,'--decision-session',a.target_session,'--expected-commit',UPSTREAM,'--target-boundary-adapter','--timeout','1800','--output',str(data)])
    universe=json.loads(od.read_text());coverage=json.loads((data/'coverage.json').read_text())
    packet=build_o(universe,coverage,__import__('hashlib').sha256(od.read_bytes()).hexdigest(),__import__('hashlib').sha256((data/'market-history.json').read_bytes()).hexdigest(),a.target_session)
    for name in ('policy','ledger','scope'):(out/(name+'.json')).write_text(json.dumps(packet[name],ensure_ascii=False,indent=2)+'\n')
    status={'schema_version':1,'target_session':a.target_session,'state':'DRY_RUN_PREFLIGHT' if a.dry_run else 'PREFLIGHT_READY','official_denominator':packet['official_denominator'],'operational_denominator':packet['operational_denominator'],'excluded_count':packet['excluded_count'],'daily_budget_ceiling_cny':str(DAILY_MAX),'per_member_cap_cny':str(PER_MEMBER),'real_orders':0}
    if a.dry_run:
        (out/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status));return
    capacity=provider_capacity();op=packet['operational_denominator']
    if capacity<op:
        status.update(state='WAIT_BUDGET_CAPACITY',affordable_calls=capacity)
        (out/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status));return
    from plan_o657_rollout_v3 import build_plan
    plan=build_plan(universe,packet['policy'],packet['ledger'],op,16);(out/'PLAN.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    scope=packet['scope'];scopes=[];codes=[]
    for sh in plan['shards']:
        sid=sh['shard_id'];cp=out/f'codes-{sid}.json';sp=out/f'scope-{sid}.json'
        cp.write_text(json.dumps(sh['codes'],ensure_ascii=False)+'\n')
        s=dict(scope);s.update({'shard_id':sid,'run_id':scope['run_id']+'-S'+sid,'maximum_requests':sh['maximum_requests'],'maximum_cost_cny':sh['maximum_cost_cny'],'maximum_authorized_cost_cny':sh['maximum_cost_cny'],'artifact_prefix':scope['artifact_prefix']+'-S'+sid})
        sp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');scopes.append((sid,sp,cp))
    env=dict(os.environ);env.update(ENV_FILE='/dev/null',ENABLE_REALTIME_QUOTE='false',ENABLE_REALTIME_TECHNICAL_INDICATORS='false',PREFETCH_REALTIME_QUOTES='false',BACKTEST_ENABLED='false',NEWS_INTEL_AUTO_FETCH_ENABLED='false',AGENT_MODE='false',REPORT_INTEGRITY_RETRY='0',MAX_WORKERS='1')
    def one(x):
        sid,sp,cp=x;dest=out/f'shard-{sid}'
        cmd=[sys.executable,str(root/'scripts/run_hk_o_operational_shard_v3.py'),'--checkout',str(a.original_root.resolve()),'--cache',str((data/'market-history.json').resolve()),'--universe',str(od.resolve()),'--policy',str((out/'policy.json').resolve()),'--scope',str(sp.resolve()),'--codes-file',str(cp.resolve()),'--out',str(dest)]
        p=subprocess.run(cmd,cwd=root,env=env,timeout=10800);return sid,p.returncode,dest
    results=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fs=[ex.submit(one,x) for x in scopes]
        for f in as_completed(fs):results.append(f.result())
    sources=[]
    for sid,rc,dest in results:
        p=dest/'SHARD_RESULT.json'
        if p.exists():sources.append((f'SHARD_{sid}',json.loads(p.read_text())))
        else:sources.append((f'SHARD_{sid}',{'members':[]}))
    rank=aggregate(universe,packet['policy'],sources);rank['run_id']='DSA-O-DAILY-'+a.target_session.replace('-','')
    acc=finalize(rank,packet['policy'])
    (out/'RANKING.json').write_text(json.dumps(rank,ensure_ascii=False,indent=2)+'\n')
    (out/'O_FORMAL.json').write_text(json.dumps(acc,ensure_ascii=False,indent=2)+'\n')
    status.update(state='GENERATED' if acc['status']=='ACCEPTED_O_FORMAL_TOP3' else 'NOT_ACCEPTED',formal_status=acc['status'],qualified_buy_in_Top3=acc.get('qualified_buy_in_Top3'),missing_count=acc.get('missing_count'))
    (out/'STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n');print(json.dumps(status))
if __name__=='__main__':main()
