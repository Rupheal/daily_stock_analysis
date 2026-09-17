import unittest
from scripts.run032_native_recovery4 import validated_rows

class Tests(unittest.TestCase):
 def fixture(self):return {'data':{'hk00501':{'qfqday':[[f'2026-08-{i:02}',1,1.5,2,1,100] for i in range(1,22)]+[['2026-08-22',1,1.5,2,1,100]]}}}
 def test_future_partial_bar_excluded(self):
  rows=validated_rows(self.fixture(),'00501','2026-08-21',{'high':2,'low':1,'close':1.5,'volume':100});self.assertEqual(len(rows),21);self.assertEqual(rows[-1]['date'],'2026-08-21')
 def test_official_conflict_fails(self):
  with self.assertRaisesRegex(ValueError,'OFFICIAL'):validated_rows(self.fixture(),'00501','2026-08-21',{'high':2,'low':1,'close':1.5,'volume':101})
 def test_history_geometry_and_length_enforced(self):
  d=self.fixture();d['data']['hk00501']['qfqday'][0][3]=0
  with self.assertRaisesRegex(ValueError,'GEOMETRY'):validated_rows(d,'00501','2026-08-21',{})
  with self.assertRaisesRegex(ValueError,'HISTORY'):validated_rows(self.fixture(),'00501','2026-08-20',{})
