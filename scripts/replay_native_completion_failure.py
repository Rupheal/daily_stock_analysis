"""Re-evaluate the preserved failed Run039 output without another provider call."""
import argparse,hashlib,json
from pathlib import Path
from o_native_context_canonical import install_into_semantic_contract
install_into_semantic_contract()
from o_provider_completion import inspect_completion
from o_post_output_contract import evaluate_post_output_contract
from o_release_quote_semantics import build_release_view,ReleaseQuoteError


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    before={str(x.relative_to(a.source)):hashlib.sha256(x.read_bytes()).hexdigest() for x in a.source.rglob('*') if x.is_file()}
    def get(name):return json.loads((a.source/name).read_text())
    pf=get('preflight/preflight.json');original=get('native/original-input.json');final=get('native/pipeline-final-result.json');cap=get('native/pipeline-final-capture.json');analyzer=get('native/original-result.json')
    completion=inspect_completion((a.source/'native/provider-response.txt').read_bytes())
    post=evaluate_post_output_contract(pf,original,final,capture_receipt=cap,analyzer_result=analyzer,expected_sources=cap['source_proof'],
        prompt_text=(a.source/'native/original-formatted-prompt.txt').read_text(),news_handoff=get('native/news-handoff-receipt.json'),required_handoff=True)
    rejected=None
    try:build_release_view(pf,original,final)
    except ReleaseQuoteError as exc:rejected=str(exc)
    assert completion['status']=='BLOCK' and completion['content_chars']==0 and 'PROVIDER_OUTPUT_TRUNCATED' in completion['blockers']
    assert post['promotion_gate']['status']=='BLOCK' and 'NATIVE_ANALYSIS_SUCCESS_NOT_PROVEN' in post['promotion_gate']['blockers']
    assert rejected=='RELEASE_NATIVE_ANALYSIS_FAILED'
    after={str(x.relative_to(a.source)):hashlib.sha256(x.read_bytes()).hexdigest() for x in a.source.rglob('*') if x.is_file()};assert before==after
    result={'run_id':'TRI-DSA-EXEC-20260917-040','scope':'Actual private failed provider result and native error default replay; not a new model opinion',
        'parent_workflow_run':35183191883,'private_index_sha256':'5655e0533f80cfb2ea640ccba31142adb07f672930b5daf1bd75f5d5af86b5ad',
        'status':'PASS_FAILED_OUTPUT_REMAINS_ISOLATED','provider_completion':completion,
        'post_contract_version':post['contract_version'],'post_blockers':post['promotion_gate']['blockers'],
        'release_adapter_rejection':rejected,'original_files_unchanged':len(before),'formal_acceptances_added':0,
        'model_requests':0,'fee_cny':'0','strategy_changes':False,'runtime_changes':False,'new_preflight_contract_note':'Future generic inputs include the existing v2 contract identifier; no retroactive repair of Run039 input'}
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
