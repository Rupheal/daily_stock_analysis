"""Deterministic uncertainty analysis for the already-frozen Run005 ranking metrics.

This module does not define new predictive metrics. It adds fixed-seed percentile
bootstrap intervals to the predeclared Spearman, pairwise ordering accuracy, and
Top-K lift metrics already stored in a Run005 outcome package.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


def _rankdata(values):
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0.0] * len(values)
    p = 0
    while p < len(order):
        q = p + 1
        v = values[order[p]]
        while q < len(order) and values[order[q]] == v:
            q += 1
        avg = (p + 1 + q) / 2.0
        for j in range(p, q):
            ranks[order[j]] = avg
        p = q
    return ranks


def _corr(a, b):
    if len(a) < 2:
        return None
    ma = sum(a) / len(a); mb = sum(b) / len(b)
    da = [x-ma for x in a]; db = [x-mb for x in b]
    va = sum(x*x for x in da); vb = sum(x*x for x in db)
    if va <= 0 or vb <= 0:
        return None
    return sum(x*y for x,y in zip(da,db)) / math.sqrt(va*vb)


def spearman(rows):
    if len(rows) < 3:
        return None
    return _corr(_rankdata([r['score'] for r in rows]), _rankdata([r['forward_return_pct'] for r in rows]))


def pairwise(rows):
    good = total = 0
    for i in range(len(rows)):
        for j in range(i+1, len(rows)):
            ds = rows[i]['score'] - rows[j]['score']
            dr = rows[i]['forward_return_pct'] - rows[j]['forward_return_pct']
            if ds == 0 or dr == 0:
                continue
            total += 1
            good += int(ds * dr > 0)
    return good / total if total else None


def topk_lift(rows, k):
    if not rows:
        return None
    ranked = sorted(rows, key=lambda r: (-r['score'], r['code']))
    kk = min(k, len(ranked))
    top = sum(r['forward_return_pct'] for r in ranked[:kk]) / kk
    mean = sum(r['forward_return_pct'] for r in ranked) / len(ranked)
    return top - mean


def percentile(values, p):
    vals = sorted(v for v in values if v is not None and math.isfinite(v))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    x = (len(vals)-1) * p
    lo = int(math.floor(x)); hi = int(math.ceil(x))
    if lo == hi:
        return vals[lo]
    w = x-lo
    return vals[lo]*(1-w) + vals[hi]*w


def bootstrap(rows, k, *, seed, reps):
    rng = random.Random(seed)
    s=[]; p=[]; t=[]
    n=len(rows)
    for _ in range(reps):
        sample=[rows[rng.randrange(n)] for __ in range(n)]
        s.append(spearman(sample)); p.append(pairwise(sample)); t.append(topk_lift(sample,k))
    return {
        'seed': seed, 'reps': reps,
        'spearman_ci95': [percentile(s,0.025), percentile(s,0.975)],
        'pairwise_accuracy_ci95': [percentile(p,0.025), percentile(p,0.975)],
        'top_k_lift_pp_ci95': [percentile(t,0.025), percentile(t,0.975)],
    }


def execute(input_path, output_path, *, seed=20260914, reps=5000):
    x=json.loads(Path(input_path).read_text())
    out={
        'schema_version':1,
        'run_id':'TRI-DSA-VAL-20260913-005-V4-UNCERTAINTY-R1',
        'source_run_id':x['run_id'],
        'anchor_id':x['anchor_id'],
        'original_denominator':x['original_denominator'],
        'method':'fixed-seed nonparametric row bootstrap on predeclared metrics only',
        'accepted_progress_claim':'NONE_BY_THIS_ARTIFACT_ALONE',
        'horizons':{},
    }
    for h in sorted(x['horizon_results'], key=int):
        v=x['horizon_results'][h]
        rows=[r for r in v['rows'] if r.get('status')=='VALID_COMPARABLE']
        m=v['metrics']; k=int(m['top_k'])
        point={
            'n':len(rows),
            'dsa_spearman':spearman(rows),
            'dsa_pairwise_accuracy':pairwise(rows),
            'top_k':k,
            'top_k_lift_pp':topk_lift(rows,k),
        }
        # Assert the independently recomputed point estimates match the frozen package.
        checks=[
            (point['dsa_spearman'],m['dsa_spearman']),
            (point['dsa_pairwise_accuracy'],m['dsa_pairwise']['accuracy']),
            (point['top_k_lift_pp'],m['top_k_lift_vs_comparable_mean_pct']),
        ]
        for a,b in checks:
            if a is None or abs(a-b) > 1e-9:
                raise ValueError(f'point_estimate_mismatch_h{h}')
        out['horizons'][h]={'point':point,'bootstrap':bootstrap(rows,k,seed=seed+int(h),reps=reps)}
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(out,indent=2,sort_keys=True))
    return out


def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True)
    p.add_argument('--seed',type=int,default=20260914); p.add_argument('--reps',type=int,default=5000)
    a=p.parse_args(); r=execute(a.input,a.output,seed=a.seed,reps=a.reps)
    print('RUN005_V4_UNCERTAINTY_OK',json.dumps({h:r['horizons'][h] for h in r['horizons']},separators=(',',':')))

if __name__=='__main__': main()
