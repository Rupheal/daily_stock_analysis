import copy,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from dsa_private_multipart import prepare,restore,save,PART_BYTES
from dsa_drive_store import StoreError,LIMIT,digest


def test_lossless_original_evidence_larger_than_single_store_limit(tmp_path):
    (tmp_path/'native').mkdir();a=b'raw response\n'*360000;b=b'original sqlite bytes'*65000
    (tmp_path/'native'/'provider-response.txt').write_bytes(a);(tmp_path/'db').write_bytes(b);(tmp_path/'empty').write_bytes(b'')
    m,p=prepare(tmp_path,'RUN-TEST','ART-TEST')
    assert sum(map(len,p))>LIMIT and all(len(x)<LIMIT for x in p)
    assert restore(m,p)=={'native/provider-response.txt':a,'db':b,'empty':b''}
    wrong=copy.deepcopy(m);wrong['files'][0]['chunks'][0]['offset']=1
    with pytest.raises(StoreError):restore(wrong,p)


def test_credential_crossing_chunk_boundary_rejected_before_upload(tmp_path,monkeypatch):
    secret='synthetic-secret-credential-12345';monkeypatch.setenv('TEST_API_KEY',secret)
    (tmp_path/'raw').write_bytes(b'x'*(PART_BYTES-8)+secret.encode()+b'y')
    class NoWrite:
        def put(self,*args):pytest.fail('Secret bytes must be rejected before storage')
    with pytest.raises(StoreError,match='CREDENTIAL_BYTES_DETECTED'):save(tmp_path,'ART-TEST','RUN-TEST',NoWrite())


def test_all_parts_and_index_readback_required(tmp_path):
    (tmp_path/'raw').write_bytes(b'x'* (PART_BYTES+9))
    class Store:
        def __init__(self):self.data={}
        def put(self,name,data,run):
            self.data[name]=data;return {'file_id':name,'sha256':digest(data)}
        def recover(self,name,sha,dest):
            assert digest(self.data[name])==sha;dest.write_bytes(self.data[name])
    s=Store();r=save(tmp_path,'ART-TEST','RUN-TEST',s)
    assert r['parts']==2 and r['save_read_hash_restore'] and 'ART-TEST-INDEX' in s.data
