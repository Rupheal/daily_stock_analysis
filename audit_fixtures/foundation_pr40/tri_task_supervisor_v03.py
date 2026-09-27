#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone, timedelta

RETRYABLE={'CONTEXT_ROLLOVER','TRANSIENT_CAPACITY','STREAM_LOST','HEARTBEAT_STALE','UNKNOWN_STALL'}
TERMINAL={'ACCEPTED','FAILED','DEAD_LETTER','CANCELLED'}
BACKOFF_SECONDS=(120,300,600,1200,1800)
EXTERNAL_PATTERN_IMMEDIATE={'UNKNOWN_STALL'}
EXTERNAL_PATTERN_MARKERS=(
    'THIRD_PARTY','MCP','SESSION','CONCURRENCY','RESOURCE_CONFLICT',
    'AUTH','OAUTH','TRANSPORT','NETWORK','VERSION_MISMATCH',
    'ENVIRONMENT_MISMATCH','PERMISSION','SECURITY'
)

def external_pattern_gate_required(r,failure_class,detail):
    """Stop blind retries for nontrivial technical failures.

    Pure policy classification only; external research is performed by the
    control worker and validated by external_pattern_gate.py.
    """
    text=str(detail or '').upper()
    if failure_class in EXTERNAL_PATTERN_IMMEDIATE:return True
    if any(marker in text for marker in EXTERNAL_PATTERN_MARKERS):return True
    if failure_class in {'CONTEXT_ROLLOVER','TRANSIENT_CAPACITY'}:return False
    return int(r.get('attempt') or 0)>=2 and failure_class in RETRYABLE

