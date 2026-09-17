"""Recover exact private originals and persist free, separate derived reviews."""
import argparse,hashlib,json,os,tempfile
from pathlib import Path
from datetime import datetime,timezone
import httpx
from dsa_drive_store import DriveStore,scoped_token,API,checked_id,StoreError
from dsa_private_multipart import restore,save
from u_report_release_view import build_release
from run_u_bounded_member_review import validate_member
from o_single_output_fact_check import check_saved_output
from o_provider_completion import inspect_completion


def recover_artifact(store,artifact_id,expected,folder):
    checked_id(artifact_id)
    r=store.request('GET',API+'/files',params={'q':"'"+store.folder+"' in parents and trashed=false and appProperties has { key='artifact_id' and value='"+artifact_id+"-INDEX' }",'fields':'files(id,appProperties),nextPageToken','pageSize':100}).json()
    if r.get('nextPageToken') or len(r.get('files',[]))!=1:raise StoreError('PRIVATE_INDEX_NOT_UNIQUE')
    m=r['files'][0]
    if m['appProperties'].get('sha256')!=expected:raise StoreError('PRIVATE_INDEX_HASH_CHANGED')
    folder.mkdir(parents=True,exist_ok=False);idx=folder/'index.json';store.recover(m['id'],expected,idx);manifest=json.loads(idx.read_text());parts=[]
    for i,part in enumerate(manifest['private_storage']):
        p=folder/('part'+str(i));store.recover(part['file_id'],part['sha256'],p);parts.append(p.read_bytes())
    return restore(manifest,parts)


def main():
    p=argparse.ArgumentParser();p.add_argument('--packet',type=Path,required=True);p.add_argument('--scope',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();s=json.loads(a.scope.read_text());a.out.mkdir(exist_ok=False,parents=True)
    packet=json.loads(a.packet.read_text());assert hashlib.sha256(a.packet.read_bytes()).hexdigest()==s['packet_sha256'];by={r['code']:r for r in packet['members']}
    result={'run_id':s['run_id'],'model_calls':0,'fee_cny':'0','status':'PENDING','formal_BUY':0,'journal_writes':0}
    try:
        with tempfile.TemporaryDirectory() as td,httpx.Client(timeout=30,follow_redirects=False) as c:
            c.headers['Authorization']='Bearer '+scoped_token(c);store=DriveStore(c,os.environ['DSA_DRIVE_FOLDER_ID']);store.private_meta(store.folder,folder=True)
            td=Path(td);derived=td/'derived';derived.mkdir();views=[];receipts=[];raw_bad=[]
            for i,item in enumerate(s['u_originals']):
                raw=recover_artifact(store,item['artifact_id'],item['sha256'],td/('U'+str(i)))
                doc=json.loads(raw['validated-reviews.json'])
                for row in doc['accepted']:
                    try:validate_member(row,by[row['code']])
                    except ValueError as exc:raw_bad.append({'code':row['code'],'reason':str(exc)})
                    view,receipt=build_release(row,by[row['code']]);views.append(view);receipts.append(receipt)
            if len(views)!=44 or len({r['code'] for r in views})!=44:raise ValueError('U_REPLAY_DENOMINATOR_MISMATCH')
            now=datetime.now(timezone.utc).isoformat();payload={'available_at':now,'input_packet_sha256':s['packet_sha256'],'members':views,'receipts':receipts,'raw_isolations_retained':raw_bad,'no_trade_signal':True}
            (derived/'U_CORRECTED_BOUNDED_REVIEWS.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
            o=s['o_original'];raw=recover_artifact(store,o['artifact_id'],o['sha256'],td/'O');decode=lambda key:json.loads(raw[key])
            oaudit=check_saved_output(decode('preflight/preflight.json'),decode('native/original-input.json'),decode('native/pipeline-final-result.json'))
            completion=inspect_completion(raw['native/provider-response.txt'])
            oresult={'complete_answer':completion['status']=='PASS','completion':completion,'semantic_audit':oaudit,'full_report_accepted':False,'original_sha256':hashlib.sha256(raw['native/pipeline-final-result.json']).hexdigest(),'raw_modified':False}
            (derived/'O_REPLAY_AUDIT.json').write_text(json.dumps(oresult,ensure_ascii=False,indent=2)+'\n')
            receipt=save(derived,s['artifact_prefix'],s['run_id'],store)
            result.update(status='PASS_PRIVATE_REPLAY_SAVED',private_persistence=receipt,U_originals_restored=2,U_reviews=44,U_raw_isolations=len(raw_bad),U_corrected_members=sum(bool(r['changes']) for r in receipts),
                U_release_body_sha256=hashlib.sha256((derived/'U_CORRECTED_BOUNDED_REVIEWS.json').read_bytes()).hexdigest(),O_original_restored=True,O_complete_answer=oresult['complete_answer'],O_full_report_accepted=False,O_remaining_guards=oaudit['triggered_semantic_guards'],completed_at=now)
    except Exception as exc:result.update(status='FAIL',reason=type(exc).__name__)
    (a.out/'SANITIZED_REPLAY_RECEIPT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if result['status']!='PASS_PRIVATE_REPLAY_SAVED':raise SystemExit(1)

if __name__=='__main__':main()
