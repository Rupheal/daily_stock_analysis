"""Source-derived market timestamps. Retrieval time never becomes a price time."""
import hashlib
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from src.services.dsa_prediction_ledger import canonical_hash,_aware_timestamp


def tencent_hk_observation(raw:bytes, *, code:str, retrieved_at:str, source_locator:str):
    code=code.upper().removeprefix('HK').zfill(5)
    if not re.fullmatch(r'\d{5}',code):raise ValueError('invalid security code')
    text=raw.decode('gb18030')
    m=re.search(r'v_(?:r_)?hk'+code+r'="([^"]+)"',text)
    if not m:raise ValueError('source security absent')
    f=m.group(1).split('~')
    if len(f)<35 or f[2]!=code:raise ValueError('source identity mismatch')
    # The field comes from the provider payload, not the caller clock.
    price_time=datetime.strptime(f[30],'%Y/%m/%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
    retrieved=_aware_timestamp(retrieved_at,'retrieved_at')
    if price_time>retrieved:raise ValueError('source price timestamp in future')
    price=float(f[3]);prior=float(f[4]);change=float(f[31]);pct=float(f[32])
    if not all(math.isfinite(x) for x in (price,prior,change,pct)) or min(price,prior)<=0:
        raise ValueError('invalid source price')
    if abs(price-prior-change)>.011 or abs((price/prior-1)*100-pct)>.02:
        raise ValueError('inconsistent quote arithmetic')
    expected='https://qt.gtimg.cn/q=r_hk'+code
    if source_locator!=expected:raise ValueError('source locator mismatch')
    result={'security_id':'HK'+code,'price':f[3],'currency':'HKD','adjustment':'raw',
            'price_time':price_time.isoformat(),'retrieved_at':retrieved_at,'source_locator':source_locator,
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'timestamp_field':'Tencent payload field30',
            'time_semantics':'PROVIDER_PRICE_TIME','cross_source_verified':False,'reference_only':True}
    result['observation_sha256']=canonical_hash(result)
    return result


def link_price(snapshot,observation,security_id):
    obs=dict(observation);given=obs.pop('observation_sha256')
    if canonical_hash(obs)!=given:raise ValueError('observation mutated')
    if obs['security_id']!=security_id:raise ValueError('wrong security')
    generated=_aware_timestamp(snapshot['generated_at'],'generated_at')
    decision=_aware_timestamp(snapshot['decision_cutoff'],'decision_cutoff')
    if generated<decision:raise ValueError('snapshot unavailable at claimed cutoff')
    pt=_aware_timestamp(obs['price_time'],'price_time')
    if pt<=max(generated,decision):raise ValueError('price not strictly after available decision')
    return {'snapshot_id':snapshot['snapshot_id'],'snapshot_sha256':canonical_hash(snapshot),
            'observation_sha256':given,'security_id':security_id,'price_time':obs['price_time'],
            'decision_available_at':max(generated,decision).isoformat(),
            'status':'TEMPORALLY_VALID_OBSERVATION_ONLY','entry_authorized':False,
            'remaining_gates':['accepted native/U signal','first eligible execution price','FX','fees','board lot','tradability','account risk limits']}
