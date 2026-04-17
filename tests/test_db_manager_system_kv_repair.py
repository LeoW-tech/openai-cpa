import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class SystemKvRepairScriptTests(unittest.TestCase):
    def test_repair_rebuilds_clean_system_kv_and_preserves_main_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source_db = base / "data.db"
            repaired_db = base / "data.repaired.db"

            with sqlite3.connect(source_db) as conn:
                conn.executescript(
                    """
                    CREATE TABLE accounts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE,
                        password TEXT,
                        token_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE local_mailboxes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE,
                        password TEXT,
                        client_id TEXT,
                        refresh_token TEXT,
                        status INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        fission_count INTEGER DEFAULT 0,
                        retry_master INTEGER DEFAULT 0
                    );
                    CREATE TABLE system_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO accounts (email, password, token_data) VALUES (?, ?, ?)",
                    ("demo@example.com", "pw", "{\"email\":\"demo@example.com\"}"),
                )
                conn.execute(
                    "INSERT INTO local_mailboxes (email, password, client_id, refresh_token, status) VALUES (?, ?, ?, ?, ?)",
                    ("mail@example.com", "pw", "cid", "rt", 2),
                )
                conn.execute(
                    "INSERT INTO system_kv (key, value) VALUES (?, ?)",
                    ("sms_reuse_data", "{\"entries\":[{\"activation_id\":\"broken\"}]}"),
                )
                conn.commit()

            result = subprocess.run(
                [
                    "python",
                    "/Users/meilinwang/Projects/openai-cpa-Public/scripts/repair_system_kv_db.py",
                    "--source-db",
                    str(source_db),
                    "--output-db",
                    str(repaired_db),
                    "--skip-lock-check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr or result.stdout)
            self.assertIn("成功迁移 accounts: 1", result.stdout)
            self.assertIn("成功迁移 local_mailboxes: 1", result.stdout)
            self.assertIn("system_kv 已重建为空", result.stdout)

            with sqlite3.connect(repaired_db) as conn:
                account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
                mailbox_count = conn.execute("SELECT COUNT(*) FROM local_mailboxes").fetchone()[0]
                system_kv_count = conn.execute("SELECT COUNT(*) FROM system_kv").fetchone()[0]
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

            self.assertEqual(1, account_count)
            self.assertEqual(1, mailbox_count)
            self.assertEqual(0, system_kv_count)
            self.assertEqual("ok", integrity)


if __name__ == "__main__":
    unittest.main()
