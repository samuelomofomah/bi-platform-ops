"""End-to-end in mock mode: tasks -> SQLite -> the SQL views a dashboard would read."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from biops import tasks
from biops.config import Settings
from biops.store import Store


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Settings(mock=True, env="test", backup_dir=str(Path(self.tmp.name) / "backups"))
        self.store = Store(":memory:", "test")

    def test_daily_views_are_the_difference_between_snapshots(self):
        for day in (date(2026, 10, 1), date(2026, 10, 2)):
            self.assertTrue(tasks.run_collect(self.s, self.store, day))
        _, rows = self.store.query(
            "SELECT view_name, workbook, views_that_day FROM v_daily_views "
            "WHERE snapshot_date = '2026-10-02' ORDER BY views_that_day DESC")
        self.assertEqual(rows[0], ("Overview", "Seller Performance", 42))

    def test_collect_is_idempotent_for_the_same_day(self):
        for _ in range(2):
            tasks.run_collect(self.s, self.store, date(2026, 10, 1))
        _, rows = self.store.query("SELECT COUNT(*) FROM content_inventory")
        self.assertEqual(rows[0][0], 7)

    def test_health_failure_returns_false_and_is_recorded(self):
        with mock.patch.dict(os.environ, {"BIOPS_MOCK_FAIL": "1"}):
            self.assertFalse(tasks.run_health(self.s, self.store))
        _, rows = self.store.query("SELECT check_name FROM v_latest_health WHERE status = 'fail'")
        self.assertEqual(rows, [("project:Marketing Analytics@mstr-node-1",)])

    def test_backup_writes_files_and_logs_checksums(self):
        self.assertTrue(tasks.run_backup(self.s, self.store, date(2026, 10, 3)))
        _, rows = self.store.query("SELECT path, bytes, sha256 FROM job_log WHERE task = 'backup'")
        self.assertEqual(len(rows), 4)
        for path, size, digest in rows:
            self.assertTrue(Path(path).exists())
            self.assertGreater(size, 0)
            self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
