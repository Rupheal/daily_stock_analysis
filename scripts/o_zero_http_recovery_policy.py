"""Deterministic policy for a durable O claim that failed before provider HTTP.

This module never deletes/reuses canonical evidence and never authorizes a model
request by itself. It only classifies whether the existing immutable evidence
is eligible to be presented for a separate explicit recovery authorization.
"""
from __future__ import annotations

REQUIRED_TRUE = (
    'o_disarmed',
    'archive_sha_verified',
    'bundle_manifest_restore_verified',
    'call_intent_receipt_present',
    'probe_summary_present',
    'preflight_present',
)
REQUIRED_FALSE = (
    'model_key_exposed',
    'provider_request_body_present',
    'provider_response_present',
    'original_input_present',
    'original_result_present',
)
PRE_REQUEST_ERRORS = {
    'NATIVE_SESSION_MISMATCH',
    'NATIVE_VOLUME_MISMATCH',
    'NATIVE_PRICE_MISMATCH_OPEN',
    'NATIVE_PRICE_MISMATCH_HIGH',
    'NATIVE_PRICE_MISMATCH_LOW',
    'NATIVE_PRICE_MISMATCH_CLOSE',
}


def classify_zero_http_recovery(report, *, owner_authorized=False):
    reasons=[]
    if report.get('canonical_claim_count') != 1:
        reasons.append('CLAIM_COUNT_NOT_ONE')
    if report.get('canonical_native_count') != 1:
        reasons.append('CANONICAL_NATIVE_COUNT_NOT_ONE')
    for key in REQUIRED_TRUE:
        if report.get(key) is not True:
            reasons.append('REQUIRED_TRUE_MISSING_' + key.upper())
    for key in REQUIRED_FALSE:
        if report.get(key) is not False:
            reasons.append('REQUIRED_FALSE_VIOLATED_' + key.upper())
    if report.get('model_http_requests') != 0:
        reasons.append('MODEL_HTTP_REQUEST_ALREADY_OCCURRED')
    if report.get('input_validated') is not False:
        reasons.append('INPUT_VALIDATION_STATE_NOT_FALSE')
    if report.get('native_process_exit_code') != 1:
        reasons.append('NATIVE_PROCESS_NOT_PRE_REQUEST_FAILURE')
    if report.get('fixed_error_code') not in PRE_REQUEST_ERRORS:
        reasons.append('ERROR_NOT_APPROVED_PRE_REQUEST_CLASS')
    if report.get('repeat_model_request_permitted') is not False:
        reasons.append('SOURCE_RECONCILIATION_ALREADY_PERMITS_REPEAT')

    evidence_recoverable = not reasons
    # A clean evidence classification is deliberately not sufficient authority.
    request_authorized = bool(evidence_recoverable and owner_authorized)
    return {
        'schema':'dsa-o-zero-http-recovery-policy-v1',
        'evidence_recoverable':evidence_recoverable,
        'owner_authorized':bool(owner_authorized),
        'request_authorized':request_authorized,
        'state':('AUTHORIZED_ONE_SUCCESSOR_ATTEMPT' if request_authorized else
                 'RECOVERABLE_BUT_NOT_AUTHORIZED' if evidence_recoverable else
                 'NOT_RECOVERABLE'),
        'reasons':reasons,
        'canonical_claim_must_remain':True,
        'canonical_native_artifact_must_remain':True,
        'canonical_ids_may_not_be_deleted_or_overwritten':True,
        'successor_evidence_requires_new_append_only_child_artifact':True,
        'maximum_successor_http_requests':1 if request_authorized else 0,
    }
