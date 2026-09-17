"""Actual wrapper hooks + unmodified frozen analyze_stock method; TEST_STUB I/O.

The native context builder/formatter and final count-annotation method execute.
Market/DB/provider/config/strategy peripheral services are synthetic boundaries;
this is NOT a live provider run or full strategy acceptance.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta, date
import ast, hashlib, inspect, json, logging, socket, sys, time
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from o_post_output_contract import *
from o_semantic_handoff_contract import build_news_handoff, canonical_hash, prove_prompt_consumption, CONTRACT_VERSION as HANDOFF_VERSION
from o_single_output_fact_check import check_saved_output
from test_native_handoff_integration import native_tools, NATIVE
from test_o_semantic_handoff_contract import pf, context
R=Path(__file__).resolve().parents[1]
PROBE=R/'scripts/run_hk_original_model_probe.py'


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args,**kwargs): raise AssertionError('NETWORK_FORBIDDEN_RUN025')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def compile_native_method(native_tools,monkeypatch):
    """Compile exact AST of frozen analyze_stock; no rewrite of method body."""
    path=NATIVE/'src/core/pipeline.py'
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==PINNED_SHA256['pipeline']
    tree=ast.parse(raw)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StockAnalysisPipeline')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='analyze_stock')
    from src.services.empty_news import news_evidence_present
    monkeypatch.setitem(sys.modules,'src.services.history_loader',SimpleNamespace(get_frozen_target_date=lambda:date(2026,1,5)))
    none=lambda *a,**k:None
    env={'__name__':'frozen_native_method_TEST_STUB','datetime':datetime,'timedelta':timedelta,'time':time,
         'logger':logging.getLogger('run025.native'),
         'get_market_for_stock':lambda code:'hk','normalize_stock_code':lambda code:code,
         'build_market_phase_context':lambda **kw:SimpleNamespace(to_dict=lambda:{'effective_daily_bar_date':'2026-01-05'}),
         'render_market_phase_summary':lambda x:'TEST_STUB completed session',
         'normalize_report_language':lambda x:'zh','get_effective_trading_date':lambda *a,**k:date(2026,1,5),
         'get_market_now':lambda market:datetime(2026,1,5,tzinfo=timezone.utc),
         'FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT':1,
         'record_llm_run_started':none,'record_llm_run':none,'record_history_run':none,
         'news_evidence_present':news_evidence_present,'normalize_chip_structure_availability':none,
         'fill_price_position_if_needed':none,'stabilize_decision_with_structure':none,
         'apply_phase_decision_guardrails':none,'apply_daily_market_context_guardrail':none}
    unit=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),fn],type_ignores=[])
    ast.fix_missing_locations(unit);exec(compile(unit,str(path),'exec'),env)
    return env['analyze_stock']


def harness(tmp_path,native_tools,monkeypatch,*,bad=None,search_hits=None,drop_prompt=False,handoff_enabled=True,interrupt_after_analyzer=False):
    native_method=compile_native_method(native_tools,monkeypatch)
    main=next(n for n in ast.parse(PROBE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    names={'load_news','analyze','format_prompt','pipeline_analyze'}
    funcs=[n for n in main.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(funcs)==4
    init=ast.parse('''def factory():
    news_handoff = None
    prompt_handoff_receipt = None
    output_semantic_receipt = None
    output_contract_receipt = None
    analyzer_snapshot = None
    final_capture_receipt = None
    captured_prompt = None
    returned_result = None
    observed_input = None
    loader_called = False
    validated = False
    validation_receipt = None
''').body[0]
    init.body+=funcs
    init.body+=ast.parse('''def state():
    return dict(contract=output_contract_receipt,final_capture=final_capture_receipt,analyzer_snapshot=analyzer_snapshot,prompt=captured_prompt,observed_input=observed_input,handoff=news_handoff)
return load_news, analyze, format_prompt, pipeline_analyze, state
''').body
    unit=ast.Module(body=[init],type_ignores=[]);ast.fix_missing_locations(unit)
    raw={'pattern_analysis':'低开','action':'watch','operation_advice':'观察','success':True,
         'news_result_count_known':True,'news_result_count':None,'current_price':None,
         'search_performed':False,'report_origin':'TEST_STUB'}
    if bad=='OPEN':raw['pattern_analysis']='高开'
    elif bad=='SEM-001':raw['dashboard']={'data_perspective':{'price_position':{'current_price':10.0}}}
    elif bad=='SEM-002':raw['checklist']='未见近3日利空公告'
    elif bad=='SEM-003':raw['sector_position']='恒生科技指数权重股之一'
    class Result:
        def __init__(self):self.__dict__.update(deepcopy(raw))
        def to_dict(self):return deepcopy(vars(self))
    result=Result();holder={};stub_calls=[]
    def provider_stub(instance,ctx,news_context=None,analysis_context_pack_summary=None,progress_callback=None,stream_progress_callback=None):
        stub_calls.append('TEST_STUB_NOT_HTTP')
        holder['formatter'](instance,ctx,ctx['stock_name'],news_context=news_context,analysis_context_pack_summary=analysis_context_pack_summary)
        return result
    source={'frozen_upstream':FROZEN_UPSTREAM,'pipeline_sha256':PINNED_SHA256['pipeline'],
            'observer_sha256':hashlib.sha256(PROBE.read_bytes()).hexdigest(),'pipeline_module_under_checkout':True}
    env=dict(inspect=inspect,json=json,datetime=datetime,timezone=timezone,
      ContractError=ContractError,NativeInputContractError=ValueError,
      validate_native_input=lambda p,c:{'validated':True},validate_native_history_database=lambda p,d:None,canonical_hash=canonical_hash,
      build_news_handoff=build_news_handoff,prove_prompt_consumption=prove_prompt_consumption,
      build_final_capture=build_final_capture,evaluate_post_output_contract=evaluate_post_output_contract,
      check_saved_output=check_saved_output,preflight=(pf() if handoff_enabled else dict(pf(),news_count=0,allowed_news_urls=[],company_news_evidence=[])),args=SimpleNamespace(news_handoff_v1=handoff_enabled),
      capture_source_proof=source,CONTRACT_VERSION=HANDOFF_VERSION,root=tmp_path,
      started='2026-01-05T09:01:00+00:00',target_session='2026-01-05',
      original_news_loader=lambda *a,**kw:None,original_analyze=provider_stub,
      original_pipeline_analyze=native_method,
      original_format_prompt=lambda instance,c,name,*a,**kw:native_tools.formatter._format_prompt(c,name,*a,**kw))
    if drop_prompt:env['original_format_prompt']=lambda *a,**kw:'TEST_STUB dropped supplied evidence'
    exec(compile(unit,'actual_run025_wrapper_hooks','exec'),env)
    load,analyze,fmt,pipeline,state=env['factory']();holder['formatter']=fmt
    cfg=SimpleNamespace(get_effective_news_window_days=lambda:3,enable_realtime_quote=False,agent_mode=False,
                        agent_skills=[],report_language='zh')
    none=lambda *a,**kw:None
    services=SimpleNamespace(get_stock_name=lambda *a,**kw:'合成标的',get_chip_distribution=none,
                             get_fundamental_context=lambda *a,**kw:{})
    database=SimpleNamespace(save_fundamental_snapshot=none,get_data_range=lambda *a,**kw:[],save_analysis_history=lambda **kw:None)
    instance=SimpleNamespace(config=cfg,query_source='TEST_STUB',analysis_skills=[],fetcher_manager=services,
      search_service=None,social_sentiment_service=None,db=database,save_context_snapshot=False,
      _coerce_daily_market_context_date=lambda d:date.fromisoformat(d),_load_daily_market_context=none,
      _emit_progress=none,_attach_belong_boards_to_fundamental_context=lambda c,f:f,
      _build_market_structure_context=none,
      _load_persisted_intelligence_context=lambda **kw:load(instance,**kw),
      _get_analysis_context_with_market_fallback=lambda *a,**kw:deepcopy(context()),
      _enhance_context=lambda c,*a,**kw:deepcopy(c),_attach_daily_market_context=none,
      _build_legacy_analysis_artifacts=lambda **kw:kw,
      _build_analysis_context_pack_outputs=lambda a,**kw:(native_tools.pack(a['enhanced_context'],a['news_context'])[1],{}),
      _refresh_decision_action_for_final_result=none,_append_daily_data_source=none,
      _build_context_snapshot=lambda **kw:{'origin':'TEST_STUB'},
      analyzer=SimpleNamespace(analyze=lambda *a,**kw:analyze(object(),*a,**kw)))
    if search_hits is not None:
        # Explicit synthetic search transport; real native count aggregation executes.
        instance.search_service=SimpleNamespace(is_available=True,
            search_comprehensive_intel=lambda **kw:{'test':SimpleNamespace(success=True,results=[{}]*search_hits)},
            format_intel_report=lambda *a:'')
        instance._build_query_context=lambda **kw:{}
        database.save_news_intel=none
    if interrupt_after_analyzer:
        def interrupted(*args,**kw):raise RuntimeError('TEST_STUB_INTERRUPTED_AFTER_ANALYZER')
        instance._append_daily_data_source=interrupted
    def run():return pipeline(instance,'HK01810',SimpleNamespace(value='simple'),'TEST_STUB_QUERY')
    return run,state,stub_calls


@pytest.mark.parametrize('hits,expected',[(None,'NOT_SEARCHED'),(0,'SEARCHED_ZERO'),(2,'SEARCHED_HITS')])
def test_actual_native_pipeline_finalizes_tristate_and_full_handoff(tmp_path,native_tools,monkeypatch,hits,expected):
    run,state,calls=harness(tmp_path,native_tools,monkeypatch,search_hits=hits)
    assert run() is not None
    st=state();out=st['contract']
    assert calls==['TEST_STUB_NOT_HTTP'] and out['semantic_contract_pass']
    assert out['deterministic_facts']['news_result_count']['final_search_state']==expected
    assert out['evidence_handoff']['supplied_evidence_count']==1
    assert st['analyzer_snapshot']['news_result_count'] is None
    final=json.loads((tmp_path/'pipeline-final-result.json').read_text())
    assert final['news_result_count']==hits
    assert json.loads((tmp_path/'original-result.json').read_text())['news_result_count'] is None
    assert out['capture_verified'] and st['handoff']['news_context'] in st['prompt']
    assert output_exit_code(out,request_count=1)==0 # simulated execution counter, not an HTTP
    assert not out['promotion_gate']['o_single_stock_formal_acceptance']


@pytest.mark.parametrize('bad',['OPEN','SEM-001','SEM-002','SEM-003'])
def test_actual_output_exit_rejects_single_fault_and_preserves_raw(tmp_path,native_tools,monkeypatch,bad):
    run,state,calls=harness(tmp_path,native_tools,monkeypatch,bad=bad,handoff_enabled=False)
    run();out=state()['contract'];assert out and output_exit_code(out,request_count=1)==1
    assert (tmp_path/'original-result.json').exists() and (tmp_path/'pipeline-final-result.json').exists()
    assert bad in out['promotion_gate']['blockers'] or bad=='OPEN'
    if bad.startswith('SEM'):
        assert not [f for f in out['semantic_audit']['findings'] if f['severity']=='BLOCK']
    assert calls==['TEST_STUB_NOT_HTTP']


def test_dropped_news_in_exact_prompt_never_gets_final_stage(tmp_path,native_tools,monkeypatch):
    run,state,_=harness(tmp_path,native_tools,monkeypatch,drop_prompt=True)
    with pytest.raises(ContractError,match='FINAL_PIPELINE_RESULT_NOT_PROVEN'):run()
    assert state()['final_capture'] is None and not (tmp_path/'pipeline-final-result.json').exists()
    assert output_exit_code(state()['contract'],request_count=1)==1


def test_actual_wrapper_exit_is_wired_to_contract_and_no_finally_backfill():
    tree=ast.parse(PROBE.read_text());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='output_exit_code']
    assert len(calls)==1
    final_writes=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='write_text' and any(isinstance(x,ast.Constant) and x.value=='pipeline-final-result.json' for x in ast.walk(n.func.value))]
    pipeline=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='pipeline_analyze')
    assert len(final_writes)==1 and final_writes[0] in list(ast.walk(pipeline))


def test_interrupted_pipeline_never_promotes_early_snapshot(tmp_path,native_tools,monkeypatch):
    run,state,calls=harness(tmp_path,native_tools,monkeypatch,interrupt_after_analyzer=True)
    with pytest.raises(ContractError,match='FINAL_PIPELINE_RESULT_NOT_PROVEN'):run()
    assert calls==['TEST_STUB_NOT_HTTP']
    assert (tmp_path/'original-result.json').exists()
    assert not (tmp_path/'pipeline-final-result.json').exists()
    assert state()['final_capture'] is None and output_exit_code(state()['contract'],request_count=1)==1


@pytest.mark.parametrize('tamper',['admitted_evidence_count','preflight_hash','native_context_hash','target_session','symbol'])
def test_handoff_manifest_cannot_drift_after_consumption(tmp_path,native_tools,monkeypatch,tamper):
    run,state,_=harness(tmp_path,native_tools,monkeypatch);run();st=state()
    final=json.loads((tmp_path/'pipeline-final-result.json').read_text())
    bad=deepcopy(st['handoff']);bad[tamper]='wrong'
    out=evaluate_post_output_contract(pf(),st['observed_input'],final,
        capture_receipt=st['final_capture'],analyzer_result=st['analyzer_snapshot'],
        expected_sources=st['final_capture']['source_proof'],prompt_text=st['prompt'],news_handoff=bad,required_handoff=True)
    assert out['evidence_handoff']['status']=='BLOCK'
    assert output_exit_code(out,request_count=1)==1
