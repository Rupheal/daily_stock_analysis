from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from o_zero_http_recovery_policy import classify_zero_http_recovery


def clean():
    return {
        'o_disarmed':True,'archive_sha_verified':True,'bundle_manifest_restore_verified':True,
        'call_intent_receipt_present':True,'probe_summary_present':True,'preflight_present':True,
        'model_key_exposed':False,'provider_request_body_present':False,'provider_response_present':False,
        'original_input_present':False,'original_result_present':False,'canonical_claim_count':1,
        'canonical_native_count':1,'model_http_requests':0,'input_validated':False,
        'native_process_exit_code':1,'fixed_error_code':'NATIVE_SESSION_MISMATCH',
        'repeat_model_request_permitted':False,
    }

def test_clean_evidence_is_not_self_authorizing():
    r=classify_zero_http_recovery(clean())
    assert r['state']=='RECOVERABLE_BUT_NOT_AUTHORIZED'
    assert r['request_authorized'] is False
    assert r['maximum_successor_http_requests']==0

def test_explicit_owner_authorization_allows_at_most_one_successor():
    r=classify_zero_http_recovery(clean(),owner_authorized=True)
    assert r['state']=='AUTHORIZED_ONE_SUCCESSOR_ATTEMPT'
    assert r['maximum_successor_http_requests']==1
    assert r['canonical_ids_may_not_be_deleted_or_overwritten'] is True
    assert r['successor_evidence_requires_new_append_only_child_artifact'] is True

def test_any_existing_http_request_blocks_recovery():
    x=clean(); x['model_http_requests']=1
    assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'

def test_provider_body_or_response_blocks_zero_http_classification():
    for key in ('provider_request_body_present','provider_response_present'):
        x=clean(); x[key]=True
        assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'

def test_missing_integrity_blocks_recovery():
    for key in ('archive_sha_verified','bundle_manifest_restore_verified','call_intent_receipt_present'):
        x=clean(); x[key]=False
        assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'

def test_claim_or_native_count_not_one_blocks_recovery():
    for key in ('canonical_claim_count','canonical_native_count'):
        x=clean(); x[key]=0
        assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'

def test_post_request_or_unknown_error_blocks_recovery():
    x=clean(); x['fixed_error_code']='PRIVATE_ERROR_OTHER_RUNTIMEERROR'
    assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'

def test_input_validated_true_is_not_this_recovery_class():
    x=clean(); x['input_validated']=True
    assert classify_zero_http_recovery(x)['state']=='NOT_RECOVERABLE'
