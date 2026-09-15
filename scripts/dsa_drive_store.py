"""Bounded append-only Drive evidence storage; no raw data or credentials on stdout.

The caller serializes writers (Actions concurrency). JSON/ZIP remain opaque bytes.
Every receipt is private; public logs contain counts and status only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
import httpx

SCOPE = 'https://www.googleapis.com/auth/drive.file'
API = 'https://www.googleapis.com/drive/v3'
LIMIT = 4 * 1024 * 1024
READ_ATTEMPTS = 3


class StoreError(RuntimeError):
    """Only fixed, non-sensitive error codes may escape the CLI."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise StoreError('INVALID_ID')
    return value


def scoped_token(client):
    names = ('DSA_DRIVE_CLIENT_ID', 'DSA_DRIVE_CLIENT_SECRET', 'DSA_DRIVE_REFRESH_TOKEN')
    if not all(os.environ.get(k) for k in names):
        raise StoreError('DRIVE_OAUTH_CONFIGURATION_MISSING')
    r = client.post('https://oauth2.googleapis.com/token', data={
        'client_id': os.environ[names[0]], 'client_secret': os.environ[names[1]],
        'refresh_token': os.environ[names[2]], 'grant_type': 'refresh_token'})
    if r.status_code != 200:
        raise StoreError('OAUTH_REFRESH_FAILED')
    p = r.json()
    if set(p.get('scope', '').split()) != {SCOPE} or not p.get('access_token'):
        raise StoreError('OAUTH_SCOPE_NOT_EXACT_DRIVE_FILE')
    return p['access_token']


