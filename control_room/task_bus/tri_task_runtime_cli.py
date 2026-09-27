#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SUP_PATH=ROOT/'tri_task_supervisor_v03.py'
DISP_PATH=ROOT/'tri_dispatcher.py'
spec=importlib.util.spec_from_file_location('sup',SUP_PATH); sup=importlib.util.module_from_spec(spec); spec.loader.exec_module(sup)
dspec=importlib.util.spec_from_file_location('disp',DISP_PATH); disp=importlib.util.module_from_spec(dspec); dspec.loader.exec_module(disp)
def now(): return datetime.now(timezone.utc)
def load(path):
    with Path(path).open('r',encoding='utf-8') as f:return json.load(f)
def save(path,obj):
    p=Path(path); tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f: json.dump(obj,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\n')
    tmp.replace(p)
def task_id_from_runtime(r): return r['task_id']

def main():
    ap=argparse.ArgumentParser(description='TRIDENT worker runtime CLI v0.4')
    ap.add_argument('runtime',type=Path); sp=ap.add_subparsers(dest='cmd',required=True)
    c=sp.add_parser('claim'); c.add_argument('--owner',required=True); c.add_argument('--lease-id',required=True)
    h=sp.add_parser('heartbeat'); h.add_argument('--lease-id',required=True); h.add_argument('--seq',type=int,required=True); h.add_argument('--summary',required=True); h.add_argument('--checkpoint-ref'); h.add_argument('--checkpoint-hash')
    pc=sp.add_parser('pulse-complete'); pc.add_argument('--lease-id',required=True); pc.add_argument('--summary',required=True); pc.add_argument('--checkpoint-ref',required=True); pc.add_argument('--checkpoint-hash',required=True); pc.add_argument('--task-complete',action='store_true'); pc.add_argument('--yield-worker',action='store_true')
    f=sp.add_parser('fail'); f.add_argument('--class-name',required=True); f.add_argument('--detail',required=True); f.add_argument('--lease-id',required=True)
    for command in (h,pc,f):
        command.add_argument('--owner',required=True); command.add_argument('--attempt',type=int,required=True)
    ac=sp.add_parser('accept'); ac.add_argument('--verifier',required=True); ac.add_argument('--receipt-ref',required=True); ac.add_argument('--receipt-hash',required=True); ac.add_argument('--persistence-evidence',type=Path,required=True)
    sp.add_parser('watchdog'); sp.add_parser('show')
    a=ap.parse_args(); r=load(a.runtime); t=now(); tid=task_id_from_runtime(r)
    if a.cmd=='claim':
        q=disp.load(disp.QUEUE); limit=q['global_wip_limit']
        if disp.running_count()>=limit: raise SystemExit(f'WIP limit reached: {limit}')
        qrow=next((x for x in q['tasks'] if x['task_id']==tid),None)
        if not qrow or qrow['state']!='QUEUED': raise SystemExit('task must be QUEUED before claim')
        sup.claim(r,a.owner,a.lease_id,t)
    elif a.cmd=='heartbeat': sup.heartbeat(r,a.lease_id,a.seq,a.summary,a.checkpoint_ref,a.checkpoint_hash,t,a.owner,a.attempt)
    elif a.cmd=='pulse-complete':
        sup.lease_valid(r,a.lease_id,t,a.owner,a.attempt)
        sup.complete_pulse(r,a.lease_id,a.summary,a.checkpoint_ref,a.checkpoint_hash,t,a.task_complete,a.yield_worker)
    elif a.cmd=='fail':
        sup.lease_valid(r,a.lease_id,t,a.owner,a.attempt)
        sup.classify_worker_failure(r,a.class_name,a.detail,t)
    elif a.cmd=='accept': sup.independent_accept(r,a.verifier,a.receipt_ref,a.receipt_hash,load(a.persistence_evidence),t)
    elif a.cmd=='watchdog': sup.watchdog_tick(r,t)
    elif a.cmd=='show': print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    save(a.runtime,r); disp.sync_task_state(tid,r['state'])
    print(json.dumps({'task_id':tid,'state':r['state'],'attempt':r['attempt'],'pulse':r['pulse'],'heartbeat':r['heartbeat'],'retry':r['retry'],'failure':r['failure']},ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
