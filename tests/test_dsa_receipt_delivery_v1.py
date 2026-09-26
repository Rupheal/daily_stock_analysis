"""Synthetic clocks/evidence only. No formal acceptance is produced."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from scripts import dsa_receipt_delivery_v1 as d
from scripts.dsa_formal_receipt_resolver_v1 import resolve
from scripts.dsa_formal_timing_seal_v1 import write_candidate

DAY='2026-09-24'
def t(h):return DAY+'T'+h+'+08:00'

def fixture(tmp_path,monkeypatch):
    from test_dsa_entry_binding_v1 import inputs
    o,u,op,up=inputs(tmp_path)
    del o['signal_timing'];op.write_bytes(d.encode(o))
    gen={'account':'O','target_session':DAY,'receipt_sha256':d.digest(op.read_bytes()),'generation_observed_at':t('09:00:00')}
    gp=tmp_path/'generation.json';gp.write_bytes(d.encode(gen))
    monkeypatch.setattr(d,'clock',lambda:t('09:01:00'))
    dest=d.publish(op,gp,tmp_path/'store')
    return op,gp,dest

def test_producer_publication_resolver_consumption_seal(tmp_path,monkeypatch):
    op,gp,dest=fixture(tmp_path,monkeypatch);before=op.read_bytes()
    monkeypatch.setattr(d,'clock',lambda:t('09:02:00'))
    observation=tmp_path/'consumer.json';sha=d.digest(before)
    r=resolve(tmp_path,DAY,delivery_sources={'O':{'directory':str(dest),'sha256':sha,'observation':str(observation)}})
    assert r['O']['path']==str(dest/'receipt.json') and observation.exists()
    a={'accepted':True,'authority_reference':'synthetic-only-not-real-authority','receipt_sha256':sha,
       'consumer_sha256':d.digest(observation.read_bytes()),'account':'O','target_session':DAY,
       'accepted_at':t('09:03:00'),'frozen_at':t('09:20:00')}
    ap=tmp_path/'external.json';ap.write_bytes(d.encode(a))
    ev={'account':'O','target_session':DAY,'receipt_sha256':sha,'signal_timing':{
        'cutoff':t('08:59:00'),'available_at':t('09:02:00'),'valid_until':t('10:00:00'),'next_session':'2026-09-25'},
        'field_evidence':{k:{'source':'synthetic','sha256':'a'*64} for k in ('cutoff','available_at','valid_until','next_session')}}
    ev['field_evidence']['available_at']['sha256']=d.digest(observation.read_bytes())
    ep=tmp_path/'timing.json';ep.write_bytes(d.encode(ev));out=tmp_path/'sealed.json'
    result=write_candidate(op,ep,out,t('09:35:00'),delivery=dest,consumer=observation,acceptance=ap,acceptance_sha=d.digest(ap.read_bytes()))
    assert result['authority_verified_by_this_tool'] is False
    assert op.read_bytes()==before
    saved=observation.read_bytes();monkeypatch.setattr(d,'clock',lambda:t('09:40:00'))
    d.consume(dest,sha,observation)
    assert observation.read_bytes()==saved
    a['frozen_at']=t('09:25:01');ap.write_bytes(d.encode(a))
    with pytest.raises(ValueError,match='LATE_OR_NON_MORNING'):
        d.check_chain(dest,observation,ap,d.digest(ap.read_bytes()),ev,t('09:35:00'))
    a['accepted']=False;ap.write_bytes(d.encode(a))
    with pytest.raises(ValueError,match='EXTERNAL_ACCEPTANCE'):
        d.check_chain(dest,observation,ap,d.digest(ap.read_bytes()),ev,t('09:35:00'))


def test_exact_publication_retry_and_crash_recovery(tmp_path,monkeypatch):
    op,gp,dest=fixture(tmp_path,monkeypatch)
    original=(dest/'publication.json').read_bytes()
    monkeypatch.setattr(d,'clock',lambda:t('09:10:00'))
    assert d.publish(op,gp,tmp_path/'store')==dest
    assert (dest/'publication.json').read_bytes()==original
    (dest/'publication.json').unlink() # Simulated crash before observation commit.
    d.publish(op,gp,tmp_path/'store')
    event=json.loads((dest/'publication.json').read_bytes())
    assert event['first_publication_at'] is None and event['observed_at']==t('09:10:00')

@pytest.mark.parametrize('file',['receipt.json','generation.json','manifest.json'])
def test_publication_drift_rejected(tmp_path,monkeypatch,file):
    op,gp,dest=fixture(tmp_path,monkeypatch)
    (dest/file).write_text('{}')
    with pytest.raises((ValueError,KeyError)):d.consume(dest,d.digest(op.read_bytes()),tmp_path/'obs.json')

def test_partial_stage_mismatch_never_publishes(tmp_path,monkeypatch):
    op,gp,dest=fixture(tmp_path,monkeypatch)
    root=tmp_path/'new';stage=root/('.'+d.digest(op.read_bytes())+'.incomplete');stage.mkdir(parents=True)
    (stage/'receipt.json').write_text('{}')
    with pytest.raises(ValueError,match='CONTENT_CONFLICT'):d.publish(op,gp,root)
    assert not (root/dest.name).exists()

def test_partial_stage_can_resume_matching_content(tmp_path,monkeypatch):
    op,gp,dest=fixture(tmp_path,monkeypatch)
    root=tmp_path/'new';stage=root/('.'+d.digest(op.read_bytes())+'.incomplete');stage.mkdir(parents=True)
    (stage/'receipt.json').write_bytes(op.read_bytes())
    assert d.publish(op,gp,root).is_dir()

def test_atomic_concurrent_identical_write_and_conflict(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    p=tmp_path/'event.json'
    with ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(lambda _:d.immutable(p,b'payload'),range(10)))
    assert p.read_bytes()==b'payload'
    with pytest.raises(ValueError):d.immutable(p,b'changed')

def test_no_future_generation(tmp_path,monkeypatch):
    op,gp,dest=fixture(tmp_path,monkeypatch);monkeypatch.setattr(d,'clock',lambda:t('08:00:00'))
    with pytest.raises(ValueError,match='FUTURE_GENERATION'):d.publish(op,gp,tmp_path/'else')
