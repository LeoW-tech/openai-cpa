import importlib
import json
import sys
import time
import types
import unittest
from unittest.mock import ANY
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(get=None, post=None, Session=object, Response=object)
sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module, CurlMime=object)


class HeroSmsReusePoolTests(unittest.TestCase):
    def _reload_hero_sms(self, saved_state=None):
        import utils.integrations.hero_sms as hero_sms

        with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=saved_state):
            with patch.object(hero_sms.db_manager, "set_sys_kv"):
                return importlib.reload(hero_sms)

    def test_legacy_reuse_state_is_migrated_to_pool_on_import(self):
        legacy_state = {
            "activation_id": "legacy-1",
            "phone": "+1234567890",
            "service": "dr",
            "country": 52,
            "uses": 1,
            "updated_at": 1_700_000_000.0,
        }

        hero_sms = self._reload_hero_sms(saved_state=legacy_state)

        snapshot = hero_sms.get_hero_sms_reuse_pool_snapshot()
        self.assertEqual(1, len(snapshot["entries"]))
        self.assertEqual("legacy-1", snapshot["entries"][0]["activation_id"])
        self.assertEqual(1, snapshot["entries"][0]["confirmed_uses"])

    def test_reuse_entry_remains_available_until_confirmed_uses_reaches_limit(self):
        hero_sms = self._reload_hero_sms(saved_state=None)

        with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_MAX_USES", 3, create=True):
            with patch.object(hero_sms.db_manager, "set_sys_kv"):
                hero_sms._hero_sms_reuse_clear()
                hero_sms._hero_sms_reuse_set("reuse-1", "+6699990000", "dr", 52)

                with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=hero_sms.get_hero_sms_reuse_pool_snapshot()):
                    self.assertEqual(("reuse-1", "+6699990000", 0), hero_sms._hero_sms_reuse_get("dr", 52))

                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
                with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=hero_sms.get_hero_sms_reuse_pool_snapshot()):
                    self.assertEqual(("reuse-1", "+6699990000", 2), hero_sms._hero_sms_reuse_get("dr", 52))

                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
                with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=hero_sms.get_hero_sms_reuse_pool_snapshot()):
                    self.assertEqual(("", "", 0), hero_sms._hero_sms_reuse_get("dr", 52))

    def test_expired_entry_is_not_reusable(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        base_ts = time.time()

        with patch.object(hero_sms.db_manager, "set_sys_kv"):
            with patch.object(hero_sms.time, "time", return_value=base_ts):
                hero_sms._hero_sms_reuse_clear()
                hero_sms._hero_sms_reuse_set("reuse-expired", "+6688880000", "dr", 52)

            with patch.object(
                hero_sms.time,
                "time",
                return_value=base_ts + hero_sms._hero_sms_reuse_ttl_sec() + 1,
            ):
                with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=hero_sms.get_hero_sms_reuse_pool_snapshot()):
                    self.assertEqual(("", "", 0), hero_sms._hero_sms_reuse_get("dr", 52))

    def test_reuse_get_prefers_fresh_database_state_over_stale_memory(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        base_ts = time.time()
        db_state = {
            "entries": [
                {
                    "activation_id": "reuse-db",
                    "phone": "+66964536019",
                    "service": "dr",
                    "country": 52,
                    "confirmed_uses": 2,
                    "updated_at": base_ts + 30,
                }
            ],
            "updated_at": base_ts + 30,
        }

        with patch.object(hero_sms.db_manager, "set_sys_kv"):
            with patch.object(hero_sms.time, "time", return_value=base_ts):
                hero_sms._hero_sms_reuse_clear()

            with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=db_state):
                with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_MAX_USES", 3, create=True):
                    with patch.object(hero_sms.time, "time", return_value=base_ts + 60):
                        self.assertEqual(
                            ("reuse-db", "+66964536019", 2),
                            hero_sms._hero_sms_reuse_get("dr", 52),
                        )

    def test_reuse_get_logs_why_no_candidate_was_selected(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        base_ts = time.time()
        saved_state = {
            "entries": [
                {
                    "activation_id": "reuse-limit",
                    "phone": "+6699990000",
                    "service": "dr",
                    "country": 52,
                    "confirmed_uses": 3,
                    "updated_at": base_ts,
                },
                {
                    "activation_id": "reuse-country",
                    "phone": "+447000000000",
                    "service": "dr",
                    "country": 16,
                    "confirmed_uses": 1,
                    "updated_at": base_ts,
                },
            ],
            "updated_at": base_ts,
        }

        with patch.object(hero_sms.db_manager, "set_sys_kv"):
            with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=saved_state):
                hero_sms._load_reuse_state_from_db()
                with patch.object(hero_sms.time, "time", return_value=base_ts + 1):
                    with patch.object(hero_sms, "_info") as info_log:
                        self.assertEqual(("", "", 0), hero_sms._hero_sms_reuse_get("dr", 52))

        info_log.assert_any_call(ANY)
        logged_messages = [call.args[0] for call in info_log.call_args_list]
        self.assertTrue(
            any("当前无可复用号码" in message and "service=dr" in message and "country=52" in message for message in logged_messages)
        )

    def test_reuse_get_raises_when_system_kv_storage_is_corrupted(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        storage_error = hero_sms.db_manager.SystemKvStorageError("system_kv 损坏")

        with patch.object(hero_sms.db_manager, "get_sys_kv", side_effect=storage_error):
            with self.assertRaises(hero_sms.db_manager.SystemKvStorageError):
                hero_sms._hero_sms_reuse_get("dr", 52)

    def test_sync_reuse_to_db_logs_storage_failure_without_mutating_memory_state(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        storage_error = hero_sms.db_manager.SystemKvStorageError("system_kv 损坏")
        base_ts = time.time()

        with patch.object(hero_sms.time, "time", return_value=base_ts):
            with patch.object(hero_sms.db_manager, "set_sys_kv", side_effect=storage_error):
                with patch.object(hero_sms, "_warn") as warn_log:
                    hero_sms._hero_sms_reuse_set("reuse-write-fail", "+6691110000", "dr", 52)

        snapshot = hero_sms.get_hero_sms_reuse_pool_snapshot()
        self.assertEqual(1, len(snapshot["entries"]))
        self.assertEqual("reuse-write-fail", snapshot["entries"][0]["activation_id"])
        self.assertEqual(0, snapshot["entries"][0]["confirmed_uses"])
        warn_log.assert_any_call(ANY)
        self.assertTrue(any("复用池写回失败" in call.args[0] for call in warn_log.call_args_list))

    def test_verify_phone_stops_new_purchase_when_reuse_storage_is_corrupted(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()
        storage_error = hero_sms.db_manager.SystemKvStorageError("system_kv 损坏")

        with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
            with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                    with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                        with patch.object(hero_sms, "_hero_sms_reuse_get", side_effect=storage_error):
                            with patch.object(hero_sms, "_hero_sms_get_number") as get_number:
                                with patch.object(hero_sms, "_warn") as warn_log:
                                    ok, reason = hero_sms._try_verify_phone_via_hero_sms(
                                        session,
                                        proxies=None,
                                        run_ctx={},
                                    )

        self.assertFalse(ok)
        self.assertEqual("复用池存储异常，已停止新购号码，请先修复数据库", reason)
        get_number.assert_not_called()
        self.assertTrue(any("system_kv" in call.args[0] for call in warn_log.call_args_list))

    def test_verify_phone_ignores_reuse_storage_failure_when_reuse_is_disabled(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()

        with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_PHONE", False, create=True):
            with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                    with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                        with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                            with patch.object(hero_sms, "_hero_sms_reuse_get") as reuse_get:
                                with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                    with patch.object(hero_sms, "_hero_sms_get_number", return_value=("", "", "NO_NUMBERS")) as get_number:
                                        with patch.object(hero_sms, "_sleep_interruptible", return_value=False):
                                            ok, reason = hero_sms._try_verify_phone_via_hero_sms(
                                                session,
                                                proxies=None,
                                                run_ctx={},
                                            )

        self.assertFalse(ok)
        self.assertEqual("取号失败: NO_NUMBERS", reason)
        reuse_get.assert_not_called()
        get_number.assert_called_once()


if __name__ == "__main__":
    unittest.main()
