"""Offline entry tests with exact native context builder and formatter source.

Provider/model call is never invoked; the old prompt is reproduced byte-for-byte
from saved CHILD2 data as an additional local-only check.
"""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import sys,os,ast,inspect,json,hashlib
import pytest
from o_semantic_handoff_contract import *
from o_single_output_fact_check import check_saved_output
from native_source_loader import PureNativeLoader
from test_o_semantic_handoff_contract import pf,context,bundle
R=Path(__file__).resolve().parents[1]
NATIVE=Path(os.getenv('DSA_FROZEN_SOURCE_ROOT',str(R/'baseline/pinned/original')))
PROBE=next(p for p in (R/'scripts/run_hk_original_model_probe.py',R/'src/run_hk_original_model_probe.py') if p.exists())

@pytest.fixture(scope='module')
def native_tools():
 if not NATIVE.exists():pytest.skip('Pinned native source required for formatter integration')
 b=(NATIVE/'src/analyzer.py').read_bytes()
 assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()=='837070f2d7ce49a7b5a402a44eb096cdf0c65ac7'
 sys.path.insert(0,str(NATIVE))
 from src.services.analysis_context_builder import PipelineAnalysisArtifacts,AnalysisContextBuilder
 from src.analysis_context_pack_prompt import format_analysis_context_pack_prompt_section
 from src.services.empty_news import persisted_news_result_state,empty_news_disclosure
 l=PureNativeLoader(NATIVE);fmt=l.formatter()
 def pack(c,n):
  a=PipelineAnalysisArtifacts(code=c['code'],stock_name=c.get('stock_name','合成'),market='hk',phase=c.get('market_phase_context'),
    base_context=c,enhanced_context=c,realtime_quote=None,trend_result=c.get('trend_analysis'),chip_data=None,
    fundamental_context=c.get('fundamental_context'),news_context=n,news_result_count=None,metadata={})
  built=AnalysisContextBuilder.build(a)
  return built,format_analysis_context_pack_prompt_section(built,report_language='zh')
 return SimpleNamespace(loader=l,formatter=fmt,pack=pack,native_count=persisted_news_result_state,native_disclosure=empty_news_disclosure)

def test_native_tristate_contract_proves_prior_false_positive(native_tools):
 r={'news_result_count':None,'news_result_count_known':True,'news_evidence_present':False}
 assert native_tools.native_count(r)==(None,True)
 assert '未配置搜索渠道' in native_tools.native_disclosure(r)
 assert news_count_state(r)['state']=='NOT_SEARCHED'

def test_exact_native_pack_and_formatter_receive_evidence_once(native_tools):
 c=context();b=bundle(c=c);before=deepcopy(c)
 pack,s=native_tools.pack(c,b['news_context'])
 assert str(pack.blocks['news'].status.value)=='available' and 'news_context_missing' not in s
 prompt=native_tools.formatter._format_prompt(c,'合成',news_context=b['news_context'],analysis_context_pack_summary=s)
 assert prove_prompt_consumption(prompt,b)['native_prompt_evidence_consumed']
 assert b['admitted_event_ids'][0] in prompt and c==before
 assert '新闻: available' in prompt and '未搜索到该股票近期的相关新闻。' not in prompt

def test_late_analyzer_only_injection_is_rejected_due_to_stale_pack(native_tools):
 c=context();b=bundle(c=c);_,old=native_tools.pack(c,None)
 prompt=native_tools.formatter._format_prompt(c,'合成',news_context=b['news_context'],analysis_context_pack_summary=old)
 with pytest.raises(ContractError,match='FALSE_NO_NEWS_BRANCH'):prove_prompt_consumption(prompt,b)

def build_probe_harness(tmp_path,native_tools,existing_news=None,enabled=True,bad_result=False):
 source=PROBE.read_text();main=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='main')
 funcs=[n for n in main.body if isinstance(n,ast.FunctionDef) and n.name in ('load_news','analyze','format_prompt')]
 init=ast.parse('''def factory():
    news_handoff = None
    prompt_handoff_receipt = None
    output_semantic_receipt = None
    returned_result = None
    observed_input = None
    loader_called = False
    validated = False
    validation_receipt = None
''').body[0]
 init.body+=funcs
 init.body+=ast.parse('''def state():
    return dict(loader_called=loader_called,validated=validated,observed_input=observed_input,output_semantic_receipt=output_semantic_receipt,prompt_handoff_receipt=prompt_handoff_receipt)
return load_news, analyze, format_prompt, state
''').body
 module=ast.Module(body=[init],type_ignores=[]);ast.fix_missing_locations(module)
 holder={};raw={'pattern_analysis':'高开' if bad_result else '低开','news_result_count_known':True,'news_result_count':None,'action':'watch','search_performed':False,'current_price':None}
 class Result:
  def to_dict(self):return deepcopy(raw)
 result=Result()
 def original_analyze(self,ctx,news_context=None,analysis_context_pack_summary=None):
  holder['format'](self,ctx,ctx.get('stock_name','合成'),news_context=news_context,analysis_context_pack_summary=analysis_context_pack_summary)
  return result
 env=dict(inspect=inspect,json=json,datetime=datetime,timezone=timezone,ContractError=ContractError,
  NativeInputContractError=ValueError,validate_native_input=lambda p,c:{'validated':True},validate_native_history_database=lambda p,d:None,
  canonical_hash=canonical_hash,build_news_handoff=build_news_handoff,prove_prompt_consumption=prove_prompt_consumption,
  check_saved_output=check_saved_output,preflight=pf(),args=SimpleNamespace(news_handoff_v1=enabled),root=tmp_path,
  started='2026-01-05T09:01:00+00:00',target_session='2026-01-05',
  original_news_loader=lambda *a,**k:existing_news,original_analyze=original_analyze,
  original_format_prompt=lambda instance,c,name,*a,**kw:native_tools.formatter._format_prompt(c,name,*a,**kw))
 exec(compile(module,'actual_probe_nested_functions','exec'),env)
 load,analyze,fmt,state=env['factory']();holder['format']=fmt
 return load,analyze,state,result

