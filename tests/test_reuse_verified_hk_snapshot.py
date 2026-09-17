import json,tempfile,unittest,hashlib
from pathlib import Path
from scripts.reuse_verified_hk_snapshot import reuse

class Tests(unittest.TestCase):
 def test_changed_bytes_and_stale_session_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'MANIFEST.json').write_text(json.dumps({'official_session':'2026-09-17','files':{'O_UNIVERSE.json':'a'*64}}))
   with self.assertRaisesRegex(ValueError,'STALE'):reuse(p,'2026-09-16',p/'out')
   (p/'O_UNIVERSE.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'HASH'):reuse(p,'2026-09-17',p/'out')
