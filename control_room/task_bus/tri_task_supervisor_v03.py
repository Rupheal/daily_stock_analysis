#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import re

RETRYABLE={'CONTEXT_ROLLOVER','TRANSIENT_CAPACITY','STREAM_LOST','HEARTBEAT_STALE','UNKNOWN_STALL'}
TERMINAL={'ACCEPTED','FAILED','DEAD_LETTER','CANCELLED'}
BACKOFF_SECONDS=(120,300,600,1200,1800)

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
def complete_pulse(r,lease_id,summary,checkpoint_ref,checkpoint_hash,now,task_complete=False,worker_yield=False):
    if task_complete: raise ValueError('INDEPENDENT_ACCEPTANCE_REQUIRED; worker may only submit completion evidence')
    seq=r['heartbeat']['progress_seq']+1; heartbeat(r,lease_id,seq,summary,checkpoint_ref,checkpoint_hash,now)
    r['pulse']['completed']+=1; r['pulse']['last_completed_at']=iso(now)
    r['pulse']['current']+=1
    if not r['pulse'].get('auto_chain',True):
        r['state']='QUEUED'; clear_lease(r); return r
    if worker_yield:
        r['state']='QUEUED'; clear_lease(r); return r
    # auto-chain: same worker keeps lease and immediately starts next bounded pulse
    r['state']='RUNNING'; renew_lease(r,now); return r
def classify_worker_failure(r,failure_class,detail,now):
    if r['state'] in TERMINAL: return r
    if failure_class not in RETRYABLE|{'FINAL_QUOTA','WAIT_OWNER','WAIT_DEPENDENCY','PERMANENT_FAILURE'}: failure_class='UNKNOWN_STALL'
    r['failure']={'class':failure_class,'retryable':failure_class in RETRYABLE,'detail':detail}; r['updated_at']=iso(now); clear_lease(r)
    if failure_class=='TRANSIENT_CAPACITY':
        if r['attempt']>=r['max_attempts']: r['state']='DEAD_LETTER'; r['failure']['retryable']=False; r['retry']['retry_after']=None; return r
        step=r['retry']['backoff_step']; r['state']='WAIT_CAPACITY'; r['retry']['retry_after']=iso(now+timedelta(seconds=retry_delay_seconds(step))); r['retry']['backoff_step']=step+1
    elif failure_class=='FINAL_QUOTA': r['state']='WAIT_QUOTA'; r['retry']['retry_after']=None
    elif failure_class=='WAIT_OWNER': r['state']='WAIT_OWNER'
    elif failure_class=='WAIT_DEPENDENCY': r['state']='WAIT_DEPENDENCY'
    elif failure_class=='PERMANENT_FAILURE': r['state']='FAILED'
    else: r['state']='STALLED'; schedule_retry(r,now)
    return r

PERSISTENCE_VERIFIED="REMOTE_READBACK_VERIFIED"
_HEX40=re.compile(r"^[0-9a-f]{40}$")
_HEX64=re.compile(r"^[0-9a-f]{64}$")

def require_remote_persistence(persistence):
    if not isinstance(persistence,dict) or persistence.get("state")!=PERSISTENCE_VERIFIED:
        raise ValueError("REMOTE_PERSISTENCE_NOT_VERIFIED")
    if persistence.get("verified_by")!="CONTROL_ROOM_REMOTE_READBACK":
        raise ValueError("PERSISTENCE_VERIFIER_NOT_CONTROL_ROOM")
    if not _HEX64.fullmatch(str(persistence.get("binding_hash") or "")):
        raise ValueError("PERSISTENCE_BINDING_HASH_INVALID")
    if not _HEX40.fullmatch(str(persistence.get("remote_head") or "")):
        raise ValueError("PERSISTENCE_REMOTE_HEAD_INVALID")
    return True

def independent_accept(r,verifier,receipt_ref,receipt_hash,persistence,now):
    """Independent acceptance is impossible until durable remote persistence is proven."""
    if r.get("state")=="ACCEPTED": return r
    if r.get("state") in {"FAILED","DEAD_LETTER","CANCELLED"}: raise ValueError("TERMINAL_TASK_NOT_ACCEPTABLE")
    if not verifier or not receipt_ref or not _HEX64.fullmatch(str(receipt_hash or "")):
        raise ValueError("INDEPENDENT_ACCEPTANCE_RECEIPT_REQUIRED")
    require_remote_persistence(persistence)
    r["state"]="ACCEPTED"; r["updated_at"]=iso(now); clear_lease(r)
    r["last_external_receipt"]=receipt_ref
    r["persistence"]=persistence
    return r
