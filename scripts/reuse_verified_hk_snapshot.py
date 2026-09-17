"""Reuse a complete same-session public snapshot without pretending to refetch it."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

def reuse(cache, session, out):
    cache=Path(cache);out=Path(out)
    manifest=json.loads((cache/'MANIFEST.json').read_text())
    if manifest['official_session']!=session:raise ValueError('STALE_OFFICIAL_CACHE')
    payloads={}
    for name in ('O_UNIVERSE.json','U_UNIVERSE.json','U45_NEWS_MULTISOURCE.json'):
        raw=(cache/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=manifest['files'][name]:raise ValueError('CACHE_HASH_MISMATCH')
        payloads[name]=(raw,json.loads(raw))
    o=payloads['O_UNIVERSE.json'][1];u=payloads['U_UNIVERSE.json'][1]
    if not o.get('full_union_verified') or o.get('effective_session')!=session:raise ValueError('UNVERIFIED_POOL')
    for d in (o,u):
        if d['member_count']!=len(d['members']) or len({m['code'] for m in d['members']})!=d['member_count']:raise ValueError('DENOMINATOR_MISMATCH')
        observed=datetime.fromisoformat(d['observed_at_utc'])
        if observed.tzinfo is None or observed>datetime.now(timezone.utc):raise ValueError('UNKNOWN_OR_FUTURE_AVAILABILITY')
    if u['member_count']!=45 or u['effective_session']!=session:raise ValueError('U_POOL_MISMATCH')
    out.mkdir(parents=True,exist_ok=True)
    for name,(raw,_) in payloads.items():(out/name).write_bytes(raw)
    receipt={**manifest,'reused_at':datetime.now(timezone.utc).isoformat(),'cloud_refetch':False}
    (out/'CACHE_REUSE_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return {'O_denominator':o['member_count'],'U_denominator':45,'reused_prior_verified_sources':True,'cloud_refetch':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cache',required=True);p.add_argument('--session',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(reuse(a.cache,a.session,a.out)))