def parse_ts(value):
    if value is None: return None
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('TIMESTAMP_TIMEZONE_MISSING')
    return dt.astimezone(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def retry_delay_seconds(step): return BACKOFF_SECONDS[min(max(step,0),len(BACKOFF_SECONDS)-1)]
def clear_lease(r): r['lease']={'owner':None,'lease_id':None,'acquired_at':None,'expires_at':None}
def lease_seconds(r):
    # Original acquired_at is immutable. Deriving duration from renewed expiry
    # inflated the lease on every heartbeat. Old records use the 600s policy.
    return r['lease'].get('duration_seconds',600)
def lease_valid(r,lease_id,now,owner=None,attempt=None):
    lease=r.get('lease') or {}
    if r.get('state')!='RUNNING' or not lease_id or lease.get('lease_id')!=lease_id:
        raise ValueError('INVALID_LEASE')
    acquired=parse_ts(lease.get('acquired_at')); expires=parse_ts(lease.get('expires_at'))
    if not acquired or not expires or now<acquired or now>=expires:
        raise ValueError('LEASE_EXPIRED_OR_INVALID')
    if owner is not None and lease.get('owner')!=owner: raise ValueError('LEASE_OWNER_MISMATCH')
    if attempt is not None and r.get('attempt')!=attempt: raise ValueError('LEASE_ATTEMPT_MISMATCH')
    return True
def renew_lease(r,now):
    if r['lease'].get('lease_id'): r['lease']['expires_at']=iso(now+timedelta(seconds=lease_seconds(r)))
def heartbeat_dead(r,now):
    if r['state']!='RUNNING': return False
    lease=r.get('lease') or {}; beat=r.get('heartbeat') or {}
    expiry=parse_ts(lease.get('expires_at'))
    if expiry is None or now>=expiry: return True
    at=parse_ts(beat.get('at') or lease.get('acquired_at') or r.get('updated_at'))
    return at is None or at>now or now>=at+timedelta(seconds=beat.get('timeout_seconds',360))
def schedule_retry(r,now):
    if r['attempt']>=r['max_attempts']:
        r['state']='DEAD_LETTER'; r['failure']['retryable']=False; r['updated_at']=iso(now); clear_lease(r); return r
    step=r['retry']['backoff_step']; r['state']='RETRY_BACKOFF'; r['retry']['retry_after']=iso(now+timedelta(seconds=retry_delay_seconds(step))); r['retry']['backoff_step']=step+1; r['updated_at']=iso(now); clear_lease(r); return r
def watchdog_tick(r,now):
    if r['state'] in TERMINAL: return r
    if (r.get('dispatch') or {}).get('state') in {'SUBMITTING','UNKNOWN'} and heartbeat_dead(r,now):
        r['state']='STALLED'; r['failure']={'class':'WAIT_DEPENDENCY','retryable':False,'detail':'DELIVERY_RECONCILIATION_REQUIRED; never blindly resubmit'}; r['updated_at']=iso(now); clear_lease(r); return r
    if heartbeat_dead(r,now):
        r['state']='STALLED'; r['failure']={'class':'HEARTBEAT_STALE','retryable':True,'detail':'heartbeat timeout'}; r['updated_at']=iso(now); clear_lease(r); return schedule_retry(r,now)
    if r['state']=='STALLED' and r.get('failure',{}).get('retryable') is True: return schedule_retry(r,now)
    if r['state'] in {'RETRY_BACKOFF','WAIT_CAPACITY'}:
        ra=parse_ts(r['retry']['retry_after'])
        if ra and now>=ra: r['state']='QUEUED'; r['retry']['retry_after']=None; r['updated_at']=iso(now)
    return r
def can_claim(r): return r['state']=='QUEUED' and r['attempt']<r['max_attempts']
def claim(r,owner,lease_id,now,lease_seconds_=600):
    if not can_claim(r): raise ValueError('task not claimable')
    if not owner or not lease_id or not 60<=lease_seconds_<=3600: raise ValueError('INVALID_CLAIM')
    r['attempt']+=1; r['state']='RUNNING'; r['updated_at']=iso(now); r['lease']={'owner':owner,'lease_id':lease_id,'acquired_at':iso(now),'expires_at':iso(now+timedelta(seconds=lease_seconds_)),'duration_seconds':lease_seconds_}; r['heartbeat']['at']=iso(now)
    if r['pulse']['current']==0: r['pulse']['current']=1
    return r
def heartbeat(r,lease_id,progress_seq,summary,checkpoint_ref,checkpoint_hash,now,owner=None,attempt=None):
    lease_valid(r,lease_id,now,owner,attempt)
    old_at=parse_ts(r['heartbeat'].get('at'))
    if old_at and now<old_at: raise ValueError('HEARTBEAT_TIME_REGRESSION')
    if progress_seq<r['heartbeat']['progress_seq']: raise ValueError('progress_seq regression')
    r['heartbeat'].update({'at':iso(now),'progress_seq':progress_seq,'summary':summary,'checkpoint_ref':checkpoint_ref,'checkpoint_hash':checkpoint_hash}); r['updated_at']=iso(now); renew_lease(r,now); return r
def bind_resource_heartbeat(r,broker_state,broker,now):
    """Renew every claim as one Supervisor pulse; any stale fence fails closed."""
    state=broker_state
    refreshed=[]
    for claim in r.get('active_resource_claims') or []:
        state=broker.heartbeat(state,claim['resource_id'],claim['claim_id'],claim['epoch'],now)
        refreshed.append({**claim,'heartbeat_at':iso(now)})
    r['active_resource_claims']=refreshed;r['resource_heartbeat']={'at':iso(now)}
    return r,state

def managed_resource_heartbeat(r,lease_id,progress_seq,summary,checkpoint_ref,checkpoint_hash,
                               broker_state,broker,now,owner=None,attempt=None):
    """One managed heartbeat path for Task lease + all held Resource leases."""
    heartbeat(r,lease_id,progress_seq,summary,checkpoint_ref,checkpoint_hash,now,owner,attempt)
    if r.get('active_resource_claims'):
        return bind_resource_heartbeat(r,broker_state,broker,now)
    return r,broker_state
def require_drain_on_yield(r):
    if r.get('active_resource_claims'):
        r['drain_state']={'state':'DRAINING','reason':'WORKER_YIELD','finalizers_pending':True}
    return r
def begin_resource_drain(r,broker_state,broker,now):
    state=broker_state
    for claim in r.get('active_resource_claims') or []:
        state=broker.begin_drain(state,claim['resource_id'],claim['claim_id'],claim['epoch'],now)
        claim['state']='DRAINING'
    require_drain_on_yield(r)
    return r,state
def complete_pulse(r,lease_id,summary,checkpoint_ref,checkpoint_hash,now,task_complete=False,worker_yield=False):
    if task_complete: raise ValueError('INDEPENDENT_ACCEPTANCE_REQUIRED; worker may only submit completion evidence')
    seq=r['heartbeat']['progress_seq']+1; heartbeat(r,lease_id,seq,summary,checkpoint_ref,checkpoint_hash,now)
    r['pulse']['completed']+=1; r['pulse']['last_completed_at']=iso(now)
    r['pulse']['current']+=1
    if not r['pulse'].get('auto_chain',True):
        r['state']='QUEUED'; clear_lease(r); return r
    if worker_yield:
        require_drain_on_yield(r)
        r['state']='QUEUED'; clear_lease(r); return r
    # auto-chain: same worker keeps lease and immediately starts next bounded pulse
    r['state']='RUNNING'; renew_lease(r,now); return r
def classify_worker_failure(r,failure_class,detail,now):
    if r['state'] in TERMINAL: return r
    if failure_class not in RETRYABLE|{'FINAL_QUOTA','WAIT_OWNER','WAIT_DEPENDENCY','PERMANENT_FAILURE'}: failure_class='UNKNOWN_STALL'
    r['failure']={'class':failure_class,'retryable':failure_class in RETRYABLE,'detail':detail}; r['updated_at']=iso(now); clear_lease(r)
    if external_pattern_gate_required(r,failure_class,detail):
        r['state']='WAIT_DEPENDENCY'
        r['failure']['retryable']=False
        r['failure']['detail']='EXTERNAL_PATTERN_GATE_REQUIRED; '+str(detail or '')
        r['retry']['retry_after']=None
        return r
    if failure_class=='TRANSIENT_CAPACITY':
        if r['attempt']>=r['max_attempts']: r['state']='DEAD_LETTER'; r['failure']['retryable']=False; r['retry']['retry_after']=None; return r
        step=r['retry']['backoff_step']; r['state']='WAIT_CAPACITY'; r['retry']['retry_after']=iso(now+timedelta(seconds=retry_delay_seconds(step))); r['retry']['backoff_step']=step+1
    elif failure_class=='FINAL_QUOTA': r['state']='WAIT_QUOTA'; r['retry']['retry_after']=None
    elif failure_class=='WAIT_OWNER': r['state']='WAIT_OWNER'
    elif failure_class=='WAIT_DEPENDENCY': r['state']='WAIT_DEPENDENCY'
    elif failure_class=='PERMANENT_FAILURE': r['state']='FAILED'
    else: r['state']='STALLED'; schedule_retry(r,now)
    return r
