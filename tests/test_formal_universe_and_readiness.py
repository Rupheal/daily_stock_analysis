import json,unittest,copy
from pathlib import Path
from scripts.join_dual_formal_readiness import assemble
from scripts.o_native_input_contract import validate_native_input,NativeInputContractError,CALIBRATION_RUN_ID,LATEST_SESSION_MAX_RELATIVE_DEVIATION,UNIT_SEMANTICS
class Tests(unittest.TestCase):
 def test_non_xiaomi_requires_matching_symbol(self):
  p={'passed':True,'symbol':'HK00700','target':'2026-09-16','today':{'date':'2026-09-16','open':1,'high':2,'low':1,'close':2,'volume':100},'price_reconciliation':{'volume':{'calibration_run_id':CALIBRATION_RUN_ID,'latest_session_max_relative_deviation':LATEST_SESSION_MAX_RELATIVE_DEVIATION,'unit_semantics':UNIT_SEMANTICS}}}
  ctx={'today':p['today'],'code':'HK00700'};self.assertTrue(validate_native_input(p,ctx)['validated'])
  for v in ('HK01810',''):
   ctx['code']=v
   with self.assertRaises(NativeInputContractError):validate_native_input(p,ctx)
 def test_denominator_kept_and_old_prices_blocked(self):
  u={'member_count':45,'members':[{'code':str(i).zfill(5),'channels':['SSE'],'identity_verified':True} for i in range(45)]};o={'member_count':2,'members':u['members'][:2],'full_union_verified':True,'effective_session':'2026-09-17'}
  data={'target_session':'2026-09-15','members':[{'code':'00000','price_ready':True}]};r=assemble(o,u,{},data,{},'2026-09-16');self.assertEqual(r['O']['denominator'],2);self.assertEqual(len(r['U']['members']),45);self.assertEqual(r['U']['price_data_ready'],0);self.assertEqual(r['qualified_signals'],0)
 def test_parse_success_is_not_formal_news(self):
  u={'member_count':45,'members':[{'code':str(i).zfill(5),'channels':['SSE']} for i in range(45)]};o={'member_count':1,'members':u['members'][:1],'full_union_verified':True,'effective_session':'2026-09-17'}
  r=assemble(o,u,{}, {},{'rows':[{'code':'00000','retrieval_ready':True,'relevance_ready':True}]},'2026-09-16');self.assertTrue(r['U']['members'][0]['news_retrieval_ready']);self.assertFalse(r['U']['members'][0]['formal_news_ready'])
if __name__=='__main__':unittest.main()
