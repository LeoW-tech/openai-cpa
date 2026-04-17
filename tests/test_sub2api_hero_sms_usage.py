import importlib
import json
import sys
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


if __name__ == "__main__":
    unittest.main()
