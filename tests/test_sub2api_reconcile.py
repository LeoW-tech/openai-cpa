import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


class _FakeClient:
    def __init__(self, cloud_items=None, repair_results=None):
        self._cloud_items = list(cloud_items or [])
        self._repair_results = list(repair_results or [])
        self.repair_payloads = []

    def get_all_accounts(self, page_size=100):
        return True, list(self._cloud_items)

    def add_account(self, token_data):
        self.repair_payloads.append(dict(token_data))
        if self._repair_results:
            return self._repair_results.pop(0)
        return True, "Sub2API account import succeeded"


class Sub2APIReconcileTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "reconcile.db")

        import utils.db_manager as db_manager
        self.db_manager = importlib.reload(db_manager)
        self._db_path_patcher = patch.object(self.db_manager, "DB_PATH", self.db_path)
        self._db_type_patcher = patch.object(self.db_manager, "DB_TYPE", "sqlite")
        self._db_path_patcher.start()
        self._db_type_patcher.start()
        self.db_manager.init_db()

        import utils.registration_history as registration_history
        self.history = importlib.reload(registration_history)
        self.history.db_manager.DB_PATH = self.db_path
        self.history.db_manager.DB_TYPE = "sqlite"

        sys.modules.pop("utils.sub2api_reconcile", None)
        import utils.sub2api_reconcile as sub2api_reconcile
        self.reconcile = importlib.reload(sub2api_reconcile)
        self.reconcile.db_manager.DB_PATH = self.db_path
        self.reconcile.db_manager.DB_TYPE = "sqlite"

    def tearDown(self):
        self._db_type_patcher.stop()
        self._db_path_patcher.stop()
        self._tmpdir.cleanup()
        sys.modules.pop("utils.sub2api_reconcile", None)

    def _insert_success_attempt(self, email, account_id, created_at):
        token_data = json.dumps(
            {
                "email": email,
                "account_id": account_id,
                "access_token": f"access-{account_id}",
                "refresh_token": f"refresh-{account_id}",
                "sub2api_proxy_name": "JP-01",
            }
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO accounts (email, password, token_data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, "Password123!", token_data, created_at),
            )
            conn.commit()

        attempt_id = self.history.start_attempt(
            source_mode="sub2api",
            flow_type="register",
            email=email,
            linked_account_email=email,
            linked_account_created_at=created_at,
            proxy_name="JP-01",
            auto_capture_network=False,
        )
        self.history.finish_attempt(
            attempt_id,
            final_status="success",
            success_flag=True,
            finished_at=created_at,
            linked_account_email=email,
            linked_account_created_at=created_at,
            proxy_name="JP-01",
        )
        return attempt_id

    def test_list_missing_sub2api_accounts_finds_only_cloud_gaps(self):
        self._insert_success_attempt("kept@example.com", "acct-kept", "2026-04-25 10:00:00")
        self._insert_success_attempt("missing@example.com", "acct-missing", "2026-04-25 10:05:00")
        client = _FakeClient(
            cloud_items=[
                {
                    "id": 1,
                    "name": "kept@example.com",
                    "credentials": {"chatgpt_account_id": "acct-kept"},
                    "status": "active",
                }
            ]
        )

        audit = self.reconcile.list_missing_sub2api_accounts(client)

        self.assertEqual(2, audit["local_success_total"])
        self.assertEqual(1, audit["cloud_total"])
        self.assertEqual(1, audit["missing_total"])
        self.assertEqual("missing@example.com", audit["rows"][0]["email"])
        self.assertEqual("acct-missing", audit["rows"][0]["chatgpt_account_id"])

    def test_repair_missing_sub2api_accounts_only_pushes_missing_rows(self):
        kept_attempt_id = self._insert_success_attempt("kept@example.com", "acct-kept", "2026-04-25 10:00:00")
        missing_attempt_id = self._insert_success_attempt("missing@example.com", "acct-missing", "2026-04-25 10:05:00")
        client = _FakeClient(
            cloud_items=[
                {
                    "id": 1,
                    "name": "kept@example.com",
                    "credentials": {"chatgpt_account_id": "acct-kept"},
                    "status": "active",
                }
            ],
            repair_results=[(True, "Sub2API account import succeeded")],
        )

        result = self.reconcile.repair_missing_sub2api_accounts(client)

        self.assertEqual(1, result["missing_total"])
        self.assertEqual(1, result["repaired_total"])
        self.assertEqual(0, result["failed_total"])
        self.assertEqual(["missing@example.com"], [item["email"] for item in result["results"]])
        self.assertEqual(1, len(client.repair_payloads))
        self.assertEqual("missing@example.com", client.repair_payloads[0]["email"])

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, sub2api_push_ok, failure_message
                FROM registration_attempts
                WHERE id IN (?, ?)
                ORDER BY id ASC
                """,
                (kept_attempt_id, missing_attempt_id),
            ).fetchall()
            events = conn.execute(
                """
                SELECT event_type, message
                FROM registration_attempt_events
                WHERE attempt_id = ?
                ORDER BY seq_no ASC
                """,
                (missing_attempt_id,),
            ).fetchall()

        self.assertEqual(0, rows[0][1])
        self.assertEqual(1, rows[1][1])
        self.assertEqual("", rows[1][2] or "")
        self.assertIn(("sub2api_push_started", "repair attempt 1/2"), events)
        self.assertIn(("sub2api_push_succeeded", "Sub2API account import succeeded"), events)


if __name__ == "__main__":
    unittest.main()
