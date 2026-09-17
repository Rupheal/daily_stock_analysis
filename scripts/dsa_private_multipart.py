"""Owner-only, byte-preserving evidence parts; the 4 MiB store limit is unchanged."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from dsa_drive_bundle import bundle, verify_bundle
from dsa_drive_store import StoreError, LIMIT

PART_BYTES = 2 * 1024 * 1024
TOTAL_BYTES = 16 * 1024 * 1024
VERSION = 'DSA_PRIVATE_MULTIPART_v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source: Path, run_id: str, artifact_id: str):
    """Validate *all* bytes before any upload; split oversized files losslessly."""
    if source.is_symlink():
        raise StoreError('SYMLINK_REJECTED')
    files, total = [], 0
    for p in sorted(source.rglob('*')):
        if p.is_symlink():
            raise StoreError('SYMLINK_REJECTED')
        if not p.is_file():
            continue
        name = p.relative_to(source).as_posix()
        if p.name.startswith('.env') or name == 'MANIFEST.json':
            raise StoreError('RESERVED_OR_SECRET_FILE')
        if '\\' in name or ':' in name or any(x in ('..', '.', '') for x in name.split('/')):
            raise StoreError('UNSAFE_ARCHIVE_PATH')
        total += p.stat().st_size
        if total > TOTAL_BYTES:
            raise StoreError('MULTIPART_TOTAL_TOO_LARGE')
        data = p.read_bytes()
        for key, value in os.environ.items():
            if any(x in key for x in ('SECRET', 'TOKEN', 'API_KEY')) and len(value) >= 12 and value.encode() in data:
                raise StoreError('CREDENTIAL_BYTES_DETECTED')
        files.append((name, data))
    if not files:
        raise StoreError('EMPTY_BUNDLE')
    manifest = {'schema': VERSION, 'run_id': run_id, 'artifact_id': artifact_id, 'files': [], 'original_bytes': total,
                'timestamps': 'Original document fields preserved; no inferred source time'}
    payloads, group, size = [], [], 0

    def flush():
        nonlocal group, size
        if not group:
            return
        index = len(payloads)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, data in group:
                (root / name).write_bytes(data)
            payload = bundle(root, run_id, artifact_id + '-P%03d' % index)
            verify_bundle(payload)
            payloads.append(payload)
        group, size = [], 0

    for file_index, (name, data) in enumerate(files):
        row = {'path': name, 'bytes': len(data), 'sha256': sha(data), 'chunks': []}
        for offset in range(0, max(1, len(data)), PART_BYTES):
            chunk = data[offset:offset + PART_BYTES]
            if group and size + len(chunk) > PART_BYTES:
                flush()
            chunk_name = 'f%05d-o%010d' % (file_index, offset)
            row['chunks'].append({'part': len(payloads), 'name': chunk_name, 'offset': offset, 'bytes': len(chunk), 'sha256': sha(chunk)})
            group.append((chunk_name, chunk)); size += len(chunk)
        manifest['files'].append(row)
    flush()
    manifest['parts'] = [{'index': i, 'bytes': len(b), 'sha256': sha(b)} for i, b in enumerate(payloads)]
    restore(manifest, payloads)  # Full local byte reassembly before writes.
    return manifest, payloads


def restore(manifest, payloads):
    import io, zipfile
    if manifest.get('schema') != VERSION or len(payloads) != len(manifest['parts']):
        raise StoreError('MULTIPART_SCHEMA_INVALID')
    parts = []
    for expected, data in zip(manifest['parts'], payloads):
        if sha(data) != expected['sha256'] or len(data) != expected['bytes']:
            raise StoreError('MULTIPART_PART_HASH_MISMATCH')
        verify_bundle(data)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            parts.append({n: z.read(n) for n in z.namelist() if n != 'MANIFEST.json'})
    restored, used = {}, set()
    total = 0
    for row in manifest['files']:
        name = row['path']
        if name in restored or '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or any(x in ('..', '.', '') for x in name.split('/')):
            raise StoreError('UNSAFE_ARCHIVE_PATH')
        chunks, offset = [], 0
        for c in row['chunks']:
            key = (c['part'], c['name'])
            if key in used or c['offset'] != offset:
                raise StoreError('MULTIPART_CHUNK_ORDER_INVALID')
            b = parts[c['part']][c['name']]
            if len(b) != c['bytes'] or sha(b) != c['sha256']:
                raise StoreError('MULTIPART_CHUNK_HASH_MISMATCH')
            chunks.append(b); offset += len(b); used.add(key)
        data = b''.join(chunks); total += len(data)
        if total > TOTAL_BYTES or len(data) != row['bytes'] or sha(data) != row['sha256']:
            raise StoreError('MULTIPART_FILE_HASH_MISMATCH')
        restored[name] = data
    if used != {(i, name) for i, p in enumerate(parts) for name in p} or total != manifest['original_bytes']:
        raise StoreError('MULTIPART_FILE_SET_MISMATCH')
    return restored


def save(source, artifact_id, run_id, store):
    manifest, payloads = prepare(source, run_id, artifact_id)
    receipts, recovered = [], []
    with tempfile.TemporaryDirectory() as td:
        for i, payload in enumerate(payloads):
            r = store.put(artifact_id + '-P%03d' % i, payload, run_id)
            dest = Path(td) / ('part%03d.zip' % i)
            store.recover(r['file_id'], r['sha256'], dest)
            recovered.append(dest.read_bytes()); receipts.append(r)
        restore(manifest, recovered)
        manifest['private_storage'] = [{'file_id': r['file_id'], 'sha256': r['sha256']} for r in receipts]
        data = (json.dumps(manifest, sort_keys=True, ensure_ascii=False) + '\n').encode()
        if len(data) > LIMIT:
            raise StoreError('MULTIPART_INDEX_TOO_LARGE')
        index = store.put(artifact_id + '-INDEX', data, run_id)
        dest = Path(td) / 'index.json'; store.recover(index['file_id'], index['sha256'], dest)
        restore(json.loads(dest.read_bytes()), recovered)
    return {'format': VERSION, 'save_read_hash_restore': True, 'sha256': index['sha256'],
            'bytes': sum(len(b) for b in payloads) + len(data), 'original_bytes': manifest['original_bytes'],
            'parts': len(payloads), 'files': len(manifest['files'])}
