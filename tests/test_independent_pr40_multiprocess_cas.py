import importlib.util,json,multiprocessing,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/"audit_fixtures"/"foundation_pr40"
spec=importlib.util.spec_from_file_location("pr40_broker",FIX/"shared_resource_broker.py")
rb=importlib.util.module_from_spec(spec);spec.loader.exec_module(rb)

def worker(path,barrier,q,value):
    store=rb.JsonCASStore(path)
    state,version=store.read()
    state["winner"]=value
    barrier.wait()
    try:
        store.commit(version,state);q.put("OK")
    except rb.CASConflict:
        q.put("CONFLICT")

def test_pr40_multiprocess_cas_exactly_one_writer():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"broker.json"
        p.write_text(json.dumps({"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},"budgets":{}}))
        barrier=multiprocessing.Barrier(2);q=multiprocessing.Queue()
        ps=[multiprocessing.Process(target=worker,args=(p,barrier,q,n)) for n in (1,2)]
        for x in ps:x.start()
        for x in ps:
            x.join(10)
            assert x.exitcode==0
        assert sorted(q.get(timeout=2) for _ in ps)==["CONFLICT","OK"]
