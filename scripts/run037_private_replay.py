"""Free storage replay of existing immutable originals, never a new model result."""
import argparse,json,os,tempfile,zipfile
from pathlib import Path
import httpx
from dsa_drive_store import DriveStore,scoped_token,API,checked_id
from dsa_drive_bundle import verify_bundle,bundle
from dsa_private_multipart import save


def main():
    p=argparse.ArgumentParser();p.add_argument('--scope',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();s=json.loads(a.scope.read_text());a.out.mkdir(parents=True,exist_ok=False)
    with httpx.Client(timeout=30,follow_redirects=False) as c,tempfile.TemporaryDirectory() as td:
        c.headers['Authorization']='Bearer '+scoped_token(c);store=DriveStore(c,os.environ['DSA_DRIVE_FOLDER_ID']);root=Path(td)/'combined';root.mkdir()
        for row in s['private_replay_parents']:
            artifact=checked_id(row['artifact_id']);store.private_meta(store.folder,folder=True)
            q="'"+store.folder+"' in parents and trashed=false and appProperties has { key='artifact_id' and value='"+artifact+"' }"
            matches=store.request('GET',API+'/files',params={'q':q,'fields':'files(id),nextPageToken','pageSize':2}).json()
            assert len(matches.get('files',[]))==1 and not matches.get('nextPageToken'),'PRIVATE_PARENT_NOT_UNIQUE'
            dest=Path(td)/(row['label']+'.zip');store.recover(matches['files'][0]['id'],row['sha256'],dest);verify_bundle(dest.read_bytes())
            target=root/row['label'];target.mkdir()
            with zipfile.ZipFile(dest) as z:
                for name in z.namelist():
                    if name=='MANIFEST.json':continue
                    path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(name))
        old_error=None
        try:bundle(root,s['run_id'],'ART-DSA-RUN037-SINGLE-PACK-PROBE')
        except Exception as exc:old_error=str(exc)
        assert old_error=='BUNDLE_TOO_LARGE','Exact realistic size failure must be reproduced'
        result=save(root,'ART-DSA-RUN037-EXISTING-RAW-MULTIPART',s['run_id'],store)
        result.update(run_id=s['run_id'],workflow_run=os.environ['GITHUB_RUN_ID'],scope='Storage engineering replay of old immutable originals; no new prediction',old_single_pack_failure=old_error,model_requests=0,fee_cny='0',originals_changed=False)
        (a.out/'PRIVATE_REPLAY_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print('PRIVATE_REPLAY_RESULT '+json.dumps(result))
if __name__=='__main__':main()
