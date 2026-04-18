import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from contextlib import contextmanager
from unittest.mock import patch

from utils import db_manager


class DbManagerPoolFissionTests(unittest.TestCase):
    @contextmanager
    def _temp_db_context(self):
        tmpdir = tempfile.TemporaryDirectory()
        stack = ExitStack()
        try:
            stack.enter_context(tmpdir)
            db_path = f"{tmpdir.name}/data.db"
            stack.enter_context(patch.object(db_manager, "DB_PATH", db_path))
            stack.enter_context(patch.object(db_manager, "DB_TYPE", "sqlite"))
            db_manager.init_db()
            yield db_path
        finally:
            stack.close()

    def test_get_mailbox_for_pool_fission_ignores_retry_master_when_fission_count_is_higher(self):
        with self._temp_db_context() as db_path:
            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO local_mailboxes (
                        email, password, client_id, refresh_token, status, fission_count, retry_master
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("normal-low@example.com", "pw", "cid1", "rt1", 0, 1, 0),
                        ("retry@example.com", "pw", "cid2", "rt2", 0, 5, 1),
                        ("normal-high@example.com", "pw", "cid3", "rt3", 0, 7, 0),
                    ],
                )
                conn.commit()

            row = db_manager.get_mailbox_for_pool_fission()

            self.assertIsNotNone(row)
            self.assertEqual("normal-low@example.com", row["email"])

    def test_get_mailbox_for_pool_fission_rotates_to_next_mailbox_on_second_pick(self):
        with self._temp_db_context() as db_path:
            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO local_mailboxes (
                        email, password, client_id, refresh_token, status, fission_count, retry_master
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("first@example.com", "pw", "cid1", "rt1", 0, 0, 0),
                        ("second@example.com", "pw", "cid2", "rt2", 0, 0, 0),
                    ],
                )
                conn.commit()

            first = db_manager.get_mailbox_for_pool_fission()
            second = db_manager.get_mailbox_for_pool_fission()

            self.assertEqual("first@example.com", first["email"])
            self.assertEqual("second@example.com", second["email"])

    def test_get_mailbox_for_pool_fission_excludes_current_mailbox_and_returns_next_candidate(self):
        with self._temp_db_context() as db_path:
            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO local_mailboxes (
                        email, password, client_id, refresh_token, status, fission_count, retry_master
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("retry@example.com", "pw", "cid1", "rt1", 0, 0, 1),
                        ("fallback@example.com", "pw", "cid2", "rt2", 0, 0, 0),
                    ],
                )
                conn.commit()

            row = db_manager.get_mailbox_for_pool_fission(exclude_emails=["retry@example.com"])

            self.assertIsNotNone(row)
            self.assertEqual("fallback@example.com", row["email"])

    def test_update_pool_fission_result_keeps_retry_master_record_but_not_selection_priority(self):
        with self._temp_db_context() as db_path:
            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO local_mailboxes (
                        email, password, client_id, refresh_token, status, fission_count, retry_master
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("retry@example.com", "pw", "cid", "rt", 0, 5, 0),
                        ("fresh@example.com", "pw", "cid2", "rt2", 0, 0, 0),
                    ],
                )
                conn.commit()

            db_manager.update_pool_fission_result("retry@example.com", is_blocked=True, is_raw=False)
            row = db_manager.get_mailbox_for_pool_fission()
            with sqlite3.connect(db_path) as conn:
                retry_flag = conn.execute(
                    "SELECT retry_master FROM local_mailboxes WHERE email = ?",
                    ("retry@example.com",),
                ).fetchone()[0]

            self.assertIsNotNone(row)
            self.assertEqual("fresh@example.com", row["email"])
            self.assertEqual(1, retry_flag)


if __name__ == "__main__":
    unittest.main()
