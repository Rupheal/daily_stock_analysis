"""Create a bounded original-byte archive, validate restoration, then persist it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
import httpx
from dsa_drive_store import DriveStore, StoreError, LIMIT, scoped_token


def bundle(source, run_id, artifact_id, source_time=None, retrieved_time=None, parent=None):
    if source.is_symlink():
        raise StoreError('SYMLINK_REJECTED')
    items = [source] if source.is_file() else sorted(source.rglob('*'))
    files = []
    total = 0
    for f in items:
        if f.is_symlink():
            raise StoreError('SYMLINK_REJECTED')
        if not f.is_file():
            continue
        rel = f.name if source.is_file() else f.relative_to(source).as_posix()
        if rel == 'MANIFEST.json' or f.name.startswith('.env'):
            raise StoreError('RESERVED_OR_SECRET_FILE')
        total += f.stat().st_size
        if total > LIMIT:
            raise StoreError('BUNDLE_TOO_LARGE')
        data = f.read_bytes()
        for name, value in os.environ.items():
            if any(k in name for k in ('SECRET', 'TOKEN', 'API_KEY')) and len(value) >= 12 and value.encode() in data:
                raise StoreError('CREDENTIAL_BYTES_DETECTED')
        files.append((rel, data))
    if not files:
        raise StoreError('EMPTY_BUNDLE')
    manifest = {'run_id': run_id, 'artifact_id': artifact_id, 'source_time': source_time,
                'retrieved_time': retrieved_time, 'parent_artifact_id': parent,
                'unknown_times_reason': 'caller must supply source times; filesystem mtime is not evidence time',
                'role': 'canonical_new_raw_evidence', 'files': [
                    {'path': n, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in files]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in files + [('MANIFEST.json', json.dumps(manifest, sort_keys=True).encode())]:
            # Fixed ZIP timestamps make a retry byte-identical.
            z.writestr(zipfile.ZipInfo(n, (1980, 1, 1, 0, 0, 0)), b)
    data = out.getvalue()
    if len(data) > LIMIT:
        raise StoreError('BUNDLE_TOO_LARGE')
    verify_bundle(data)
    return data


def verify_bundle(data):
    if not data or len(data) > LIMIT:
        raise StoreError('RESTORE_TOO_LARGE')
    with zipfile.ZipFile(io.BytesIO(data)) as z, tempfile.TemporaryDirectory(prefix='dsa-bundle-restore-') as td:
        entries = z.infolist()
        names = [entry.filename for entry in entries]
        # Check the complete expanded size, including the manifest, before reading.
        if sum(entry.file_size for entry in entries) > LIMIT:
            raise StoreError('RESTORE_TOO_LARGE')
        if len(set(names)) != len(names) or 'MANIFEST.json' not in names:
            raise StoreError('MANIFEST_FILE_SET_MISMATCH')
        m = json.loads(z.read('MANIFEST.json'))
        rows = m.get('files') if isinstance(m, dict) else None
        if not isinstance(rows, list) or not rows:
            raise StoreError('MANIFEST_SCHEMA_INVALID')
        if any(not isinstance(f, dict) or not isinstance(f.get('path'), str) for f in rows):
            raise StoreError('MANIFEST_SCHEMA_INVALID')
        paths = [f['path'] for f in rows]
        if len(set(paths)) != len(paths) or 'MANIFEST.json' in paths or set(names) != {'MANIFEST.json'} | set(paths):
            raise StoreError('MANIFEST_FILE_SET_MISMATCH')
        for f in rows:
            name = f['path']
            if '\\' in name or ':' in name or name.startswith('/') or any(p in ('..', '.', '') for p in name.split('/')):
                raise StoreError('UNSAFE_ARCHIVE_PATH')
            if type(f.get('bytes')) is not int or f['bytes'] < 0 or not isinstance(f.get('sha256'), str):
                raise StoreError('MANIFEST_SCHEMA_INVALID')
            b = z.read(name)
            if len(b) != f['bytes'] or hashlib.sha256(b).hexdigest() != f['sha256']:
                raise StoreError('MANIFEST_HASH_MISMATCH')
            dest = Path(td) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != f['sha256']:
                raise StoreError('DISK_RESTORE_HASH_MISMATCH')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--artifact-id', required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--source-time')
    p.add_argument('--retrieved-time')
    p.add_argument('--parent-artifact-id')
    a = p.parse_args()
    try:
        if a.receipt.exists():
            raise StoreError('RECEIPT_ALREADY_EXISTS')
        data = bundle(a.source, a.run_id, a.artifact_id, a.source_time, a.retrieved_time, a.parent_artifact_id)
        with httpx.Client(timeout=30, follow_redirects=False) as c:
            token = scoped_token(c)
            c.headers['Authorization'] = 'Bearer ' + token
            store = DriveStore(c, os.environ.get('DSA_DRIVE_FOLDER_ID', ''))
            receipt = store.put(a.artifact_id, data, a.run_id)
            with tempfile.TemporaryDirectory(prefix='dsa-independent-read-') as td:
                target = Path(td) / 'archive.zip'
                store.recover(receipt['file_id'], receipt['sha256'], target)
                verify_bundle(target.read_bytes())
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        with a.receipt.open('x') as f:
            json.dump(receipt, f, indent=2)
        print(json.dumps({'status': 'BUNDLE_SAVE_READ_HASH_RESTORE_PASS', 'model_requests': 0}))
    except Exception as e:
        print(json.dumps({'status': 'FAILED', 'reason': str(e) if isinstance(e, StoreError) else type(e).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
