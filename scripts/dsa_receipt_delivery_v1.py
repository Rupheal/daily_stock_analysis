"""Immutable isolated file-store publication and consumer observations.

This is a local/shared-directory transport, not proof of GitHub/Drive publication.
No acceptance is issued here. External acceptance provenance needs authentication
by the existing authority reader; this module checks bytes and event ordering.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def digest(raw): return hashlib.sha256(raw).hexdigest()
def encode(value): return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
def clock(): return datetime.now(timezone.utc).isoformat()
def timestamp(value):
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('NAIVE_EVENT_TIME')
    return d

def immutable(path, raw):
    """Atomic no-replace commit; concurrent identical writers are harmless."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.delivery-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
        try: os.link(tmp,path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=raw: raise ValueError('DELIVERY_CONTENT_CONFLICT')
    finally: Path(tmp).unlink(missing_ok=True)


def verify(directory, expected):
    directory=Path(directory)
    if not re.fullmatch('[0-9a-f]{64}',expected): raise ValueError('DIGEST_INVALID')
    if directory.is_symlink(): raise ValueError('DELIVERY_SYMLINK')
    paths=[directory/x for x in ('receipt.json','generation.json','manifest.json')]
    if any(p.is_symlink() for p in paths): raise ValueError('DELIVERY_SYMLINK')
    raw,graw,mraw=[p.read_bytes() for p in paths]
    g=json.loads(graw);m=json.loads(mraw);receipt=json.loads(raw)
    if m.get('transport')!='ISOLATED_FILE_STORE' or m.get('formal_acceptance_issued') is not False:
        raise ValueError('DELIVERY_MANIFEST_CONTRACT')
    if digest(raw)!=expected or m.get('receipt_sha256')!=expected or g.get('receipt_sha256')!=expected:
        raise ValueError('DELIVERY_RECEIPT_DRIFT')
    if m.get('generation_sha256')!=digest(graw): raise ValueError('DELIVERY_GENERATION_DRIFT')
    if g.get('target_session')!=receipt.get('target_session') or g.get('account') not in ('O','U'):
        raise ValueError('DELIVERY_PROVENANCE_MISMATCH')
    timestamp(g['generation_observed_at'])
    return raw,g,m


def publish(receipt, generation, root):
    raw=Path(receipt).read_bytes();graw=Path(generation).read_bytes();g=json.loads(graw)
    sha=digest(raw);root=Path(root);dest=root/sha;stage=root/('.'+sha+'.incomplete')
    if g.get('receipt_sha256')!=sha: raise ValueError('GENERATION_RECEIPT_MISMATCH')
    if timestamp(g['generation_observed_at'])>timestamp(clock()): raise ValueError('FUTURE_GENERATION')
    manifest=encode({'schema_version':1,'receipt_sha256':sha,'generation_sha256':digest(graw),
                     'transport':'ISOLATED_FILE_STORE','formal_acceptance_issued':False})
    if not dest.exists():
        stage.mkdir(parents=True,exist_ok=True)
        if stage.is_symlink(): raise ValueError('DELIVERY_SYMLINK')
        expected={'receipt.json':raw,'generation.json':graw,'manifest.json':manifest}
        if set(p.name for p in stage.iterdir())-set(expected): raise ValueError('UNKNOWN_PARTIAL_OUTPUT')
        for name,content in expected.items(): immutable(stage/name,content)
        verify(stage,sha)
        try: stage.rename(dest)
        except OSError:
            if not dest.exists(): raise
    _,_,m=verify(dest,sha)
    if (dest/'generation.json').read_bytes()!=graw or (dest/'manifest.json').read_bytes()!=manifest:
        raise ValueError('DELIVERY_PUBLICATION_CONFLICT')
    # Crash after rename: recover with a new observation, never invent the first
    # publish instant. Even normal success reports an observation, not first availability.
    event=dest/'publication.json'
    if not event.exists():
        value={'schema_version':1,'event':'PUBLICATION_OBSERVED','receipt_sha256':sha,
               'generation_sha256':m['generation_sha256'],'observed_at':clock(),
               'location':str(dest.resolve()),'transport':'ISOLATED_FILE_STORE',
               'first_publication_at':None,'formal_accepted_at':None}
        try: immutable(event,encode(value))
        except ValueError:
            if not event.exists(): raise
    observed=json.loads(event.read_bytes())
    if (event.is_symlink() or observed.get('receipt_sha256')!=sha
            or observed.get('generation_sha256')!=digest(graw)
            or observed.get('location')!=str(dest.resolve())
            or observed.get('event')!='PUBLICATION_OBSERVED'
            or timestamp(observed['observed_at'])<timestamp(g['generation_observed_at'])):
        raise ValueError('PUBLICATION_EVENT_DRIFT')
    return dest


def consume(directory,expected,observation):
    raw,g,m=verify(directory,expected);directory=Path(directory)
    pubraw=(directory/'publication.json').read_bytes();pub=json.loads(pubraw)
    if ((directory/'publication.json').is_symlink() or pub.get('event')!='PUBLICATION_OBSERVED'
            or pub.get('generation_sha256')!=m['generation_sha256']
            or pub.get('receipt_sha256')!=expected or pub.get('location')!=str(directory.resolve())):
        raise ValueError('PUBLICATION_EVENT_DRIFT')
    if not timestamp(g['generation_observed_at'])<=timestamp(pub['observed_at'])<=timestamp(clock()):
        raise ValueError('DELIVERY_EVENT_ORDER')
    observation=Path(observation)
    if observation.is_symlink(): raise ValueError('OBSERVATION_SYMLINK')
    if observation.resolve().is_relative_to(directory.resolve()): raise ValueError('OBSERVATION_MUST_BE_SEPARATE')
    if observation.exists():
        value=json.loads(observation.read_bytes())
        if (value.get('receipt_sha256')!=expected or value.get('publication_sha256')!=digest(pubraw)
                or value.get('location')!=str(directory.resolve()) or value.get('event')!='CONSUMER_BYTES_OBSERVED'):
            raise ValueError('CONSUMER_RETRY_DRIFT')
    else:
        value={'schema_version':1,'event':'CONSUMER_BYTES_OBSERVED','receipt_sha256':expected,
               'publication_sha256':digest(pubraw),'location':str(directory.resolve()),
               'observed_at':clock(),'earliest_global_availability_claimed':False}
        immutable(observation,encode(value))
    if not timestamp(g['generation_observed_at'])<=timestamp(pub['observed_at'])<=timestamp(value['observed_at'])<=timestamp(clock()):
        raise ValueError('DELIVERY_EVENT_ORDER')
    return raw,value


def check_chain(directory,consumer_path,acceptance_path,acceptance_sha,timing,now):
    """Validate supplied authority evidence; never create or authenticate it."""
    expected=timing['receipt_sha256'];raw,g,_=verify(directory,expected)
    pubraw=(Path(directory)/'publication.json').read_bytes();pub=json.loads(pubraw)
    craw=Path(consumer_path).read_bytes();c=json.loads(craw)
    araw=Path(acceptance_path).read_bytes();a=json.loads(araw)
    if digest(araw)!=acceptance_sha: raise ValueError('ACCEPTANCE_BYTES_DRIFT')
    if not a.get('authority_reference') or a.get('accepted') is not True: raise ValueError('EXTERNAL_ACCEPTANCE_REQUIRED')
    for event in (pub,c,a):
        if event.get('receipt_sha256')!=expected: raise ValueError('CHAIN_RECEIPT_MISMATCH')
    if c.get('publication_sha256')!=digest(pubraw) or a.get('consumer_sha256')!=digest(craw):
        raise ValueError('CHAIN_EVENT_MISMATCH')
    if pub.get('location')!=str(Path(directory).resolve()) or c.get('location')!=pub['location']:
        raise ValueError('CHAIN_LOCATION_MISMATCH')
    if a.get('account')!=g['account'] or a.get('target_session')!=g['target_session']:
        raise ValueError('ACCEPTANCE_SCOPE_MISMATCH')
    if pub.get('event')!='PUBLICATION_OBSERVED' or c.get('event')!='CONSUMER_BYTES_OBSERVED':
        raise ValueError('CHAIN_EVENT_TYPE')
    if pub.get('generation_sha256')!=digest((Path(directory)/'generation.json').read_bytes()):
        raise ValueError('CHAIN_GENERATION_MISMATCH')
    if timing.get('field_evidence',{}).get('available_at',{}).get('sha256')!=digest(craw):
        raise ValueError('AVAILABILITY_REFERENCE_MISMATCH')
    t=timing['signal_timing']
    # This candidate deliberately uses the observed consumer time as a conservative
    # availability boundary, not as evidence of first/global availability.
    if t['available_at']!=c['observed_at']: raise ValueError('AVAILABILITY_NOT_CONSUMER_OBSERVATION')
    ordered=[t['cutoff'],g['generation_observed_at'],pub['observed_at'],c['observed_at'],a['accepted_at'],a['frozen_at'],now]
    if any(timestamp(x)>timestamp(y) for x,y in zip(ordered,ordered[1:])): raise ValueError('CHAIN_TIME_ORDER')
    hk=ZoneInfo('Asia/Hong_Kong');session=g['target_session']
    for x in (t['cutoff'],c['observed_at'],a['accepted_at'],a['frozen_at']):
        d=timestamp(x).astimezone(hk)
        if d.date().isoformat()!=session or (d.hour,d.minute,d.second,d.microsecond)>(9,25,0,0):
            raise ValueError('LATE_OR_NON_MORNING_CHAIN')
    return {'state':'CHAIN_STRUCTURALLY_VALID','receipt_sha256':expected,
            'consumer_sha256':digest(craw),'external_acceptance_sha256':acceptance_sha,
            'authority_authenticated_by_this_tool':False,'production_activated':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('publish');a.add_argument('--receipt',type=Path,required=True);a.add_argument('--generation',type=Path,required=True);a.add_argument('--root',type=Path,required=True)
    b=sub.add_parser('consume');b.add_argument('--directory',type=Path,required=True);b.add_argument('--sha256',required=True);b.add_argument('--observation',type=Path,required=True)
    v=p.parse_args()
    if v.command=='publish': print(json.dumps({'directory':str(publish(v.receipt,v.generation,v.root)),'production_activated':False}))
    else:
        _,event=consume(v.directory,v.sha256,v.observation);print(json.dumps(event))
if __name__=='__main__': main()
