import importlib
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

                self.assertEqual(("reuse-1", "+6699990000", 0), hero_sms._hero_sms_reuse_get("dr", 52))

                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
                self.assertEqual(("reuse-1", "+6699990000", 2), hero_sms._hero_sms_reuse_get("dr", 52))

                hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
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


if __name__ == "__main__":
    unittest.main()
