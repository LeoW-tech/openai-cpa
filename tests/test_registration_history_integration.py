import importlib
import json
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch


class RegistrationHistoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(
            get=None,
            post=None,
            patch=None,
            delete=None,
            put=None,
            Session=object,
        )
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
                    "curl_cffi": types.SimpleNamespace(requests=fake_requests_module, CurlMime=object),
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        clear_sticky_domain=lambda: None,
                        mask_email=lambda value, force_mask=False: value,
                        get_last_email=lambda: "demo@example.com",
                    ),
                    "utils.register": types.SimpleNamespace(
                        run=lambda *args, **kwargs: (None, None),
                        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
                        submit_callback_url=lambda *args, **kwargs: json.dumps({"email": "demo@example.com"}),
                    ),
                    "utils.proxy_manager": types.SimpleNamespace(
                        smart_switch_node=lambda *args, **kwargs: True,
                        reload_proxy_config=lambda *args, **kwargs: None,
                        get_last_success_node_name=lambda *args, **kwargs: None,
                    ),
                    "utils.integrations.sub2api_client": types.SimpleNamespace(Sub2APIClient=object),
                    "utils.integrations.tg_notifier": types.SimpleNamespace(
                        send_tg_msg_sync=lambda *args, **kwargs: None,
                        send_tg_msg_async=lambda *args, **kwargs: None,
                    ),
                    "utils.email_providers.gmail_oauth_handler": types.SimpleNamespace(GmailOAuthHandler=object),
                    "cloudflare": types.SimpleNamespace(Cloudflare=object),
                },
            )
        )
        sys.modules.pop("utils.core_engine", None)
        sys.modules.pop("routers.api_routes", None)

    def tearDown(self):
        sys.modules.pop("utils.core_engine", None)
        sys.modules.pop("routers.api_routes", None)
        if hasattr(builtins, "_openai_cpa_real_print"):
            builtins.print = builtins._openai_cpa_real_print
        self._module_stack.close()

    def _reload_core_engine(self):
        import utils.core_engine as core_engine

        return importlib.reload(core_engine)

    def _reload_api_routes(self):
        import routers.api_routes as api_routes

        return importlib.reload(api_routes)

    def test_handle_registration_result_finishes_history_attempt(self):
        core_engine = self._reload_core_engine()
        demo_password = "unit-test-pass"
        result = (json.dumps({"email": "demo@example.com"}), demo_password)

        with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True):
            with patch.object(core_engine, "send_tg_msg_sync"):
                with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                    with patch.object(core_engine.registration_history, "finish_attempt") as finish_attempt:
                        run_ctx = {
                            "analytics_attempt_id": 77,
                            "analytics_started_monotonic": 100.0,
                            "phone_gate_hit": True,
                            "phone_otp_entered": True,
                            "phone_otp_success": True,
                            "sub2api_proxy_name": "JP-01",
                        }
                        with patch.object(core_engine.time, "time", return_value=104.25):
                            status = core_engine.handle_registration_result(
                                result,
                                cpa_upload=False,
                                run_ctx=run_ctx,
                            )

        self.assertEqual("success", status)
        finish_attempt.assert_called_once()
        kwargs = finish_attempt.call_args.kwargs
        self.assertEqual(77, finish_attempt.call_args.args[0])
        self.assertEqual("success", kwargs["final_status"])
        self.assertTrue(kwargs["success_flag"])
        self.assertEqual(4250, kwargs["total_duration_ms"])
        self.assertEqual("JP-01", kwargs["proxy_name"])
        self.assertEqual("demo@example.com", kwargs["linked_account_email"])
        self.assertEqual(1, kwargs["phone_gate_hit_flag"])
        self.assertEqual(1, kwargs["phone_otp_entered_flag"])
        self.assertEqual(1, kwargs["phone_otp_success_flag"])

    def test_ext_submit_result_records_history_for_legacy_payload(self):
        api_routes = self._reload_api_routes()
        demo_password = "unit-test-pass"

        with patch.object(api_routes.db_manager, "save_account_to_db", return_value=True):
            with patch.object(
                api_routes.registration_history,
                "record_extension_result",
                return_value=123,
            ) as record_extension_result:
                result = api_routes.ext_submit_result(
                    api_routes.ExtResultReq(
                        status="success",
                        task_id="TASK-1",
                        email="demo@example.com",
                        password=demo_password,
                        token_data=json.dumps({"email": "demo@example.com"}),
                    ),
                    token="demo-token",
                )
        self.assertEqual("success", result["status"])
        record_extension_result.assert_called_once()
        call_req = record_extension_result.call_args.args[0]
        self.assertEqual("TASK-1", call_req.task_id)
        self.assertEqual("demo@example.com", call_req.email)


if __name__ == "__main__":
    unittest.main()
