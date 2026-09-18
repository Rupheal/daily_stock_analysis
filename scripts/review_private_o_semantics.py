"""Generic sanitized semantic attribution for one restored private O-member tree.

No provider/model call. Raw prompt/response/model content is read only inside the
runner and never emitted; only guard IDs, paths, hashes and disposition leave the
private restore boundary.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from o_single_output_fact_check import check_saved_output

PATTERNS=[
    re.compile(r'未见.{0,16}(?:利空|重大利空|负面|处罚|减持|公告)'),
    re.compile(r'未发现.{0,16}(?:利空|重大利空|负面|处罚|减持|公告)'),
    re.compile(r'没有.{0,12}(?:利空|重大利空|负面|处罚|减持|公告)'),
    re.compile(r'暂无.{0,12}(?:利空|重大利空|负面|处罚|减持|公告)'),
    re.compile(r'近.{0,6}(?:日|天)无.{0,16}(?:利空|负面|处罚|减持|业绩)'),
]

def one(root:Path,suffix:str):
    hits=[p for p in root.rglob('*') if p.is_file() and p.as_posix().endswith(suffix)]
    if len(hits)!=1: raise ValueError('PRIVATE_REQUIRED_FILE_NOT_UNIQUE:'+suffix)
    return hits[0]

def sem(a,g):
    return [{'code':x.get('code'),'paths':x.get('paths')} for x in a.get('findings',[]) if x.get('guard_id')==g]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--code',required=True)
    ap.add_argument('--expected-provider-sha256',required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    p=one(a.root,'preflight/preflight.json'); i=one(a.root,'native/original-input.json')
    ar=one(a.root,'native/original-result.json'); fr=one(a.root,'native/pipeline-final-result.json')
    pc=one(a.root,'native/post-output-contract.json'); pr=one(a.root,'native/provider-response.txt')
    got=hashlib.sha256(pr.read_bytes()).hexdigest()
    if got!=a.expected_provider_sha256: raise ValueError('PROVIDER_RESPONSE_HASH_MISMATCH')
    pre=json.loads(p.read_text()); inp=json.loads(i.read_text())
    analyzer=json.loads(ar.read_text()); final=json.loads(fr.read_text()); post=json.loads(pc.read_text())
    aa=check_saved_output(pre,inp,analyzer); fa=check_saved_output(pre,inp,final)
    raw=pr.read_text(errors='replace')
    provider_sem002=any(x.search(raw) for x in PATTERNS)
    analyzer_sem002=bool(sem(aa,'SEM-002')); final_sem002=bool(sem(fa,'SEM-002'))
    if provider_sem002 or analyzer_sem002:
        disposition='PERMANENT_ISOLATE_NO_RETRY'
    elif final_sem002:
        disposition='DOWNSTREAM_SEM002_REQUIRES_SEPARATE_CONTRACT'
    else:
        disposition='NO_SEM002_IN_CHECKED_LAYERS'
    out={
      'schema_version':1,'code':a.code,'private_restore_hash_verified':True,
      'provider_response_sha256':got,'provider_sem002_pattern_present':provider_sem002,
      'analyzer_semantic_gates':sorted(aa.get('triggered_semantic_guards') or []),
      'analyzer_sem001_findings':sem(aa,'SEM-001'),'analyzer_sem002_findings':sem(aa,'SEM-002'),'analyzer_sem003_findings':sem(aa,'SEM-003'),
      'pipeline_semantic_gates':sorted(fa.get('triggered_semantic_guards') or []),
      'pipeline_sem001_findings':sem(fa,'SEM-001'),'pipeline_sem002_findings':sem(fa,'SEM-002'),'pipeline_sem003_findings':sem(fa,'SEM-003'),
      'saved_post_output_blockers':(post.get('promotion_gate') or {}).get('blockers',[]),
      'disposition':disposition,'repeat_model_request_permitted':False,
      'model_http_requests_added':0,'raw_content_public':False
    }
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'code':a.code,'provider_sem002':provider_sem002,'analyzer_sem002':analyzer_sem002,'pipeline_sem002':final_sem002,'disposition':disposition,'model_requests_added':0}))
if __name__=='__main__': main()
