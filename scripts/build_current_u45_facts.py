"""Reusable U facts from verified market cache; never O scores or inferred fills."""
import argparse,hashlib,json,math,zipfile
from pathlib import Path
from datetime import datetime,timezone


def main():
    p=argparse.ArgumentParser()
    for x in ['archive','recovery','history','universe','out']:p.add_argument('--'+x,type=Path,required=True)
    a=p.parse_args();raw=a.archive.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='158168b4959304cc912e6dbce6ae9c2c680e9c8bb4b721df86ffc0fd9a0ff4ce'
    with zipfile.ZipFile(a.archive) as z:
        paths=[n for n in z.namelist() if n.endswith('market-history.json')];assert len(paths)==1
        market_raw=z.read(paths[0]);assert hashlib.sha256(market_raw).hexdigest()=='489ea5927b6543fd24bfb033eb330c7e1409e692baaaf83b05e86b44800970d9'
        market=json.loads(market_raw)
    recovery=json.loads(a.recovery.read_text());history=json.loads(a.history.read_text());u=json.loads(a.universe.read_text())
    assert market['target_session']==recovery['target']==history['target_session'] and u['member_count']==len(u['members'])==45
    provenance={x['code']:x for x in recovery['rows']};rows=[]
    for member in u['members']:
        code=member['code'];base={'code':code,'name':member.get('official_name') or member['user_alias'],'market_session':market['target_session'],
            'price_time':None,'price_time_note':'Completed daily bar date only; not a timestamped executable quote',
            'facts':None,'rank':None,'score':None,'action':'NO_FORMAL_SIGNAL','execution_price':None}
        bars=market['histories'].get('hk'+code) or []
        if not bars:
            base['reason']='NOT_IN_THIS_ACCEPTED_CACHE_RETAINED_IN_U45';rows.append(base);continue
        assert len(bars)==21 and bars[-1]['date']==market['target_session']
        last=bars[-1];closes=[x['close'] for x in bars];pct=(closes[-1]/closes[-2]-1)*100
        assert abs(pct-last['pct_chg'])<1e-8
        facts={k:last[k] for k in ['open','high','low','close','volume','amount','pct_chg','ma5','ma10','ma20','volume_ratio']}
        for days in (5,10,20):
            mean=sum(closes[-days:])/days;assert abs(mean-last['ma'+str(days)])<=.00500001
        ratio=last['volume']/(sum(x['volume'] for x in bars[-6:-1])/5)
        assert abs(ratio-last['volume_ratio'])<=.00500001
        facts.update(return_5d_pct=(closes[-1]/closes[-6]-1)*100,return_20d_pct=(closes[-1]/closes[-21]-1)*100)
        assert all(v is None or math.isfinite(v) for v in facts.values())
        source=history['histories'][code]['independent_source'];rec=provenance[code]
        base.update(facts=facts,data_source=last['data_source'],basis='Declared native/Run006 adjusted research series; corporate-action execution basis not asserted',
                    independent_source_locator=source.get('url'),independent_source_sha256=source.get('sha256'),
                    retrieved_at=rec.get('raw_available_at') or source.get('retrieved_at'),
                    indicator_checks='Daily return, MA5/10/20 and volume ratio recomputed from all accepted bars; no score calculation')
        rows.append(base)
    result={'run_id':'TRI-DSA-EXEC-20260917-038-FACTS','generated_at':datetime.now(timezone.utc).isoformat(),'U_denominator':45,
            'facts_available':sum(x['facts'] is not None for x in rows),'formal_signals':0,'model_calls':0,'fee_cny':'0',
            'source_archive_sha256':hashlib.sha256(raw).hexdigest(),'market_history_sha256':hashlib.sha256(market_raw).hexdigest(),
            'scope':'Reusable U per-member public facts only; independent candidate selection and no O rankings; cannot backfill AM snapshot or create simulated fill','rows':rows}
    a.out.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