class DriveStore:
    def __init__(self, client, folder):
        self.client = client
        self.folder = checked_id(folder)

    def request(self, method, url, **kw):
        method = method.upper()
        attempts = READ_ATTEMPTS if method == 'GET' else 1
        for attempt in range(attempts):
            try:
                r = self.client.request(method, url, **kw)
            except httpx.TransportError:
                if method != 'GET':
                    raise StoreError('DRIVE_WRITE_TRANSPORT_AMBIGUOUS') from None
                if attempt + 1 >= attempts:
                    raise StoreError('DRIVE_GET_TRANSPORT_FAILED') from None
                time.sleep(0.2 * (attempt + 1))
                continue
            if r.status_code in (200, 201):
                return r
            if method == 'GET' and r.status_code >= 500 and attempt + 1 < attempts:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise StoreError('DRIVE_HTTP_' + str(r.status_code))
        raise StoreError('DRIVE_GET_TRANSPORT_FAILED')

    def assert_absent(self, artifact_id):
        checked_id(artifact_id)
        self.private_meta(self.folder, folder=True)
        r = self.request('GET', API + '/files', params={
            'q': "'" + self.folder + "' in parents and trashed=false and appProperties has { key='artifact_id' and value='" + artifact_id + "' }",
            'fields': 'files(id),nextPageToken', 'pageSize': 100}).json()
        if r.get('files') or r.get('nextPageToken'):
            raise StoreError('NATIVE_ARTIFACT_EXISTS_NO_REPEAT_MODEL')

    def reserve_native_call(self, artifact_id, run_id, preflight_sha256, execution_id):
        """Durable call intent under the existing single-writer serialization."""
        checked_id(artifact_id); checked_id(run_id); checked_id(execution_id)
        claim_id = checked_id(artifact_id + '-CLAIM')
        if not re.fullmatch(r'[0-9a-f]{64}', preflight_sha256):
            raise StoreError('INVALID_PREFLIGHT_HASH')
        self.assert_absent(artifact_id)
        self.assert_absent(claim_id)
        data = json.dumps({
            'schema': 'dsa-native-call-intent-v1', 'run_id': run_id,
            'native_artifact_id': artifact_id, 'execution_id': execution_id,
            'preflight_sha256': preflight_sha256,
            'upstream_commit': '089d9d26d68f8b839ea5a74a3784e4402925f8b7',
            'state': 'RESERVED_RECONCILE_BEFORE_ANY_REPEAT', 'model_acceptance': False,
        }, sort_keys=True).encode()
        receipt = self.put(claim_id, data, run_id)
        if receipt.get('idempotent_reuse'):
            raise StoreError('CLAIM_EXISTS_RECONCILE_NO_REPEAT_MODEL')
        return receipt

    def private_meta(self, file_id, folder=False):
        m = self.request('GET', API + '/files/' + checked_id(file_id), params={
            'fields': 'id,mimeType,parents,trashed,version,headRevisionId,size,capabilities(canShare,canAddChildren),permissions(type,role),appProperties'
        }).json()
        perms = m.get('permissions')
        if (m.get('trashed') or not m.get('capabilities', {}).get('canShare')
                or not perms or any(p.get('type') != 'user' or p.get('role') != 'owner' for p in perms)):
            raise StoreError('OWNER_ONLY_PERMISSIONS_NOT_VERIFIED')
        if folder:
            if m.get('mimeType') != 'application/vnd.google-apps.folder' or not m.get('capabilities', {}).get('canAddChildren'):
                raise StoreError('FOLDER_NOT_WRITABLE')
        elif m.get('parents') != [self.folder] or m.get('mimeType', '').startswith('application/vnd.google-apps.'):
            raise StoreError('FILE_LOCATION_OR_FORMAT_INVALID')
        return m

    def stable_content_meta(self, file_id, attempts=6, pause=0.25):
        """Require the blob content revision id to exist and settle before readback.

        Google Drive ``version`` advances on every server-side file change,
        including metadata-only changes. ``headRevisionId`` identifies the
        current blob content revision, so content integrity is gated on it while
        ``version`` remains audit metadata only.
        """
        previous_revision = None
        for attempt in range(attempts):
            current = self.private_meta(file_id)
            revision = current.get('headRevisionId')
            if isinstance(revision, str) and revision:
                if revision == previous_revision:
                    return current
                previous_revision = revision
            elif attempt + 1 >= attempts:
                raise StoreError('READBACK_HEAD_REVISION_UNVERIFIED')
            if attempt + 1 < attempts:
                time.sleep(pause)
        raise StoreError('READBACK_HEAD_REVISION_NOT_STABLE')

    def _read_media(self, file_id):
        for attempt in range(READ_ATTEMPTS):
            parts = []
            total = 0
            try:
                with self.client.stream('GET', API + '/files/' + checked_id(file_id), params={'alt': 'media'}) as response:
                    if response.status_code != 200:
                        if response.status_code >= 500 and attempt + 1 < READ_ATTEMPTS:
                            time.sleep(0.2 * (attempt + 1)); continue
                        raise StoreError('DRIVE_HTTP_' + str(response.status_code))
                    for part in response.iter_bytes(chunk_size=64 * 1024):
                        total += len(part)
                        if total > LIMIT:
                            raise StoreError('READBACK_TOO_LARGE')
                        parts.append(part)
                return b''.join(parts)
            except httpx.TransportError:
                if attempt + 1 >= READ_ATTEMPTS:
                    raise StoreError('DRIVE_MEDIA_TRANSPORT_FAILED') from None
                time.sleep(0.2 * (attempt + 1))
        raise StoreError('DRIVE_MEDIA_TRANSPORT_FAILED')

    def recover(self, file_id, expected, out):
        before = self.stable_content_meta(file_id)
        data = self._read_media(file_id)
        after = self.private_meta(file_id)
        # Byte integrity remains the first and hardest content gate.
        if digest(data) != expected:
            raise StoreError('READBACK_HASH_MISMATCH')
        after_revision = after.get('headRevisionId')
        if not isinstance(after_revision, str) or not after_revision:
            raise StoreError('READBACK_HEAD_REVISION_UNVERIFIED')
        if before.get('headRevisionId') != after_revision:
            raise StoreError('READBACK_CONTENT_REVISION_CHANGED')
        with Path(out).open('xb') as f:
            f.write(data)
        return after

    def put(self, artifact_id, data, run_id):
        checked_id(artifact_id); checked_id(run_id)
        if not data or len(data) > LIMIT:
            raise StoreError('EMPTY_OR_OVERSIZE_INPUT')
        self.private_meta(self.folder, folder=True)
        p = self.request('GET', API + '/files', params={
            'q': "'" + self.folder + "' in parents and trashed=false and appProperties has { key='artifact_id' and value='" + artifact_id + "' }",
            'fields': 'files(id,appProperties),nextPageToken', 'pageSize': 100}).json()
        found = p.get('files', [])
        if p.get('nextPageToken') or len(found) > 1:
            raise StoreError('DUPLICATE_ARTIFACT_ID')
        sha = digest(data)
        if found:
            props = found[0].get('appProperties', {})
            if props.get('sha256') != sha or props.get('run_id') != run_id:
                raise StoreError('APPEND_ONLY_CONFLICT')
            file_id = found[0]['id']
        else:
            # No automatic POST retry: an ambiguous write transport requires a
            # later serialized artifact-id lookup before any new write/model call.
            boundary = 'dsa_' + uuid.uuid4().hex
            meta = {'name': artifact_id + '.bin', 'mimeType': 'application/octet-stream',
                    'parents': [self.folder], 'appProperties': {'artifact_id': artifact_id, 'sha256': sha, 'run_id': run_id}}
            body = (('--' + boundary + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode()
                    + json.dumps(meta).encode() + ('\r\n--' + boundary + '\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                    + data + ('\r\n--' + boundary + '--\r\n').encode())
            file_id = self.request('POST', 'https://www.googleapis.com/upload/drive/v3/files',
                                   params={'uploadType': 'multipart', 'fields': 'id'}, content=body,
                                   headers={'Content-Type': 'multipart/related; boundary=' + boundary}).json()['id']
        self.private_meta(self.folder, folder=True)
        with tempfile.TemporaryDirectory(prefix='dsa-restore-') as td:
            restored = Path(td) / 'restored.bin'
            m = self.recover(file_id, sha, restored)
            if restored.read_bytes() != data:
                raise StoreError('RESTORE_BYTES_MISMATCH')
        return {'artifact_id': artifact_id, 'run_id': run_id, 'file_id': file_id,
                'version': m.get('version'), 'head_revision_id': m.get('headRevisionId'),
                'sha256': sha, 'bytes': len(data),
                'role': 'canonical_new_raw_evidence', 'verified_at': datetime.now(timezone.utc).isoformat(),
                'idempotent_reuse': bool(found), 'save_read_hash_restore': True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--artifact-id', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--receipt', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.source.is_symlink() or a.source.stat().st_size > LIMIT:
            raise StoreError('SOURCE_INVALID_OR_OVERSIZE')
        if a.receipt.exists():
            raise StoreError('RECEIPT_ALREADY_EXISTS')
        with httpx.Client(timeout=30, follow_redirects=False) as c:
            token = scoped_token(c); c.headers['Authorization'] = 'Bearer ' + token
            receipt = DriveStore(c, os.environ.get('DSA_DRIVE_FOLDER_ID', '')).put(a.artifact_id, a.source.read_bytes(), a.run_id)
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        with a.receipt.open('x') as f: json.dump(receipt, f, indent=2)
        print(json.dumps({'status': 'SAVE_READ_HASH_RESTORE_PASS', 'model_requests': 0}))
    except Exception as e:
        print(json.dumps({'status': 'FAILED', 'reason': str(e) if isinstance(e, StoreError) else type(e).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
