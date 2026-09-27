#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SUP_PATH=ROOT/'tri_task_supervisor_v03.py'
DISP_PATH=ROOT/'tri_dispatcher.py'
BROKER_PATH=ROOT/'shared_resource_broker.py'
BROKER_STATE=ROOT/'SHARED_RESOURCE_STATE_v1.json'
BROKER_REGISTRY=ROOT/'SHARED_RESOURCE_REGISTRY_v1.json'
spec=importlib.util.spec_from_file_location('sup',SUP_PATH); sup=importlib.util.module_from_spec(spec); spec.loader.exec_module(sup)
dspec=importlib.util.spec_from_file_location('disp',DISP_PATH); disp=importlib.util.module_from_spec(dspec); dspec.loader.exec_module(disp)
bspec=importlib.util.spec_from_file_location('broker',BROKER_PATH); broker=importlib.util.module_from_spec(bspec); bspec.loader.exec_module(broker)
def now(): return datetime.now(timezone.utc)
def load(path):
    with Path(path).open('r',encoding='utf-8') as f:return json.load(f)
def save(path,obj):
    p=Path(path); tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f: json.dump(obj,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\n')
    tmp.replace(p)
def task_id_from_runtime(r): return r['task_id']

def broker_cas(transform,max_conflicts=8):
    store=broker.JsonCASStore(BROKER_STATE)
    for _ in range(max_conflicts):
        state,version=store.read()
        updated,result=transform(state)
        try:
            store.commit(version,updated)
            return updated,result
        except broker.CASConflict:
            continue
    raise SystemExit('BROKER_STATE_CAS_RETRY_EXHAUSTED')

def drain_runtime_claims(runtime,timestamp):
    def transform(state):
        _,updated=sup.begin_resource_drain(runtime,state,broker,timestamp)
        return updated,None
    if runtime.get('active_resource_claims'):
        broker_cas(transform)

def main():
    ap=argparse.ArgumentParser(description='TRIDENT worker runtime CLI v0.4')
    ap.add_argument('runtime',type=Path); sp=ap.add_subparsers(dest='cmd',required=True)
    c=sp.add_parser('claim'); c.add_argument('--owner',required=True); c.add_argument('--lease-id',required=True)
    h=sp.add_parser('heartbeat'); h.add_argument('--lease-id',required=True); h.add_argument('--seq',type=int,required=True); h.add_argument('--summary',required=True); h.add_argument('--checkpoint-ref'); h.add_argument('--checkpoint-hash')
    pc=sp.add_parser('pulse-complete'); pc.add_argument('--lease-id',required=True); pc.add_argument('--summary',required=True); pc.add_argument('--checkpoint-ref',required=True); pc.add_argument('--checkpoint-hash',required=True); pc.add_argument('--task-complete',action='store_true'); pc.add_argument('--yield-worker',action='store_true')
    f=sp.add_parser('fail'); f.add_argument('--class-name',required=True); f.add_argument('--detail',required=True); f.add_argument('--lease-id',required=True)
    for command in (h,pc,f):
        command.add_argument('--owner',required=True); command.add_argument('--attempt',type=int,required=True)
    sp.add_parser('watchdog'); sp.add_parser('show')
    a=ap.parse_args(); r=load(a.runtime); t=now(); tid=task_id_from_runtime(r)
    if a.cmd=='claim':
        q=disp.load(disp.QUEUE); limit=q['global_wip_limit']
        if disp.running_count()>=limit: raise SystemExit(f'WIP limit reached: {limit}')
        qrow=next((x for x in q['tasks'] if x['task_id']==tid),None)
        if not qrow or qrow['state']!='QUEUED': raise SystemExit('task must be QUEUED before claim')
        if not sup.can_claim(r): raise SystemExit('runtime must be claimable before resource grant')
        packet=load(disp.task_path(tid)); registry=load(BROKER_REGISTRY)
        def acquire_resources(state):
            updated,runtime,status=disp.prepare_resource_dispatch(packet,r,registry,state,a.owner,a.lease_id,t)
            return updated,(runtime,status)
        if packet.get('required_resources'):
            state,(resource_runtime,status)=broker_cas(acquire_resources)
            r.clear();r.update(resource_runtime)
            if status=='WAIT_RESOURCE':
                save(a.runtime,r)
                print(json.dumps({'task_id':tid,'state':r['state'],'attempt':r['attempt'],
                    'resource_status':status,'resource_request':r['resource_request']},indent=2))
                return 0
            disp.validate_resource_gate(r,packet.get('required_resources'),broker,state,t)
        sup.claim(r,a.owner,a.lease_id,t)
    elif a.cmd=='heartbeat':
        sup.heartbeat(r,a.lease_id,a.seq,a.summary,a.checkpoint_ref,a.checkpoint_hash,t,a.owner,a.attempt)
        if r.get('active_resource_claims'):
            def renew(state): return sup.bind_resource_heartbeat(r,state,broker,t)[1],None
            broker_cas(renew)
    elif a.cmd=='pulse-complete':
        sup.lease_valid(r,a.lease_id,t,a.owner,a.attempt)
        if a.yield_worker: drain_runtime_claims(r,t)
        sup.complete_pulse(r,a.lease_id,a.summary,a.checkpoint_ref,a.checkpoint_hash,t,a.task_complete,a.yield_worker)
    elif a.cmd=='fail':
        sup.lease_valid(r,a.lease_id,t,a.owner,a.attempt)
        if r.get('active_resource_claims'): drain_runtime_claims(r,t)
        sup.classify_worker_failure(r,a.class_name,a.detail,t)
    elif a.cmd=='watchdog': sup.watchdog_tick(r,t)
    elif a.cmd=='show': print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    save(a.runtime,r); disp.sync_task_state(tid,r['state'])
    print(json.dumps({'task_id':tid,'state':r['state'],'attempt':r['attempt'],'pulse':r['pulse'],'heartbeat':r['heartbeat'],'retry':r['retry'],'failure':r['failure']},ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
