"""Replay one immutable historical analyzer-return bundle, entirely offline.

Do not extract credentials or run any code inside the evidence ZIP. This tool
writes a private audit plus a sanitized receipt; it never edits the source ZIP.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from o_post_output_contract import CONTRACT_VERSION, EARLY_STAGE, evaluate_post_output_contract, output_exit_code
from o_capture_stage_provenance import prove_capture_stage, assess_saved_count_stage


def replay(bundle_path, expected_sha256, source_root, output):
    bundle_path, source_root, output = map(Path, (bundle_path, source_root, output))
    before = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if before != expected_sha256:
        raise ValueError('PARENT_BUNDLE_HASH_MISMATCH')
    with zipfile.ZipFile(bundle_path) as z:
        if z.testzip() is not None:raise ValueError('ZIP_CRC_MISMATCH')
        manifest=json.loads(z.read('MANIFEST.json'))
        for item in manifest['files']:
            name=item['path'];p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts:raise ValueError('UNSAFE_MANIFEST_PATH')
            # Hash all members but never decode or export credential-like files.
            raw=z.read(name)
            if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise ValueError('MANIFEST_MEMBER_MISMATCH')
        p=json.loads(z.read('preflight.json'))
        i=json.loads(z.read('original-model/original-input.json'))
        r=json.loads(z.read('original-model/original-result.json'))
        budget=json.loads(z.read('original-model/budget.json'))
        source_hashes={n:hashlib.sha256(z.read(n)).hexdigest() for n in (
            'preflight.json','original-model/original-input.json','original-model/original-result.json',
            'original-model/request-body.json','original-model/provider-response.txt')}
    proof=prove_capture_stage(**{name:(source_root/path).read_bytes() for name,path in {
        'analyzer':'analyzer.py','pipeline':'pipeline.py','observer':'historical_observer.py'}.items()})
    stage=assess_saved_count_stage(r,proof)
    contract=evaluate_post_output_contract(p,i,r,capture_receipt={'stage':EARLY_STAGE})
    codes=contract['promotion_gate']['blockers']
    assert stage['status']=='UNKNOWN_AT_CAPTURE_STAGE'
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' not in codes
    assert 'OPEN_GAP_DIRECTION_CONTRADICTION' in codes
    assert all(contract['formal_semantic_gates'][g]=='BLOCK' for g in ('SEM-001','SEM-002','SEM-003'))
    request_count=len(budget['requests'])
    exit_code=output_exit_code(contract,request_count=request_count)
    assert exit_code==1
    after=hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert before==after
    output.mkdir(parents=True,exist_ok=False)
    (output/'PRIVATE_REPLAY_DETAIL.json').write_text(json.dumps({'historical_stage':stage,'contract':contract},ensure_ascii=False,indent=2))
    summary={'run_id':'TRI-DSA-DEV-20260916-025','scope':'ONE_INCREMENTAL_HISTORICAL_OFFLINE_REPLAY',
        'source_child_artifact':'ART-DSA-RUN018-ZEROHTTP-RECOVERY-CHILD2',
        'source_bundle_sha256_before':before,'source_bundle_sha256_after':after,
        'parent_manifest_members_verified':len(manifest['files']),'manifest_mismatches':0,
        'source_file_sha256':source_hashes,'contract_version':CONTRACT_VERSION,
        'historical_capture_stage':EARLY_STAGE,'final_count_status':stage['status'],
        'prior_count_false_positive_removed':True,'raw_fields_changed':False,
        'opening_contradiction_retained':True,'sem_gates':contract['formal_semantic_gates'],
        'promotion_gate':'BLOCK','blocker_codes':codes,'actual_wrapper_exit_code':exit_code,
        'technical_execution_history':'PASS_PRESERVED','historical_request_count':request_count,
        'new_model_requests':0,'new_model_tokens':0,'new_model_provider_cost_cny':0,
        'historical_child2_formal_acceptance':'FAIL_RETAINED','g4_3_credit':False,
        'runtime_activated':False,'private_raw_published':False}
    (output/'RUN025_CHILD2_REPLAY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--source-root',required=True);parser.add_argument('--output',required=True)
    a=parser.parse_args();print(json.dumps(replay(a.bundle,a.sha256,a.source_root,a.output),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
