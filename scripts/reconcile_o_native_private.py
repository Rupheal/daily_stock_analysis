"""Read-only reconciliation of the canonical O-native private evidence bundle.

This tool never exposes raw model/preflight/stdout/stderr content. It emits only
fixed classification codes, counts, booleans and integrity status. It never
configures or calls a model provider and performs no Drive writes.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

import httpx

from dsa_drive_store import API, DriveStore, StoreError, scoped_token
from dsa_drive_bundle import verify_bundle

ARTIFACT_ID = 'ART-DSA-RUN013-NATIVE'
CLAIM_ID = 'ART-DSA-RUN013-NATIVE-CLAIM'
EXPECTED_RUN_ID = 'TRI-DSA-EXEC-20260914-013'


KNOWN_ERROR_CODES = (
    ('Native input session differs from validated daily evidence', 'NATIVE_SESSION_MISMATCH'),
    ('Native price differs from independent evidence: open', 'NATIVE_PRICE_MISMATCH_OPEN'),
    ('Native price differs from independent evidence: high', 'NATIVE_PRICE_MISMATCH_HIGH'),
    ('Native price differs from independent evidence: low', 'NATIVE_PRICE_MISMATCH_LOW'),
    ('Native price differs from independent evidence: close', 'NATIVE_PRICE_MISMATCH_CLOSE'),
    ('Native volume differs from independent evidence', 'NATIVE_VOLUME_MISMATCH'),
    ('Original commit mismatch', 'ORIGINAL_COMMIT_MISMATCH'),
    ('Original tracked source must remain unchanged', 'ORIGINAL_SOURCE_DIRTY'),
    ('A passed Xiaomi preflight is required', 'PREFLIGHT_NOT_ACCEPTED'),
    ('This concrete request slot is not reusable', 'REQUEST_SLOT_REUSE_GUARD'),
    ('Unexpected async model route; no request sent', 'UNEXPECTED_ASYNC_MODEL_ROUTE_BLOCKED'),
)


def fixed_error_code(error):
    if not error:
        return 'NO_RECORDED_ERROR'
    text = str(error)
    for needle, code in KNOWN_ERROR_CODES:
        if needle in text:
            return code
    # Only surface the exception class prefix, never the private message.
    prefix = text.split(':', 1)[0].strip()
    safe = ''.join(ch if ch.isalnum() else '_' for ch in prefix).strip('_').upper()
    return 'PRIVATE_ERROR_OTHER_' + (safe or 'UNKNOWN')


def one_artifact(store, artifact_id):
    q = ("'" + store.folder + "' in parents and trashed=false and "
         "appProperties has { key='artifact_id' and value='" + artifact_id + "' }")
    page = store.request('GET', API + '/files', params={
        'q': q,
        'fields': 'files(id,size,version,headRevisionId,appProperties),nextPageToken',
        'pageSize': 100,
    }).json()
    rows = page.get('files', [])
    if page.get('nextPageToken') or len(rows) != 1:
        raise StoreError('RECONCILE_CANONICAL_COUNT_NOT_ONE')
    return rows[0]


def read_json(z, name):
    if name not in z.namelist():
        return None
    try:
        return json.loads(z.read(name))
    except Exception:
        raise StoreError('RECONCILE_PRIVATE_JSON_INVALID') from None


def classify_private_logs(z):
    """Search only fixed strings; never return raw log content."""
    hits = []
    for name in ('native-stderr.log', 'native-stdout.log'):
        if name not in z.namelist():
            continue
        raw = z.read(name)
        for needle, code in KNOWN_ERROR_CODES:
            if needle.encode() in raw and code not in hits:
                hits.append(code)
    return hits


def main():
    arm = json.loads((Path(__file__).resolve().parents[1] / 'docs/runtime/run012-private-native-arm.json').read_text())
    if arm.get('armed') is not False:
        raise SystemExit('RECONCILIATION_REQUIRES_O_DISARMED')
    if os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('LLM_DEEPSEEK_API_KEY'):
        raise SystemExit('MODEL_KEY_MUST_NOT_BE_EXPOSED')

    with httpx.Client(timeout=30, follow_redirects=False) as client:
        client.headers['Authorization'] = 'Bearer ' + scoped_token(client)
        store = DriveStore(client, os.environ.get('DSA_DRIVE_FOLDER_ID', ''))
        native = one_artifact(store, ARTIFACT_ID)
        claim = one_artifact(store, CLAIM_ID)

        native_props = native.get('appProperties') or {}
        claim_props = claim.get('appProperties') or {}
        if native_props.get('run_id') != EXPECTED_RUN_ID or claim_props.get('run_id') != EXPECTED_RUN_ID:
            raise StoreError('RECONCILE_RUN_ID_MISMATCH')
        expected = native_props.get('sha256')
        if not isinstance(expected, str) or len(expected) != 64:
            raise StoreError('RECONCILE_SHA_MISSING')

        with tempfile.TemporaryDirectory(prefix='dsa-o-reconcile-') as td:
            archive = Path(td) / 'native.zip'
            store.recover(native['id'], expected, archive)
            data = archive.read_bytes()
            verify_bundle(data)

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        summary = read_json(z, 'original-model/probe-summary.json') or {}
        process = read_json(z, 'process.json') or {}
        manifest = read_json(z, 'MANIFEST.json') or {}
        requests = ((summary.get('budget') or {}).get('requests') or [])
        recorded_error = summary.get('error')
        error_code = fixed_error_code(recorded_error)
        log_hits = classify_private_logs(z)
        if error_code == 'NO_RECORDED_ERROR' and log_hits:
            error_code = log_hits[0]

        expected_files = {
            'original_input': 'original-model/original-input.json',
            'request_body': 'original-model/request-body.json',
            'provider_response': 'original-model/provider-response.txt',
            'original_result': 'original-model/original-result.json',
            'probe_summary': 'original-model/probe-summary.json',
            'preflight': 'preflight.json',
            'call_intent_receipt': 'call-intent-receipt.json',
            'native_stdout': 'native-stdout.log',
            'native_stderr': 'native-stderr.log',
        }
        presence = {key: value in names for key, value in expected_files.items()}
        manifest_rows = manifest.get('files') if isinstance(manifest, dict) else None

        report = {
            'schema': 'dsa-o-native-private-reconciliation-v1',
            'run_id': EXPECTED_RUN_ID,
            'o_disarmed': True,
            'model_key_exposed': False,
            'canonical_native_count': 1,
            'canonical_claim_count': 1,
            'archive_sha_verified': True,
            'bundle_manifest_restore_verified': True,
            'manifest_file_count': len(manifest_rows) if isinstance(manifest_rows, list) else None,
            'native_process_exit_code': process.get('native_process_exit_code'),
            'summary_process_status_present': 'process_status' in summary,
            'input_validated': summary.get('input_validated'),
            'model_http_requests': len(requests),
            'provider_request_body_present': presence['request_body'],
            'provider_response_present': presence['provider_response'],
            'original_input_present': presence['original_input'],
            'original_result_present': presence['original_result'],
            'probe_summary_present': presence['probe_summary'],
            'preflight_present': presence['preflight'],
            'call_intent_receipt_present': presence['call_intent_receipt'],
            'fixed_error_code': error_code,
            'fixed_log_classifications': log_hits,
            'raw_private_content_disclosed': False,
            'repeat_model_request_permitted': False,
        }
        print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except StoreError as exc:
        print(json.dumps({
            'schema': 'dsa-o-native-private-reconciliation-v1',
            'status': 'FAILED',
            'fixed_error_code': str(exc),
            'raw_private_content_disclosed': False,
            'model_http_requests': 0,
            'repeat_model_request_permitted': False,
        }, sort_keys=True))
        raise SystemExit(1) from None
