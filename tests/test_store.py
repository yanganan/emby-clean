import tempfile
import unittest
from pathlib import Path

import app.store as store


class StoreTests(unittest.TestCase):
    def test_init_creates_durable_jobs_and_audit_tables(self):
        old_data_dir, old_db_path = store.DATA_DIR, store.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            store.DATA_DIR = Path(temp)
            store.DB_PATH = store.DATA_DIR / "test.db"
            store.init_db()
            with store.connect() as db:
                store.create_job(db, "job-1", "scan", {"mode": "smart"})
                store.update_job(db, "job-1", status="done", result_json="[]", result_count=0)
                audit_id = store.record_audit(db, "test", "unit", "job-1", {"ok": True})
                job = db.execute("select status,result_json from jobs where id='job-1'").fetchone()
                audit = db.execute("select id from audit_log where id=?", (audit_id,)).fetchone()
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["result_json"], "[]")
            self.assertIsNotNone(audit)
        store.DATA_DIR, store.DB_PATH = old_data_dir, old_db_path


if __name__ == "__main__":
    unittest.main()
