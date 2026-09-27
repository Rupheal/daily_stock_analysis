#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, os
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
RUNTIME_DIR=ROOT/'runtime'
OUTBOX_DIR=ROOT/'outbox'
SUP_PATH=ROOT/'tri_task_supervisor_v03.py'
DISP_PATH=ROOT/'tri_dispatcher.py'
PROJECT_RECOVERY_PATH=ROOT/'reliability'/'project_autorecovery.py'

spec=importlib.util.spec_from_file_location('sup3',SUP_PATH)
sup=importlib.util.module_from_spec(spec); spec.loader.exec_module(sup)
dspec=importlib.util.spec_from_file_location('disp',DISP_PATH)
disp=importlib.util.module_from_spec(dspec); dspec.loader.exec_module(disp)
pspec=importlib.util.spec_from_file_location('project_recovery',PROJECT_RECOVERY_PATH)
project_recovery=importlib.util.module_from_spec(pspec); pspec.loader.exec_module(project_recovery)

def load(p):
    with Path(p).open('r',encoding='utf-8') as f:return json.load(f)

def save(p,o):
    p=Path(p); tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(o,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\n')
    tmp.replace(p)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')

def state_counts(rows):
    counts={}
    for row in rows:
        s=row.get('state','UNKNOWN')
        counts[s]=counts.get(s,0)+1
    return counts

def resource_health(state,now):
    claims=[c for rows in state.get('claims',{}).values() for c in rows]
    return {'queue_depth':len(state.get('queue',[])),
      'waiting_tasks':[state['requests'][x]['task_id'] for x in state.get('queue',[])],
      'draining':sum(c.get('state')=='DRAINING' for c in claims),
      'quarantined':sum(c.get('state')=='QUARANTINED' for c in claims),
      'orphan_session_count':sum(sum(s.get('state')=='RUNNING' for s in c.get('sessions',[])) for c in claims),
      'stale_fences':sum(c.get('state')=='QUARANTINED' for c in claims),
      'paid_reservations':sum(x.get('state')=='RESERVED' for x in state.get('reservations',{}).values())}

def build_tick_payload(now, changed, runtime_rows, env=None, outbox_rows=None):
    env=env or {}; outbox_rows=outbox_rows or []
    return {
        'schema_version':1,
        'watchdog_id':'TRIDENT_DURABLE_WATCHDOG',
        'observed_at':iso(now),
        'event_name':env.get('GITHUB_EVENT_NAME'),
        'schedule_expression':env.get('TRI_WATCHDOG_SCHEDULE'),
        'github_run_id':env.get('GITHUB_RUN_ID'),
        'github_run_attempt':env.get('GITHUB_RUN_ATTEMPT'),
        'github_sha':env.get('GITHUB_SHA'),
        'changed_files':changed,
        'changed_count':len(changed),
        'runtime_count':len(runtime_rows),
        'state_counts':state_counts(runtime_rows),
        'outbox_count':len(outbox_rows),
        'outbox_state_counts':state_counts(outbox_rows),
        'material_state_change':bool(changed),
        'authority_note':'Tick artifact is observability evidence only; it is not research Authority.'
    }

def reconcile_external_observations(runtime_rows,observations,now):
    """Read-only incident proposals. The trusted writer applies plans after CAS.

    Observations must be supplied by a pinned, authenticated adapter. This
    function never fabricates a remote run or treats an artifact as acceptance.
    """
    proposals=[]; rmap={r['task_id']:r for r in runtime_rows}
    for o in observations:
        tid=o.get('task_id'); r=rmap.get(tid)
        if r is None:
            proposals.append({'task_id':tid,'class':'UNREGISTERED_OBSERVATION','action':'RECONCILE_ONLY'});continue
        intent=(r.get('dispatch') or {}).get('intent',{})
        if intent and (o.get('event_id')!=intent.get('event_id') or o.get('code_sha')!=intent.get('code_sha')):
            proposals.append({'task_id':tid,'class':'STALE_INPUT','action':'FAIL_CLOSED'});continue
        base={'task_id':tid,'chain_id':o.get('chain_id')}
        completed=(o.get('workflow_status')=='completed' and o.get('workflow_conclusion') in (None,'success'))
        if completed and o.get('artifact_present') and not o.get('acceptance_verified'):
            proposals.append({**base,'class':'ARTIFACT_UNCONSUMED','action':'VERIFY_NOT_PROMOTE'})
        if o.get('acceptance_verified') and not o.get('next_action_committed'):
            proposals.append({**base,'class':'ACCEPTED_WITHOUT_NEXT_ACTION_COMMIT',
                              'action':'ATOMIC_WRITEBACK_AND_OUTBOX_REQUIRED'})
        if o.get('acceptance_verified') and o.get('next_action_committed') and not o.get('dispatch_acknowledged'):
            proposals.append({**base,'class':'NEXT_ACTION_UNDISPATCHED','action':'RECONCILE_THEN_DISPATCH'})
        if (o.get('chain_classification')=='AUTO_CONTINUE' and completed
                and o.get('artifact_present') and not o.get('downstream_progress_observed')):
            proposals.append({**base,'class':'AUTO_CONTINUE_CHAIN_STALLED_AFTER_ARTIFACT',
                              'action':'VERIFY_WRITEBACK_THEN_DISPATCH_NEXT'})
        if r.get('state')=='QUEUED' and o.get('queued_age_seconds',0)>o.get('queue_timeout_seconds',600):
            proposals.append({'task_id':tid,'class':'RUNNER_OR_DISPATCH_DELAY','action':'CHECK_RUNNER_AND_DELIVERY'})
        if o.get('runner_online') is False:
            proposals.append({'task_id':tid,'class':'RUNNER_OFFLINE','action':'RESOURCE_WAIT'})
    return proposals

def project_recovery_proposals(observations):
    """Convert pinned project observations into pure, bounded recovery plans.

    Plans do not perform the repair. The existing trusted writer/dispatcher must
    persist and execute any allowed next action under CAS. Unknown observations
    fail closed in project_autorecovery.plan().
    """
    proposals=[]
    for o in observations:
        project=o.get('project')
        failure=o.get('failure_class')
        if not project or not failure:
            continue
        verdict=project_recovery.guarded_plan(project,o)
        verdict['task_id']=o.get('task_id')
        verdict['chain_id']=o.get('chain_id')
        proposals.append(verdict)
    return proposals

def reconcile_outbox_records(outbox_rows):
    """Read committed outbox state and emit fail-closed delivery proposals only.

    The watchdog never submits work from here. PREPARED means a committed next
    action is awaiting dispatcher delivery. SUBMITTING/UNKNOWN must reconcile by
    idempotency lookup and may never be treated as safe for blind resubmission.
    DELIVERED requires a receipt to count as transport-complete.
    """
    proposals=[]
    for outbox in outbox_rows:
        intent=outbox.get('intent') or {}
        next_action=outbox.get('next_action') or {}
        tid=intent.get('task_id') or next_action.get('task_id')
        base={'task_id':tid,'idempotency_key':outbox.get('idempotency_key')}
        state=outbox.get('state')
        if state=='PREPARED':
            proposals.append({**base,'class':'NEXT_ACTION_UNDISPATCHED','action':'RECONCILE_THEN_DISPATCH'})
        elif state in {'SUBMITTING','UNKNOWN'}:
            proposals.append({**base,'class':'OUTBOX_DELIVERY_UNCERTAIN','action':'LOOKUP_RECEIPT_NEVER_BLIND_RESEND'})
        elif state=='DELIVERED':
            if not outbox.get('receipt'):
                proposals.append({**base,'class':'OUTBOX_RECEIPT_MISSING','action':'FAIL_CLOSED'})
        elif state=='CANCELLED':
            continue
        else:
            proposals.append({**base,'class':'OUTBOX_STATE_INVALID','action':'FAIL_CLOSED'})
    return proposals

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--tick-out',type=Path)
    ap.add_argument('--observations',type=Path,help='Pinned external observations; incident proposals only, never automatic acceptance')
    args=ap.parse_args(argv)

    now=datetime.now(timezone.utc); changed=[]
    for p in sorted(RUNTIME_DIR.glob('TRI-TASK-*.json')):
        before=load(p); after=json.loads(json.dumps(before))
        sup.watchdog_tick(after,now)
        if after!=before:
            save(p,after)
            disp.sync_task_state(after['task_id'],after['state'])
            changed.append(str(p.relative_to(ROOT.parent.parent)))

    rows=[load(p) for p in sorted(RUNTIME_DIR.glob('TRI-TASK-*.json'))]
    outbox_rows=[load(p) for p in sorted(OUTBOX_DIR.glob('*.json'))]
    payload=build_tick_payload(now,changed,rows,os.environ,outbox_rows)
    payload['outbox_incident_proposals']=reconcile_outbox_records(outbox_rows)
    resource_path=ROOT/'SHARED_RESOURCE_STATE_v1.json'
    if resource_path.exists(): payload['resources']=resource_health(load(resource_path),now)
    if args.observations:
        observed=load(args.observations)
        if not isinstance(observed,list): raise ValueError('OBSERVATIONS_LIST_REQUIRED')
        payload['external_incident_proposals']=reconcile_external_observations(rows,observed,now)
        payload['project_recovery_proposals']=project_recovery_proposals(observed)
    if args.tick_out:
        args.tick_out.parent.mkdir(parents=True,exist_ok=True)
        save(args.tick_out,payload)
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
