import importlib.util
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('runner', ROOT/'scripts/run004_u45_safe_deepseek.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
FIXTURE = ROOT/'tests/fixtures/run004_u_failure_denominator.json'


def inputs(tmp_path):
    source = json.loads(FIXTURE.read_text())
    coverage = source['coverage']
    db = tmp_path/'native.db'
    con=sqlite3.connect(db)
    con.execute('CREATE TABLE stock_daily(code TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,ma5 REAL,ma10 REAL,ma20 REAL,volume_ratio REAL,data_source TEXT)')
    start=date(2026,8,10)
    for item in coverage:
        if item['status'] != 'passed_21_observed_daily_bars':
            continue
        code=item['code']; base=20 + int(code[-2:])/10
        for i in range(25):
            day=start+timedelta(days=i); close=base+i*.05
            con.execute('INSERT INTO stock_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (code,str(day),close-.1,close+.2,close-.2,close,100000+i*100,close-.1,close-.15,close-.2,1.0,'TencentFetcher'))
    for item in coverage:
        if item['status'] != 'passed_21_observed_daily_bars': continue
        code=item['code']; base=20+int(code[-2:])/10; close=base+2
        con.execute('INSERT INTO stock_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (code,'2026-09-11',close-.1,close+.2,close-.2,close,120000,close-.1,close-.15,close-.2,1.0,'TencentFetcher'))
    con.commit(); con.close()
    integrity=tmp_path/'integrity.json'; source['database_sha256']=runner.file_sha256(db); integrity.write_text(json.dumps(source))
    universe=tmp_path/'u.json'; universe.write_text(json.dumps({'universe_id':'U_POOL_2026-09-11_v3','member_count':45,'members':[{'code':r['code'][2:]} for r in coverage]}))
    return db, universe, integrity


def args(tmp_path, **kw):
    db, universe, integrity=inputs(tmp_path)
    d=dict(db=db,universe=universe,integrity=integrity,output=tmp_path/'out',target='2026-09-11',model='deepseek-v4-flash',
           run_id='TRI-DSA-DEV-20260913-004-U45',max_cny=5.0,max_requests=36,dry_run=False)
    d.update(kw); return SimpleNamespace(**d)


def fake_good(url,body,key):
    code=json.loads(body['messages'][1]['content'])['facts']['code']; score=50+(int(code[-2:])%20)
    return {'model':'deepseek-v4-flash','choices':[{'message':{'content':json.dumps({'score':score,'stance':'neutral','confidence':'low','reason_codes':['insufficient_edge']})}}],
            'usage':{'prompt_tokens':500,'completion_tokens':40,'total_tokens':540}}


def test_real_u45_status_fixture_keeps_45_denominator_and_9_b1_isolations(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','x'); result=runner.execute(args(tmp_path),post_json=fake_good)
    assert result['denominator']==45 and result['model_http_requests']==36
    assert result['ranked_count']==36 and result['isolated_count']==9
    assert all(x['reason'].startswith('b1_') for x in result['isolated'])
    assert result['ranking_envelope']['denominator']==45 and not result['ranking_envelope']['complete']


def test_invalid_provider_result_is_isolated_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','x'); count={'n':0}
    def bad(url,body,key):
        count['n']+=1
        if count['n']==1:
            return {'model':'deepseek-v4-flash','choices':[{'message':{'content':'{"score":101,"stance":"neutral","confidence":"low","reason_codes":["insufficient_edge"]}'}}], 'usage':{}}
        return fake_good(url,body,key)
    result=runner.execute(args(tmp_path),post_json=bad)
    assert count['n']==36 and result['model_http_requests']==36
    assert result['ranked_count']==35 and result['isolated_count']==10
    assert any('invalid_score' in x['reason'] for x in result['isolated'])


def test_serialized_package_contains_no_forbidden_content_keys(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','x'); runner.execute(args(tmp_path),post_json=fake_good)
    text=(tmp_path/'out/u45-safe-ranking.json').read_text()
    for token in ('"raw_response"','"provider_response"','"prompt"','"messages"','"reasoning"'):
        assert token not in text


def test_budget_cap_stops_calls_and_keeps_denominator(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','x'); count={'n':0}
    def counted(*a,**k): count['n']+=1; return fake_good(*a,**k)
    result=runner.execute(args(tmp_path,max_cny=.001),post_json=counted)
    assert count['n']==0 and result['denominator']==45 and result['ranked_count']==0 and result['isolated_count']==45
    assert sum(x['reason']=='budget_guard' for x in result['isolated'])==36


def test_ranking_is_deterministic_score_then_code_and_manifest_hashes(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','x')
    def same(url,body,key):
        return {'model':'deepseek-v4-flash','choices':[{'message':{'content':json.dumps({'score':60,'stance':'neutral','confidence':'low','reason_codes':['insufficient_edge']})}}], 'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
    result=runner.execute(args(tmp_path),post_json=same)
    assert [r['code'] for r in result['ranked']] == sorted(r['code'] for r in result['ranked'])
    manifest=json.loads((tmp_path/'out/manifest.json').read_text())
    assert manifest['privacy_contract']['raw_provider_response_saved'] is False
    assert len(result['hashes']['ranking_sha256'])==64
