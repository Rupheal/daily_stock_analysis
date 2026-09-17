"""Consume actual Run032 receipts and bounded issuer evidence; never create a trade."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from build_u45_prep_ledger import reviewed_news_ready

def only(root,name):
    paths=list(Path(root).rglob(name))
    if len(paths)!=1:raise ValueError('AMBIGUOUS_OR_MISSING_INPUT:'+name)
    p=paths[0];return json.loads(p.read_text()),hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--artifacts',required=True);p.add_argument('--review',required=True);p.add_argument('--evidence',required=True);p.add_argument('--title-review',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result,original_sha=only(a.artifacts,'RUN032_READINESS.json');coverage,cov_sha=only(a.artifacts,'coverage.json');providers,pv_sha=only(a.artifacts,'U45_PROVIDER_READINESS.json')
    review=json.loads(Path(a.review).read_text());evidence_sha=hashlib.sha256(Path(a.evidence).read_bytes()).hexdigest();correction=json.loads(Path(a.title_review).read_text());news,news_sha=only(a.artifacts,'U45_NEWS_MULTISOURCE.json')
    assert correction['parent_source_sha256']==news_sha
    now=datetime.now(timezone.utc).isoformat();target=result['price_session']
    failures=[{'code':x['code'],'status':x['status'],'bars':x.get('bars'),'latest_date':x.get('latest_date'),'error':x.get('error')} for x in coverage['coverage'] if x['status']!='current_valid_bar']
    for row in result['U']['members']:
        row['reviewed_news_evidence_ready']=reviewed_news_ready(row['code'],target,review,evidence_sha,now)
        if row['code']=='00388':row['news_relevance_ready']=False
        if row['reviewed_news_evidence_ready']:
            row['missing_reasons']=[x for x in row['missing_reasons'] if x!='NEWS_RETRIEVAL_IS_NOT_REVIEWED_EVIDENCE']+['BROADER_NEWS_RISK_COVERAGE_NOT_COMPLETE']
        # A bounded news component is never the full stock acceptance.
        assert row['formal_accepted'] is False
    result['U']['reviewed_news_evidence_ready']=sum(x['reviewed_news_evidence_ready'] for x in result['U']['members'])
    result['U']['news_relevance_ready']=sum(x['news_relevance_ready'] for x in result['U']['members'])
    result.update(run_id='TRI-DSA-EXEC-20260917-032-HANDOFF1',parent_workflow_run=35178119846,reviewed_at=now,O_data_failures=failures,
      U_provider_failures=[x for x in providers['members'] if not x['provider_target_crosscheck']],source_hashes={'parent_readiness':original_sha,'coverage':cov_sha,'providers':pv_sha,'news':news_sha,'primary_evidence':evidence_sha},
      entry_handoff='NO_QUALIFIED_SIGNAL; original AM expiry and accounts unchanged; no retroactive BUY')
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:({x:y for x,y in v.items() if x!='members'} if isinstance(v,dict) else v) for k,v in result.items() if k not in ('input_sha256','source_hashes')},ensure_ascii=False))
if __name__=='__main__':main()