def test_actual_probe_loader_to_pack_to_analyzer_to_prompt(tmp_path,native_tools):
 load,analyze,state,raw=build_probe_harness(tmp_path,native_tools)
 cfg=SimpleNamespace(config=SimpleNamespace(get_effective_news_window_days=lambda:3))
 news=load(cfg,code='HK01810',stock_name='合成',market='hk');c=context();_,pack=native_tools.pack(c,news)
 result=analyze(object(),c,news_context=news,analysis_context_pack_summary=pack)
 assert result is raw and state()['loader_called'] and state()['prompt_handoff_receipt']['native_prompt_evidence_consumed']
 assert state()['output_semantic_receipt']['semantic_verdict']!='NO_GO'
 assert json.loads((tmp_path/'original-result.json').read_text())['news_result_count'] is None
 assert json.loads((tmp_path/'original-input.json').read_text())['capture_stage']=='ANALYZER_ENTRY'

def test_actual_probe_rejects_dropped_news_before_provider(tmp_path,native_tools):
 load,analyze,state,_=build_probe_harness(tmp_path,native_tools)
 load(SimpleNamespace(config=SimpleNamespace(get_effective_news_window_days=lambda:3)),code='HK01810',stock_name='合成',market='hk')
 with pytest.raises(ContractError,match='ARGUMENT_DROPPED'):analyze(object(),context(),news_context=None)
 assert not state()['validated'] and not (tmp_path/'original-result.json').exists()

def test_actual_probe_rejects_uninvoked_loader(tmp_path,native_tools):
 _,analyze,_,_=build_probe_harness(tmp_path,native_tools)
 with pytest.raises(ContractError,match='LOADER_NOT_CONSUMED'):analyze(object(),context(),news_context=None)

def test_actual_probe_disabled_path_does_not_inject_news(tmp_path,native_tools):
 load,analyze,state,_=build_probe_harness(tmp_path,native_tools,enabled=False)
 assert load(object(),code='HK01810',stock_name='合成',market='hk') is None
 analyze(object(),context(),news_context=None)
 assert not state()['loader_called'] and state()['observed_input']['news_context'] is None

def test_actual_probe_keeps_raw_bad_report_but_fails_semantic(tmp_path,native_tools):
 load,analyze,state,raw=build_probe_harness(tmp_path,native_tools,enabled=False,bad_result=True)
 got=analyze(object(),context(),news_context=None)
 assert got is raw and json.loads((tmp_path/'original-result.json').read_text())['pattern_analysis']=='高开'
 assert state()['output_semantic_receipt']['semantic_verdict']=='NO_GO'

def test_actual_saved_child2_replay_no_original_mutation(native_tools):
 path=R/'private/child2'
 if not path.exists():pytest.skip('Private original not uploaded to public CI')
 files=['preflight.json','original-model/original-input.json','original-model/original-result.json','original-model/request-body.json','original-model/probe-summary.json']
 before={f:hashlib.sha256((path/f).read_bytes()).hexdigest() for f in files}
 p,i,res,req,run=[json.loads((path/f).read_text()) for f in files]
 c=i['context'];_,s=native_tools.pack(c,None)
 oldprompt=native_tools.formatter._format_prompt(c,c['stock_name'],news_context=None,analysis_context_pack_summary=s)
 assert oldprompt==next(m['content'] for m in req['messages'] if m['role']=='user')
 b=build_news_handoff(p,c,expected_preflight_hash=canonical_hash(p),decision_at=run['started_at'])
 _,s=native_tools.pack(c,b['news_context'])
 prompt=native_tools.formatter._format_prompt(c,c['stock_name'],news_context=b['news_context'],analysis_context_pack_summary=s)
 proof=prove_prompt_consumption(prompt,b);assert proof['native_prompt_evidence_consumed'] and b['admitted_evidence_count']==4
 r=check_saved_output(p,i,res);assert r['semantic_verdict']=='NO_GO'
 assert not [f for f in r['findings'] if f['code'].startswith('NEWS_COUNT_KNOWN')]
 assert not [f for f in r['findings'] if f['code']=='OPEN_GAP_STATED_NUMBER_MISMATCH']
 assert r['opening_facts_sidecar']['direction']=='DOWN'
 assert all(before[f]==hashlib.sha256((path/f).read_bytes()).hexdigest() for f in files)
