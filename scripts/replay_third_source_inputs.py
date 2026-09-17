"""Model/network-free replay of three captured publisher histories.

Never reruns accepted598 or overwrites old62 failures. A whole-window second
publisher can support either original Yahoo or Tencent; no fieldwise voting.
"""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from reconcile_hk_third_source import whole_window_agrees
from audit_dual_history_cache import normalized

CONTRACT='RUN045_THIRD_PUBLISHER_INPUT_REPAIR_v1'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def proof(a,b,target,left,right):
    d=whole_window_agrees(a,b,target);d['left_publisher']=left;d['right_publisher']=right
    for x in d.get('conflict_examples',[]):
        x['left_raw']=x.pop('yahoo_raw');x['right_raw']=x.pop('tencent_raw')
    return d


def main():
    p=argparse.ArgumentParser()
    for k in ['prior','third','parent','out','scope']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();s=json.loads(a.scope.read_text());priorp=a.prior/'CURRENT_RECOVERY.json';thirdp=a.third/'THIRD_SOURCE_RESULT.json'
    assert sha(priorp)==s['prior_sha256'] and sha(thirdp)==s['third_result_sha256'] and sha(a.parent)==s['parent_sha256']
    prior=json.loads(priorp.read_text());third=json.loads(thirdp.read_text());h=json.loads(a.parent.read_text());target=prior['target'];rows=[];inputs=dict(prior['inputs']);checks=[]
    assert target==third['target_session']==h['target_session']==s['target_session']
    tm={r['code']:r for r in third['rows']}
    for old in prior['rows']:
        code=old['code'];row=dict(old)
        if old['route']!='ISOLATED':rows.append(row);continue
        detail={'code':code,'old_reasons':old['reasons'],'status':'ISOLATED'}
        try:
            srp=a.third/code/'sina-raw.js';sn=a.third/code/'sina-normalized.json'
            if sha(srp)!=tm[code]['source_sha256']:raise ValueError('SINA_ORIGINAL_HASH_MISMATCH')
            # The original Run043 parser-derived file is part of its verified ZIP.
            sr=normalized([x for x in json.loads(sn.read_text()) if x['date']<=target][-21:],target)
            if sr[-1]['volume']<=0:raise ValueError('NO_TRADE_ON_TARGET')
            tpath=a.prior/'raw'/(code+'-tencent-raw.json');ypath=a.prior/'raw'/(code+'-yahoo-raw.json')
            tr=[];yr=[]
            if tpath.exists():
                assert sha(tpath)==old['tencent_raw_sha256']
                bb=json.loads(tpath.read_text())['data']['hk'+code].get('day',[])
                tr=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in bb if b[0]<=target]
            if ypath.exists():
                assert sha(ypath)==old['yahoo_raw_sha256'];yr=json.loads(ypath.read_text())['rows']
            st=proof(sr,tr,target,'Sina','Tencent');sy=proof(sr,yr,target,'Sina','Yahoo')
            detail.update(sina_vs_tencent=st,sina_vs_yahoo=sy,source_locator=tm[code]['source_locator'],source_sha256=sha(srp))
            if st['accepted']:
                qp=a.prior/'raw'/(code+'-qfq.json')
                if qp.exists() and old.get('new_qfq_sha256')==sha(qp):
                    v=json.loads(qp.read_text())['data']['hk'+code];bb=v.get('qfqday') or v.get('day') or []
                    q=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in bb]
                    detail['adjusted_cache_origin']='Run035 newly captured qfq original';detail['adjusted_source_sha256']=sha(qp)
                else:
                    q=h['histories'][code].get('tencent') or []
                q=normalized([x for x in q if x['date']<=target][-21:],target)
                if [x['date'] for x in q]!=[x['date'] for x in sr] or any(x['volume']!=y['volume'] for x,y in zip(q,sr)):raise ValueError('QFQ_DATE_VOLUME_CONFLICT')
                item={'rows':q,'source':'Tencent:qfq+Sina_raw_support','recovery':True,'independent_history_full_window_passed':False}
                detail['status']='SINA_SUPPORTS_TENCENT_RAW'
            elif sy['accepted']:
                native=normalized(h['histories'][code]['native'][-21:],target)
                ns=proof(native,sr,target,'NativeYahoo','Sina');ny=proof(native,yr,target,'NativeYahoo','YahooRaw')
                if not ns['accepted'] or not ny['accepted']:raise ValueError('NATIVE_ADJUSTED_NOT_SUPPORTED_BY_RAW')
                detail.update(status='SINA_SUPPORTS_ORIGINAL_YAHOO',native_vs_sina=ns,native_vs_yahoo_raw=ny)
                item={'rows':native,'source':'native-original+Sina_raw_support','recovery':True,'independent_history_full_window_passed':False}
            else:raise ValueError('THIRD_SOURCE_CONFLICT_REMAINS')
            inputs[code]=item;row.update(route='THIRD_PUBLISHER_RECOVERY',input_source=item['source'],prior_isolation_reasons=old['reasons'],reasons=[],third_publisher_proof=detail)
        except (ValueError,KeyError,TypeError,AssertionError,FileNotFoundError) as exc:
            detail['reason']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        checks.append(detail);rows.append(row)
    result={'run_id':s['run_id'],'native_acceptance_run_id':s['run_id'],'contract_id':CONTRACT,'parent_contract_id':prior['contract_id'],
        'parent_recovery_sha256':sha(priorp),'third_result_sha256':sha(thirdp),'target':target,
        'O_denominator':660,'U_denominator':45,'rows':rows,'inputs':inputs,
        'input_ready':len(inputs),'retained_old_ready':len(prior['inputs']),'new_recovered':len(inputs)-len(prior['inputs']),
        'isolated':660-len(inputs),'checks':checks,'generated_at':datetime.now(timezone.utc).isoformat(),
        'model_requests':0,'fee_cny':'0','historical_predictions_modified':False}
    assert len(rows)==660 and all(inputs[k]==v for k,v in prior['inputs'].items())
    a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'CURRENT_RECOVERY.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
    public={k:v for k,v in result.items() if k not in ('rows','inputs')};public['recovery_sha256']=sha(a.out/'CURRENT_RECOVERY.json')
    (a.out/'REPLAY_RESULT.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in public.items() if k!='checks'}))

if __name__=='__main__':main()
