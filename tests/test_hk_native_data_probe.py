import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("probe", Path(__file__).parents[1] / "scripts/run_hk_native_data_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class CoverageTest(unittest.TestCase):
    def test_missing_stale_and_invalid_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actual.db"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE stock_daily(code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)")
            db.executemany("INSERT INTO stock_daily VALUES(?,?,?,?,?,?,?)", [
                ("current", "2026-09-11", 10, 12, 9, 11, 100),
                ("stale", "2026-09-10", 10, 12, 9, 11, 100),
                ("invalid", "2026-09-11", 10, 8, 9, 11, 100),
            ])
            db.commit()
            db.close()
            result = probe.audit_database(path, ["current", "stale", "invalid", "missing"], "2026-09-11")
            self.assertEqual(len(result), 4)
            self.assertEqual([r["status"] for r in result], ["current_valid_bar", "invalid_or_stale", "invalid_or_stale", "missing"])
            self.assertEqual(len(probe.audit_database(Path(directory) / "absent.db", ["A", "B"], "2026-09-11")), 2)
