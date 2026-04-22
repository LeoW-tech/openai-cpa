import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


class DbManagerAccountExportRunIdTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "accounts.db")

        import utils.db_manager as db_manager

        self.db_manager = importlib.reload(db_manager)
        self._db_path_patcher = patch.object(self.db_manager, "DB_PATH", self.db_path)
        self._db_type_patcher = patch.object(self.db_manager, "DB_TYPE", "sqlite")
        self._db_path_patcher.start()
        self._db_type_patcher.start()
        self.db_manager.init_db()

    def tearDown(self):
        self._db_type_patcher.stop()
        self._db_path_patcher.stop()
        self._tmpdir.cleanup()

    def test_exported_accounts_include_stored_analytics_run_id_and_created_at(self):
        self.assertTrue(
            self.db_manager.save_account_to_db(
                "demo@example.com",
                "DemoPass123!",
                '{"email":"demo@example.com"}',
            )
        )
        self.assertTrue(self.db_manager.set_account_analytics_run_id("demo@example.com", 2468))

        rows = self.db_manager.get_all_accounts_with_token(limit=10)

        self.assertEqual(1, len(rows))
        self.assertEqual("demo@example.com", rows[0]["email"])
        self.assertEqual(2468, rows[0]["analytics_run_id"])
        self.assertTrue(rows[0]["created_at"])

    def test_repeated_save_preserves_created_at(self):
        self.assertTrue(
            self.db_manager.save_account_to_db(
                "stable@example.com",
                "DemoPass123!",
                '{"email":"stable@example.com"}',
            )
        )
        first = self.db_manager.get_all_accounts_with_token(limit=10)[0]["created_at"]

        self.assertTrue(
            self.db_manager.save_account_to_db(
                "stable@example.com",
                "DemoPass456!",
                '{"email":"stable@example.com","v":2}',
            )
        )
        second = self.db_manager.get_all_accounts_with_token(limit=10)[0]["created_at"]

        self.assertEqual(first, second)

    def test_zero_run_id_does_not_clear_existing_account_run_id(self):
        self.assertTrue(
            self.db_manager.save_account_to_db(
                "run@example.com",
                "DemoPass123!",
                '{"email":"run@example.com"}',
            )
        )
        self.assertTrue(self.db_manager.set_account_analytics_run_id("run@example.com", 2468))
        self.assertTrue(self.db_manager.set_account_analytics_run_id("run@example.com", 0))

        rows = self.db_manager.get_all_accounts_with_token(limit=10)

        self.assertEqual(2468, rows[0]["analytics_run_id"])


if __name__ == "__main__":
    unittest.main()
