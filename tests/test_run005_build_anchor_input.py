import hashlib
import json
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path

from scripts.run005_build_anchor_input import execute, parse_sse_notice


def qpage(rows):
    text = "<pre>PRV.CLO./\n"
    for code, name, close in rows:
        text += f" {int(code):5d} {name:<16} HKD {close-1:.2f} {close+0.1:.2f} {close+0.5:.2f} 1,000\n"
        text += f"                               {close:.2f} {close-0.1:.2f} {close-0.5:.2f} 100,000\n"
    text += "SALES RECORD\n</pre>"
    return text.encode()


def sh(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_fixture(tmp_path):
    anchors = {
        "schema_version": 1, "run_id": "TRI-DSA-VAL-TEST", "model_config_id": "RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1",
        "history_requirement": 21,
        "anchors": [{
            "anchor_id": "A1", "notice_date": "2025-01-03", "decision_at": "2025-01-06T09:00:00+08:00",
            "source_url": "https://example.invalid/notice", "expected_additions_count": 2, "expected_additions": ["00100", "02475"]
        }]
    }
    ap=tmp_path/'anchors.json'; ap.write_text(json.dumps(anchors))
    source=tmp_path/'source'; raw=source/'raw'; qdir=raw/'hkex'; qdir.mkdir(parents=True)
    notice=b'''<html><table><tr><th>code</th><th>english</th><th>chinese</th><th>direction</th></tr>
    <tr><td>00100</td><td>MINIMAX-W</td><td>x</td><td>\xe8\xb0\x83\xe5\x85\xa5</td></tr>
    <tr><td>02475</td><td>LUXSHARE ICT</td><td>y</td><td>\xe8\xb0\x83\xe5\x85\xa5</td></tr></table></html>'''
    # Replace escaped UTF-8 bytes with real bytes for the Chinese direction.
    notice=notice.replace(b'\\xe8\\xb0\\x83\\xe5\\x85\\xa5', '调入'.encode())
    (raw/'sse-notice.html').write_bytes(notice)
    sessions=[]
    d=date(2024,12,6)
    for i in range(21):
        day=(d+timedelta(days=i)).isoformat()
        name='d'+day.replace('-','')[2:]+'e.htm'
        rows=[('00100','MINIMAX-W',100+i)]
        if i != 0: rows.append(('02475','LUXSHARE ICT',50+i))
        content=qpage(rows); p=qdir/name; p.write_bytes(content)
        sessions.append({"date":day,"url":"https://example.invalid/"+name,"file":name,"sha256":sh(p),"bytes":len(content)})
    fetch={"anchor_id":"A1","decision_at":"2025-01-06T09:00:00+08:00","notice_sha256":sh(raw/'sse-notice.html'),"selected_sessions":sessions,"outcome_data_fetched":False}
    (source/'source-fetch-receipt.json').write_text(json.dumps(fetch))
    cfg={"config_id":"RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1","frozen_before_prediction":True}
    cp=tmp_path/'config.json'; cp.write_text(json.dumps(cfg))
    return ap,source,cp


def test_notice_parser_exact_set(tmp_path):
    ap,source,cp=make_fixture(tmp_path)
    members=parse_sse_notice(source/'raw'/'sse-notice.html',["00100","02475"])
    assert [m['code'] for m in members]==["00100","02475"]


def test_build_preserves_original_denominator_and_isolates_incomplete_history(tmp_path):
    ap,source,cp=make_fixture(tmp_path)
    out=tmp_path/'out'
    args=Namespace(anchors=str(ap),anchor_id='A1',source_dir=str(source),config=str(cp),output=str(out))
    package=execute(args)
    assert package['original_denominator']==2
    assert package['eligible_count']==1
    assert package['isolated_count']==1
    coverage=json.loads((out/'coverage.json').read_text())
    assert coverage['eligible_codes']==['00100']
    assert coverage['isolated'][0]['code']=='02475'
    assert coverage['isolated'][0]['reason']=='INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS'
    features=json.loads((out/'pit-features.json').read_text())
    assert len(features['features'])==1 and features['features'][0]['code']=='00100'
    receipt=json.loads((out/'pit-manifest-receipt.json').read_text())
    assert receipt['pit_input_admissible'] is True and receipt['prediction_generated'] is False
