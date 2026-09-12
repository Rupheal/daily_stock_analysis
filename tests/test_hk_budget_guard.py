import json
from pathlib import Path
import tempfile
import unittest
import httpx
from scripts.hk_budget_guard import ResearchBudget, decode_usage


class BudgetGuardTest(unittest.TestCase):
    def request(self, **changes):
        body={'model':'test-model','messages':[{'role':'user','content':'evidence'}],'max_tokens':8192}
        body.update(changes)
        return httpx.Request('POST','https://model.example/chat/completions',json=body)

    def guard(self, root, limit='8', carry='0'):
        return ResearchBudget(Path(root)/'ledger.json',limit=limit,carry_upper=carry,
                              max_requests=2,model='test-model',host='model.example')

    def test_reservation_precedes_send_and_restart_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root)
            n=guard.admit(self.request(),True)
            stored=json.loads(guard.path.read_text())
            self.assertEqual(n,1)
            self.assertEqual(stored['requests'][0]['status'],'reserved_before_send')
            with self.assertRaises(FileExistsError): self.guard(root)
            self.assertNotIn('messages',str(stored))

    def test_budget_and_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root,carry='7.70')
            with self.assertRaises(RuntimeError): guard.admit(self.request(),True)
            self.assertEqual(guard.state['requests'],[])
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root)
            for request in [self.request(max_tokens=0),self.request(model='other'),self.request(messages=[{'content':[{'type':'image'}]}])]:
                with self.assertRaises(RuntimeError): guard.admit(request,True)
            with self.assertRaises(RuntimeError): guard.admit(self.request(),False)

    def test_failed_call_keeps_reservation_and_success_counts_reasoning_once(self):
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root)
            first=guard.admit(self.request(),True)
            guard.settle(first,None,'http_error')
            self.assertEqual(guard.state['requests'][0]['reserved_cny'],guard.state['requests'][0]['charge_upper_cny'])
            second=guard.admit(self.request(),True)
            usage={'prompt_tokens':1000,'completion_tokens':2000,'completion_tokens_details':{'reasoning_tokens':1500}}
            guard.settle(second,usage,'response_received')
            self.assertEqual(guard.state['requests'][1]['usage_peak_estimate_cny'],'0.018')
            with self.assertRaises(RuntimeError): guard.admit(self.request(),True)

    def test_native_stream_usage_can_be_observed_without_rewriting(self):
        raw='data: {"choices":[]}\n\ndata: {"usage":{"prompt_tokens":5,"completion_tokens":8}}\n\ndata: [DONE]\n'
        self.assertEqual(decode_usage(raw),{'prompt_tokens':5,'completion_tokens':8})
        self.assertIsNone(decode_usage('data: [DONE]'))
