"""Synthetic negative cases for Drive recovery; never access real Drive or model APIs."""
import io
import json
from pathlib import Path
import sys
import zipfile
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsa_drive_store import DriveStore, StoreError, LIMIT, digest
from dsa_drive_bundle import verify_bundle
from test_dsa_drive_store import Fake


def archive(entries, manifest_rows=None):
    rows = [{'path': n, 'bytes': len(b), 'sha256': digest(b)} for n, b in entries]
    if manifest_rows is not None:
        rows = manifest_rows
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in entries:
            z.writestr(n, b)
        z.writestr('MANIFEST.json', json.dumps({'files': rows}))
    return out.getvalue()


def test_total_uncompressed_bytes_rejected():
    raw = archive([('a', b'x' * (LIMIT // 2 + 1)), ('b', b'y' * (LIMIT // 2 + 1))])
    assert len(raw) < LIMIT
    with pytest.raises(StoreError, match='RESTORE_TOO_LARGE'):
        verify_bundle(raw)


def test_oversized_manifest_rejected_before_json_parse():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('MANIFEST.json', ' ' * (LIMIT + 1) + '{"files":[]}')
    with pytest.raises(StoreError, match='RESTORE_TOO_LARGE'):
        verify_bundle(out.getvalue())


def test_duplicate_manifest_record_rejected():
    row = {'path': 'raw', 'bytes': 1, 'sha256': digest(b'x')}
    with pytest.raises(StoreError, match='MANIFEST_FILE_SET_MISMATCH'):
        verify_bundle(archive([('raw', b'x')], [row, row]))


def test_windows_drive_path_rejected():
    with pytest.raises(StoreError, match='UNSAFE_ARCHIVE_PATH'):
        verify_bundle(archive([('C:payload', b'x')]))


def test_missing_head_revision_never_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'x'
    def handle(r):
        response = f.handle(r)
        if r.url.params.get('alt') != 'media' and not r.url.path.endswith('/files') and not r.url.path.endswith('/folder'):
            payload = response.json(); payload.pop('headRevisionId', None)
            return httpx.Response(200, json=payload)
        return response
    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        with pytest.raises(StoreError, match='READBACK_HEAD_REVISION_UNVERIFIED'):
            DriveStore(c, 'folder').recover('saved', digest(b'x'), tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_streaming_oversize_rejected_before_file_write(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'x' * (LIMIT + 1)
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        with pytest.raises(StoreError, match='READBACK_TOO_LARGE'):
            DriveStore(c, 'folder').recover('saved', digest(f.data), tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_server_version_change_with_same_content_revision_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'x'
    f.file_versions = ['1', '2', '3']
    f.head_revisions = ['rev-a', 'rev-a', 'rev-a']
    target = tmp_path / 'restored'
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        result = DriveStore(c, 'folder').recover('saved', digest(b'x'), target)
    assert target.read_bytes() == b'x'
    assert result['version'] == '3'
    assert result['headRevisionId'] == 'rev-a'


def test_content_revision_change_rejected_distinctly(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'x'
    # Pre-read content revision settles at A; post-media metadata reports B.
    f.head_revisions = ['rev-a', 'rev-a', 'rev-b']
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        with pytest.raises(StoreError, match='READBACK_CONTENT_REVISION_CHANGED'):
            DriveStore(c, 'folder').recover('saved', digest(b'x'), tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_hash_mismatch_takes_priority_over_content_revision_change(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'good'; f.corrupt = True
    f.head_revisions = ['rev-a', 'rev-a', 'rev-b']
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        with pytest.raises(StoreError, match='READBACK_HASH_MISMATCH'):
            DriveStore(c, 'folder').recover('saved', digest(b'good'), tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_head_revision_must_settle_before_media(tmp_path, monkeypatch):
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f = Fake(); f.data = b'x'
    f.head_revisions = ['a', 'b', 'c', 'd', 'e', 'f']
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        with pytest.raises(StoreError, match='READBACK_HEAD_REVISION_NOT_STABLE'):
            DriveStore(c, 'folder').recover('saved', digest(b'x'), tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


class Claims:
    """Single-writer model of persistence; no provider or network calls."""
    def __init__(self):
        self.saved = {}; self.checks = []; self.fail_after_save = False
    def assert_absent(self, artifact):
        self.checks.append(artifact)
        if artifact in self.saved:
            raise StoreError('NATIVE_ARTIFACT_EXISTS_NO_REPEAT_MODEL')
    def put(self, artifact, data, run):
        self.saved[artifact] = json.loads(data)
        if self.fail_after_save:
            raise RuntimeError('synthetic lost acknowledgement')
        return {'save_read_hash_restore': True, 'idempotent_reuse': False}


def reserve(store):
    return DriveStore.reserve_native_call(store, 'ART-NATIVE', 'RUN-TEST', digest(b'preflight'), 'CI-1-1')


def test_claim_persists_before_model_and_does_not_claim_acceptance():
    s = Claims(); assert reserve(s)['save_read_hash_restore']
    assert s.checks == ['ART-NATIVE', 'ART-NATIVE-CLAIM']
    assert s.saved['ART-NATIVE-CLAIM']['model_acceptance'] is False


def test_model_success_storage_failure_cannot_repeat():
    s = Claims(); reserve(s)
    assert 'ART-NATIVE' not in s.saved
    with pytest.raises(StoreError, match='NO_REPEAT_MODEL'):
        reserve(s)


def test_ambiguous_claim_save_requires_reconciliation():
    s = Claims(); s.fail_after_save = True
    with pytest.raises(RuntimeError): reserve(s)
    s.fail_after_save = False
    with pytest.raises(StoreError, match='NO_REPEAT_MODEL'): reserve(s)


def test_existing_native_report_blocks_claim():
    s = Claims(); s.saved['ART-NATIVE'] = {'synthetic': True}
    with pytest.raises(StoreError, match='NO_REPEAT_MODEL'): reserve(s)
    assert 'ART-NATIVE-CLAIM' not in s.saved


def test_bad_preflight_hash_never_writes_claim():
    s = Claims()
    with pytest.raises(StoreError, match='INVALID_PREFLIGHT_HASH'):
        DriveStore.reserve_native_call(s, 'ART-NATIVE', 'RUN-TEST', 'bad', 'CI-1-1')
    assert s.saved == {}
