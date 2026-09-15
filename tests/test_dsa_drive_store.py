import io
import json
from pathlib import Path
import sys
import zipfile
import httpx
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsa_drive_store import DriveStore, StoreError, LIMIT, digest, scoped_token, SCOPE
from dsa_drive_bundle import bundle, verify_bundle


class Fake:
    def __init__(self):
        self.data = b''; self.props = {}; self.posts = 0
        self.public = False; self.corrupt = False; self.duplicate = False
        self.file_versions = []

    def handle(self, r):
        if r.method == 'POST':
            self.posts += 1
            boundary = r.headers['content-type'].split('boundary=')[1].encode()
            chunks = r.content.split(b'--' + boundary)
            meta = json.loads(chunks[1].split(b'\r\n\r\n', 1)[1].rstrip(b'\r\n'))
            self.props = meta['appProperties']
            self.data = chunks[2].split(b'\r\n\r\n', 1)[1][:-2]
            return httpx.Response(200, json={'id': 'saved'})
        if r.url.params.get('alt') == 'media':
            return httpx.Response(200, content=b'corrupt' if self.corrupt else self.data)
        if r.url.path.endswith('/files'):
            found = [{'id': 'saved', 'appProperties': self.props}] if self.posts else []
            return httpx.Response(200, json={'files': found * (2 if self.duplicate else 1)})
        folder = r.url.path.endswith('/folder')
        version = '1'
        if not folder and self.file_versions:
            version = self.file_versions.pop(0)
        return httpx.Response(200, json={'id': 'folder' if folder else 'saved', 'version': version,
            'parents': [] if folder else ['folder'],
            'mimeType': 'application/vnd.google-apps.folder' if folder else 'application/octet-stream',
            'capabilities': {'canShare': True, 'canAddChildren': True},
            'permissions': [{'type': 'anyone' if self.public else 'user', 'role': 'owner'}]})


@pytest.fixture
def store():
    f = Fake()
    with httpx.Client(transport=httpx.MockTransport(f.handle)) as c:
        yield DriveStore(c, 'folder'), f


def test_bytes_and_idempotence(store):
    s, f = store
    data = b'\x00\xfforiginal\r\n'
    r = s.put('ART-1', data, 'RUN-1')
    assert r['sha256'] == digest(data) and r['save_read_hash_restore']
    assert s.put('ART-1', data, 'RUN-1')['idempotent_reuse']
    assert f.posts == 1


def test_fresh_version_can_settle_without_relaxing_post_read_gate(store, monkeypatch):
    s, f = store
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    f.file_versions = ['1', '2', '2', '2']
    r = s.put('ART-1', b'original', 'RUN-1')
    assert r['version'] == '2'
    assert r['save_read_hash_restore'] is True


def test_transient_get_transport_reset_is_retried(monkeypatch):
    f = Fake(); resets = {'n': 0}
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    def handle(r):
        if r.method == 'GET' and r.url.path.endswith('/folder') and resets['n'] == 0:
            resets['n'] += 1
            raise httpx.ConnectError('reset', request=r)
        return f.handle(r)
    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        m = DriveStore(c, 'folder').private_meta('folder', folder=True)
    assert m['id'] == 'folder' and resets['n'] == 1


def test_media_transport_reset_is_retried(monkeypatch, tmp_path):
    f = Fake(); f.data = b'original'; resets = {'n': 0}
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    def handle(r):
        if r.url.params.get('alt') == 'media' and resets['n'] == 0:
            resets['n'] += 1
            raise httpx.ConnectError('reset', request=r)
        return f.handle(r)
    target = tmp_path / 'restored'
    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        DriveStore(c, 'folder').recover('saved', digest(f.data), target)
    assert target.read_bytes() == b'original' and resets['n'] == 1


def test_ambiguous_write_transport_is_not_retried(monkeypatch):
    f = Fake(); attempts = {'posts': 0}
    monkeypatch.setattr('dsa_drive_store.time.sleep', lambda _: None)
    def handle(r):
        if r.method == 'POST':
            attempts['posts'] += 1
            raise httpx.ConnectError('reset', request=r)
        return f.handle(r)
    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        with pytest.raises(StoreError, match='DRIVE_WRITE_TRANSPORT_AMBIGUOUS'):
            DriveStore(c, 'folder').put('ART-1', b'original', 'RUN-1')
    assert attempts['posts'] == 1


