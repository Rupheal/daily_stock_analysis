import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from o_provider_completion import inspect_completion


def test_stream_exhausted_in_reasoning_is_not_an_answer():
    rows=[{'choices':[{'index':0,'delta':{'reasoning_content':'synthetic reasoning'},'finish_reason':None}]},
          {'choices':[{'index':0,'delta':{},'finish_reason':'length'}]}]
    raw='\n\n'.join('data: '+json.dumps(x) for x in rows)+'\n\ndata: [DONE]\n'
    out=inspect_completion(raw)
    assert out['status']=='BLOCK' and out['content_chars']==0
    assert 'PROVIDER_OUTPUT_TRUNCATED' in out['blockers']


def test_partial_json_even_with_content_is_rejected():
    out=inspect_completion(json.dumps({'choices':[{'message':{'content':'{"score":'},'finish_reason':'length'}]}))
    assert out['status']=='BLOCK'


def test_normal_answer_can_proceed_to_semantic_review():
    out=inspect_completion(json.dumps({'choices':[{'message':{'content':'{"score":50}'},'finish_reason':'stop'}]}))
    assert out['status']=='PASS' and out['model_requests']==0
