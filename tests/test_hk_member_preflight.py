import sys,json,hashlib,copy
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from prepare_hk_member_acceptance import reviewed_events

def inputs():
    raw=(ROOT/'docs/runtime/RUN032_PRIMARY_EVIDENCE.json').read_bytes();return json.loads(raw),json.loads((ROOT/'docs/runtime/RUN032_PRIMARY_REVIEW.json').read_text()),hashlib.sha256(raw).hexdigest()

def test_both_symbols_date_precision_and_no_foreign_reuse():
    e,r,h=inputs()
    for code in ['00700','01024']:
        out=reviewed_events(code,'2026-09-16',e,r,h,'2026-09-17T05:00:00+00:00')
        assert len(out)==1 and out[0]['publication_precision']=='date_only' and out[0]['event_id'].startswith(code)
    with pytest.raises(ValueError,match='NO_REVIEWED'):reviewed_events('01810','2026-09-16',e,r,h,'2026-09-17T05:00:00+00:00')

def test_hash_future_and_staleness_rejected():
    e,r,h=inputs()
    with pytest.raises(ValueError,match='HASH'):reviewed_events('00700','2026-09-16',e,r,'0'*64,'2026-09-17T05:00:00+00:00')
    with pytest.raises(ValueError,match='FUTURE'):reviewed_events('00700','2026-09-16',e,r,h,'2026-09-17T03:00:00+00:00')
    with pytest.raises(ValueError,match='NO_RECENT'):reviewed_events('00700','2026-09-16',e,r,h,'2026-09-20T05:00:00+00:00')
