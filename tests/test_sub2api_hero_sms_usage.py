import importlib
import json
import sys
import time
import types
import unittest
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(
    get=None,
    post=None,
    patch=None,
    delete=None,
    put=None,
    Session=object,
)
sys.modules.setdefault(
    "curl_cffi",
    types.SimpleNamespace(requests=fake_requests_module, CurlMime=object),
)
sys.modules.setdefault(
    "utils.email_providers.mail_service",
    types.SimpleNamespace(
        clear_sticky_domain=lambda: None,
        mask_email=lambda value, force_mask=False: value,
        get_last_email=lambda: "demo@example.com",
    ),
)
sys.modules.setdefault(
    "utils.register",
    types.SimpleNamespace(
        run=lambda *args, **kwargs: (None, None),
        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
    ),
)
sys.modules.setdefault(
    "utils.proxy_manager",
    types.SimpleNamespace(
        smart_switch_node=lambda *args, **kwargs: True,
        reload_proxy_config=lambda *args, **kwargs: None,
    ),
)
sys.modules.setdefault(
    "utils.integrations.sub2api_client",
    types.SimpleNamespace(Sub2APIClient=object),
)
sys.modules.setdefault(
    "utils.integrations.tg_notifier",
    types.SimpleNamespace(send_tg_msg_sync=lambda *args, **kwargs: None),
)


class Sub2ApiHeroSmsUsageTests(unittest.TestCase):
    def _reload_core_engine(self):
        import utils.core_engine as core_engine

        return importlib.reload(core_engine)

    def _reload_hero_sms(self, saved_state=None):
        import utils.integrations.hero_sms as hero_sms

        with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=saved_state):
            with patch.object(hero_sms.db_manager, "set_sys_kv"):
                return importlib.reload(hero_sms)

    def test_handle_registration_result_records_local_save_status(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), "Password123!")

        with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True):
            with patch.object(core_engine, "send_tg_msg_sync"):
                with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                    run_ctx = {}
                    status = core_engine.handle_registration_result(result, cpa_upload=False, run_ctx=run_ctx)

        self.assertEqual("success", status)
        self.assertIs(True, run_ctx["local_account_saved"])

    def test_handle_registration_result_marks_local_save_failure(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), "Password123!")

        with patch.object(core_engine.db_manager, "save_account_to_db", return_value=False):
            with patch.object(core_engine, "send_tg_msg_sync"):
                with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                    run_ctx = {}
                    status = core_engine.handle_registration_result(result, cpa_upload=False, run_ctx=run_ctx)

        self.assertEqual("success", status)
        self.assertIs(False, run_ctx["local_account_saved"])

    def test_sub2api_usage_confirmation_only_runs_after_full_business_success(self):
        core_engine = self._reload_core_engine()

        scenarios = [
            ("failed", True, True, False),
            ("success", False, True, False),
            ("success", True, False, False),
            ("success", True, True, True),
        ]

        for status, local_saved, sub2api_ok, should_confirm in scenarios:
            with self.subTest(status=status, local_saved=local_saved, sub2api_ok=sub2api_ok):
                run_ctx = {"local_account_saved": local_saved, "hero_sms_pending_usage": {"activation_id": "reuse-1"}}
                with patch.object(core_engine.hero_sms, "confirm_pending_hero_sms_usage") as confirm_usage:
                    core_engine.confirm_sub2api_hero_sms_usage(
                        status=status,
                        run_ctx=run_ctx,
                        sub2api_ok=sub2api_ok,
                    )

                    if should_confirm:
                        confirm_usage.assert_called_once_with(run_ctx)
                    else:
                        confirm_usage.assert_not_called()

    def test_deferred_confirmation_persists_reuse_state_for_next_selection(self):
        fake_db = {}
        hero_sms = self._reload_hero_sms(saved_state=None)
        base_ts = time.time()

        def fake_set_sys_kv(key, value):
            fake_db[key] = json.loads(json.dumps(value))

        def fake_get_sys_kv(key, default=None):
            return fake_db.get(key, default)

        with patch.object(hero_sms.db_manager, "set_sys_kv", side_effect=fake_set_sys_kv):
            with patch.object(hero_sms.db_manager, "get_sys_kv", side_effect=fake_get_sys_kv):
                with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_MAX_USES", 3, create=True):
                    with patch.object(hero_sms.time, "time", return_value=base_ts):
                        hero_sms._hero_sms_reuse_clear()
                        hero_sms._hero_sms_reuse_set("reuse-1", "+66964536019", "dr", 52)

                    run_ctx = {}
                    hero_sms._hero_sms_record_pending_usage(
                        run_ctx,
                        activation_id="reuse-1",
                        phone="+66964536019",
                        service="dr",
                        country=52,
                    )

                    with patch.object(hero_sms.time, "time", return_value=base_ts + 5):
                        self.assertTrue(hero_sms.confirm_pending_hero_sms_usage(run_ctx))

                    with hero_sms._HERO_SMS_REUSE_LOCK:
                        hero_sms._HERO_SMS_REUSE_STATE["entries"] = []
                        hero_sms._HERO_SMS_REUSE_STATE["updated_at"] = 0.0

                    with patch.object(hero_sms.time, "time", return_value=base_ts + 10):
                        self.assertEqual(
                            ("reuse-1", "+66964536019", 1),
                            hero_sms._hero_sms_reuse_get("dr", 52),
                        )


if __name__ == "__main__":
    unittest.main()
