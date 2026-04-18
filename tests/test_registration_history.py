import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class RegistrationHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "history.db")

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

    def tearDown(self):
        self._db_type_patcher.stop()
        self._db_path_patcher.stop()
        self._tmpdir.cleanup()

    def test_init_db_creates_registration_history_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

        self.assertIn("registration_runs", tables)
        self.assertIn("registration_attempts", tables)
        self.assertIn("registration_attempt_events", tables)
        self.assertIn("ip_geo_cache", tables)

    def test_init_db_creates_phone_binding_columns(self):
        with sqlite3.connect(self.db_path) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(registration_attempts)").fetchall()
            }

        self.assertIn("phone_number_full", columns)
        self.assertIn("phone_number_e164", columns)
        self.assertIn("phone_country_calling_code", columns)
        self.assertIn("phone_country_iso", columns)
        self.assertIn("phone_country_name", columns)
        self.assertIn("phone_national_number", columns)
        self.assertIn("phone_activation_id", columns)
        self.assertIn("phone_bind_provider", columns)
        self.assertIn("phone_bind_attempted_flag", columns)
        self.assertIn("phone_bind_success_flag", columns)
        self.assertIn("phone_bind_failed_flag", columns)
        self.assertIn("phone_bind_failure_reason", columns)
        self.assertIn("phone_bind_stage", columns)

    def test_history_service_records_attempt_and_events(self):
        run_id = self.history.start_run(
            source_mode="sub2api",
            target_count=3,
            trigger_source="unit-test",
            worker_id="worker-A",
        )
        attempt_id = self.history.start_attempt(
            run_id=run_id,
            source_mode="sub2api",
            attempt_no=1,
            flow_type="register",
            email="demo@example.com",
            email_provider_type="mailbox",
            email_provider_detail="unit",
            proxy_name="JP-01",
            task_id="TASK-1",
            auto_capture_network=False,
        )

        self.history.record_attempt_event(
            attempt_id,
            event_type="email_acquired",
            phase="register",
            ok_flag=True,
            message="email ready",
        )
        self.history.patch_attempt(
            attempt_id,
            phone_gate_hit_flag=1,
            phone_otp_entered_flag=1,
            phone_otp_success_flag=1,
            local_save_ok=1,
            metrics_json={"email_otp_send_count": 2},
        )
        self.history.finish_attempt(
            attempt_id,
            final_status="success",
            success_flag=True,
            labels_json={"result": "ok"},
        )
        self.history.finish_run(run_id, notes={"finished": True})

        with sqlite3.connect(self.db_path) as conn:
            attempt_row = conn.execute(
                """
                SELECT run_id, email_full, email_local_part, email_domain, proxy_name,
                       final_status, success_flag, phone_gate_hit_flag,
                       phone_otp_entered_flag, phone_otp_success_flag, local_save_ok
                FROM registration_attempts
                WHERE id = ?
                """,
                (attempt_id,),
            ).fetchone()
            event_count = conn.execute(
                "SELECT COUNT(*) FROM registration_attempt_events WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()[0]
            run_row = conn.execute(
                "SELECT source_mode, worker_id, notes_json FROM registration_runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        self.assertEqual(run_id, attempt_row[0])
        self.assertEqual("demo@example.com", attempt_row[1])
        self.assertEqual("demo", attempt_row[2])
        self.assertEqual("example.com", attempt_row[3])
        self.assertEqual("JP-01", attempt_row[4])
        self.assertEqual("success", attempt_row[5])
        self.assertEqual(1, attempt_row[6])
        self.assertEqual(1, attempt_row[7])
        self.assertEqual(1, attempt_row[8])
        self.assertEqual(1, attempt_row[9])
        self.assertEqual(1, attempt_row[10])
        self.assertGreaterEqual(event_count, 2)
        self.assertEqual("sub2api", run_row[0])
        self.assertEqual("worker-A", run_row[1])
        self.assertEqual({"finished": True}, json.loads(run_row[2]))

    def test_backfill_accounts_creates_legacy_attempts(self):
        legacy_password = "unit-test-pass"
        token_data = json.dumps(
            {
                "email": "legacy@example.com",
                "refresh_token": "rt-demo",
                "sub2api_proxy_name": "US-W01",
            }
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO accounts (email, password, token_data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                ("legacy@example.com", legacy_password, token_data, "2026-04-17 10:11:12"),
            )
            conn.commit()

        inserted = self.history.backfill_accounts_history()
        self.assertEqual(1, inserted)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT legacy_backfill, email_full, email_domain, proxy_name, success_flag, final_status
                FROM registration_attempts
                WHERE linked_account_email = ?
                """,
                ("legacy@example.com",),
            ).fetchone()

        self.assertEqual(1, row[0])
        self.assertEqual("legacy@example.com", row[1])
        self.assertEqual("example.com", row[2])
        self.assertEqual("US-W01", row[3])
        self.assertEqual(1, row[4])
        self.assertEqual("success", row[5])

    def test_distribution_and_overview_use_attempts_as_denominator(self):
        run_id = self.history.start_run(source_mode="normal", target_count=0, trigger_source="unit-test")
        samples = [
            {
                "email": "a@example.com",
                "country": "United States",
                "status": "success",
                "success": True,
                "phone_entered": True,
                "duration": 1000,
            },
            {
                "email": "b@example.com",
                "country": "United States",
                "status": "failed",
                "success": False,
                "phone_entered": False,
                "duration": 3000,
            },
            {
                "email": "c@example.com",
                "country": "Japan",
                "status": "success",
                "success": True,
                "phone_entered": False,
                "duration": 2000,
            },
        ]
        for idx, sample in enumerate(samples, start=1):
            attempt_id = self.history.start_attempt(
                run_id=run_id,
                source_mode="normal",
                attempt_no=idx,
                flow_type="register",
                email=sample["email"],
                proxy_name=f"NODE-{idx}",
                auto_capture_network=False,
            )
            self.history.patch_attempt(
                attempt_id,
                geo_country_name=sample["country"],
                phone_otp_entered_flag=1 if sample["phone_entered"] else 0,
            )
            self.history.finish_attempt(
                attempt_id,
                final_status=sample["status"],
                success_flag=sample["success"],
                total_duration_ms=sample["duration"],
            )

        overview = self.history.get_overview({})
        distribution = self.history.get_distribution({"group_by": "geo_country_name"})

        self.assertEqual(3, overview["attempts"])
        self.assertEqual(2, overview["successes"])
        self.assertAlmostEqual(66.67, overview["success_rate"], places=2)
        self.assertEqual(1, overview["phone_otp_entered"])
        self.assertEqual(2000, overview["p50_duration_ms"])
        self.assertEqual(3000, overview["p90_duration_ms"])

        by_country = {row["group_value"]: row for row in distribution["rows"]}
        self.assertEqual(2, by_country["United States"]["attempts"])
        self.assertEqual(1, by_country["United States"]["successes"])
        self.assertAlmostEqual(50.0, by_country["United States"]["success_rate"], places=2)
        self.assertEqual(1, by_country["United States"]["phone_otp_entered"])
        self.assertEqual(1, by_country["Japan"]["attempts"])
        self.assertAlmostEqual(100.0, by_country["Japan"]["success_rate"], places=2)

    def test_record_cluster_account_result_creates_and_dedupes_history_attempt(self):
        payload = {
            "email": "cluster@example.com",
            "password": "unit-pass",
            "token_data": json.dumps(
                {
                    "email": "cluster@example.com",
                    "refresh_token": "rt-demo",
                    "sub2api_proxy_name": "🇯🇵 日本W03 | IEPL",
                }
            ),
            "created_at": "2026-04-18 08:30:00",
            "started_at": "2026-04-18 08:20:00",
            "finished_at": "2026-04-18 08:30:00",
            "proxy_name": "🇯🇵 日本W03 | IEPL",
            "exit_ip": "1.2.3.4",
            "geo_country_name": "Japan",
        }

        first_id = self.history.record_cluster_account_result(payload, node_name="NODE-2")
        second_id = self.history.record_cluster_account_result(payload, node_name="NODE-2")

        self.assertTrue(first_id)
        self.assertEqual(first_id, second_id)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT COUNT(*), source_mode, success_flag, final_status, proxy_name, geo_country_name,
                       external_attempt_id, source_node_name
                FROM registration_attempts
                WHERE linked_account_email = ?
                """,
                ("cluster@example.com",),
            ).fetchone()

        self.assertEqual(1, rows[0])
        self.assertEqual("cluster_import", rows[1])
        self.assertEqual(1, rows[2])
        self.assertEqual("success", rows[3])
        self.assertEqual("🇯🇵 日本W03 | IEPL", rows[4])
        self.assertEqual("Japan", rows[5])
        self.assertEqual("", rows[6])
        self.assertEqual("NODE-2", rows[7])

    def test_overview_and_distribution_include_phone_binding_metrics_and_history_gap(self):
        run_id = self.history.start_run(source_mode="normal", target_count=0, trigger_source="unit-test")
        attempt_id = self.history.start_attempt(
            run_id=run_id,
            source_mode="normal",
            attempt_no=1,
            flow_type="register",
            email="phone@example.com",
            proxy_name="HK-01",
            auto_capture_network=False,
        )
        self.history.patch_attempt(
            attempt_id,
            started_at="2026-04-18 10:00:00",
            finished_at="2026-04-18 10:05:00",
            phone_country_calling_code="+852",
            phone_country_name="Hong Kong",
            phone_bind_attempted_flag=1,
            phone_bind_success_flag=1,
            phone_bind_stage="otp_validated",
        )
        self.history.finish_attempt(
            attempt_id,
            final_status="success",
            success_flag=True,
            total_duration_ms=5000,
            finished_at="2026-04-18 10:05:00",
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO accounts (email, password, token_data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                ("gap@example.com", "unit-pass", json.dumps({"email": "gap@example.com"}), "2026-04-18 10:06:00"),
            )
            conn.commit()

        filters = {"started_from": "2026-04-18 00:00:00", "started_to": "2026-04-18 23:59:59"}
        overview = self.history.get_overview(filters)
        distribution = self.history.get_distribution({**filters, "group_by": "phone_country_calling_code"})

        self.assertEqual(1, overview["phone_bind_attempted"])
        self.assertEqual(1, overview["phone_bind_success"])
        self.assertEqual(0, overview["phone_bind_failed"])
        self.assertEqual(1, overview["history_coverage_gap"])

        by_code = {row["group_value"]: row for row in distribution["rows"]}
        self.assertEqual(1, by_code["+852"]["phone_bind_attempted"])
        self.assertEqual(1, by_code["+852"]["phone_bind_success"])
        self.assertEqual(0, by_code["+852"]["phone_bind_failed"])


if __name__ == "__main__":
    unittest.main()
