import tempfile,sqlite3,json,unittest
from pathlib import Path
from scripts.run_hk_native_data_probe import export_market_history

class Tests(unittest.TestCase):
 def test_only_requested_historical_market_columns_are_saved(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'x.db';out=Path(td)/'history.json';c=sqlite3.connect(db)
   c.execute('CREATE TABLE stock_daily(code TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,private_payload TEXT)')
   c.executemany('INSERT INTO stock_daily VALUES(?,?,?,?,?,?,?,?)',[('HK00501','2026-09-16',1,2,1,2,100,'must-not-export'),('HK00501','2026-09-17',1,2,1,2,100,'future'),('HK00638','2026-09-16',1,2,1,2,100,'other-code')]);c.execute('CREATE TABLE llm_response(secret TEXT)');c.execute("INSERT INTO llm_response VALUES('must-not-export')");c.commit();c.close()
   export_market_history(db,['hk00501'],'2026-09-16',out);s=out.read_text();d=json.loads(s)
   self.assertEqual(len(d['histories']['hk00501']),1);self.assertNotIn('must-not-export',s);self.assertNotIn('2026-09-17',s);self.assertNotIn('HK00638',s)