def test_conflict_not_overwritten(store):
    s, f = store; s.put('ART-1', b'old', 'RUN-1')
    with pytest.raises(StoreError, match='APPEND_ONLY_CONFLICT'):
        s.put('ART-1', b'new', 'RUN-1')
    assert f.posts == 1 and f.data == b'old'


def test_permission_gate_before_write(store):
    s, f = store; f.public = True
    with pytest.raises(StoreError, match='PERMISSIONS'):
        s.put('ART-1', b'x', 'RUN-1')
    assert f.posts == 0


def test_corrupt_readback(store):
    s, f = store; f.corrupt = True
    with pytest.raises(StoreError, match='HASH'):
        s.put('ART-1', b'x', 'RUN-1')


def test_duplicate_id_rejected(store):
    s, f = store; s.put('ART-1', b'x', 'RUN-1'); f.duplicate = True
    with pytest.raises(StoreError, match='DUPLICATE'):
        s.put('ART-1', b'x', 'RUN-1')


def test_native_repeat_gate(store):
    s, f = store
    s.assert_absent('ART-1')
    s.put('ART-1', b'x', 'RUN-1')
    with pytest.raises(StoreError, match='NO_REPEAT_MODEL'):
        s.assert_absent('ART-1')


@pytest.mark.parametrize('bad', ['../x', '', "a'b", 'a/b'])
def test_unsafe_id(store, bad):
    with pytest.raises(StoreError, match='INVALID_ID'):
        store[0].put(bad, b'x', 'RUN-1')


def test_bounded_size(store):
    with pytest.raises(StoreError, match='OVERSIZE'):
        store[0].put('ART-1', b'x' * (LIMIT + 1), 'RUN-1')


def test_deterministic_original_archive(tmp_path):
    (tmp_path / 'raw.json').write_bytes(b'{"x":1}\r\n')
    (tmp_path / 'raw.db').write_bytes(b'\x00\xff\x01')
    a = bundle(tmp_path, 'RUN-1', 'ART-1')
    assert a == bundle(tmp_path, 'RUN-1', 'ART-1')
    verify_bundle(a)
    with zipfile.ZipFile(io.BytesIO(a)) as z:
        assert z.read('raw.db') == b'\x00\xff\x01'


def test_secret_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('DSA_DRIVE_REFRESH_TOKEN', 'synthetic-secret-value')
    (tmp_path / 'raw.txt').write_text('synthetic-secret-value')
    with pytest.raises(StoreError, match='CREDENTIAL'):
        bundle(tmp_path, 'RUN-1', 'ART-1')


def test_symlink_rejected(tmp_path):
    (tmp_path / 'link').symlink_to('/etc/hosts')
    with pytest.raises(StoreError, match='SYMLINK'):
        bundle(tmp_path, 'RUN-1', 'ART-1')


def test_manifest_corruption(tmp_path):
    (tmp_path / 'data').write_text('original')
    raw = bundle(tmp_path, 'RUN-1', 'ART-1')
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(out, 'w') as dest:
        for n in source.namelist():
            dest.writestr(n, b'changed' if n == 'data' else source.read(n))
    with pytest.raises(StoreError, match='HASH'):
        verify_bundle(out.getvalue())


@pytest.mark.parametrize('scope', ['', 'https://www.googleapis.com/auth/drive', SCOPE + ' other'])
def test_oauth_rejects_broad_or_unknown_scopes(monkeypatch, scope):
    for name in ('DSA_DRIVE_CLIENT_ID', 'DSA_DRIVE_CLIENT_SECRET', 'DSA_DRIVE_REFRESH_TOKEN'):
        monkeypatch.setenv(name, 'synthetic-value')
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'scope': scope, 'access_token': 'synthetic'}))) as c:
        with pytest.raises(StoreError, match='SCOPE'):
            scoped_token(c)
