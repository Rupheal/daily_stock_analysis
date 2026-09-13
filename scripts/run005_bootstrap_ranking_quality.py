"""Deterministic bootstrap uncertainty for Run005 ranking-quality metrics."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

SEED_TAG = "TRIDENT-RUN005-V4-BOOTSTRAP-V1"


def rank_average(values):
    indexed = sorted(enumerate(values), key=lambda x: (x[1], x[0]))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j): ranks[indexed[k][0]] = avg
        i = j
    return ranks


def pearson(a,b):
    if len(a) != len(b) or len(a) < 2: return None
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    da=[x-ma for x in a]; db=[x-mb for x in b]
    den=math.sqrt(sum(x*x for x in da)*sum(x*x for x in db))
    return None if den == 0 else sum(x*y for x,y in zip(da,db))/den


def spearman(rows):
    return pearson(rank_average([r['score'] for r in rows]), rank_average([r['forward_return_pct'] for r in rows]))


def pairwise(rows):
    correct=comp=0
    for i in range(len(rows)):
        for j in range(i+1,len(rows)):
            ds=rows[i]['score']-rows[j]['score']; dr=rows[i]['forward_return_pct']-rows[j]['forward_return_pct']
            if ds == 0 or dr == 0: continue
            comp += 1
            if ds*dr > 0: correct += 1
    return correct/comp if comp else None


def top_lift(rows):
    if not rows: return None
    k=min(10,max(1,math.ceil(len(rows)*0.10)))
    mean=sum(r['forward_return_pct'] for r in rows)/len(rows)
    top=sorted(rows,key=lambda r:(-r['score'],r['code']))[:k]
    return sum(r['forward_return_pct'] for r in top)/len(top)-mean


def quantile(vals,q):
    if not vals: return None
    x=sorted(vals)
    pos=(len(x)-1)*q
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:return x[lo]
    return x[lo]*(hi-pos)+x[hi]*(pos-lo)


def ci(vals):
    vals=[v for v in vals if v is not None and math.isfinite(v)]
    return {'valid_reps':len(vals),'p2_5':quantile(vals,0.025),'p50':quantile(vals,0.5),'p97_5':quantile(vals,0.975)}


def execute(args):
    src=json.loads(Path(args.input).read_text())
    anchor=src['anchor_id']
    out={'schema_version':1,'anchor_id':anchor,'bootstrap_reps':args.reps,'seed_tag':SEED_TAG,'horizons':{}}
    for h,payload in sorted(src['horizon_results'].items(), key=lambda x:int(x[0])):
        rows=[r for r in payload['rows'] if r.get('status')=='VALID_COMPARABLE' and r.get('score') is not None and r.get('forward_return_pct') is not None]
        seed=int(hashlib.sha256(f'{anchor}|{h}|{SEED_TAG}'.encode()).hexdigest()[:16],16)
        rng=random.Random(seed)
        sp=[]; pw=[]; tl=[]
        for _ in range(args.reps):
            sample=[rows[rng.randrange(len(rows))] for _ in range(len(rows))] if rows else []
            sp.append(spearman(sample)); pw.append(pairwise(sample)); tl.append(top_lift(sample))
        point={'spearman':spearman(rows),'pairwise_accuracy':pairwise(rows),'top_k_lift_pct':top_lift(rows)}
        out['horizons'][h]={'n':len(rows),'seed':seed,'point':point,'ci95':{'spearman':ci(sp),'pairwise_accuracy':ci(pw),'top_k_lift_pct':ci(tl)}}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print('RUN005_V4_BOOTSTRAP_OK',json.dumps({h:{'n':v['n'],'spearman_ci':v['ci95']['spearman']} for h,v in out['horizons'].items()}))
    return out


def parser():
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True); p.add_argument('--reps',type=int,default=2000); return p

if __name__=='__main__': execute(parser().parse_args())
