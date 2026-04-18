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

    def test_handle_registration_result_ensures_attempt_before_local_save(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), "unit-test-pass")
        calls = []

        def _ensure_attempt(run_ctx, **kwargs):
            calls.append(("ensure", kwargs["source_mode"], kwargs["proxy_name"]))
            run_ctx["analytics_attempt_id"] = 778
            return 778

        def _save_account(email, password, token_data):
            calls.append(("save", email))
            return True

        with patch.object(core_engine.registration_history, "ensure_attempt", side_effect=_ensure_attempt) as ensure_attempt:
            with patch.object(core_engine.registration_history, "finish_attempt") as finish_attempt:
                with patch.object(core_engine.db_manager, "save_account_to_db", side_effect=_save_account):
                    with patch.object(core_engine, "send_tg_msg_sync"):
                        with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                            status = core_engine.handle_registration_result(
                                result,
                                cpa_upload=False,
                                run_ctx={"sub2api_proxy_name": "JP-02"},
                            )

        self.assertEqual("success", status)
        self.assertEqual(2, ensure_attempt.call_count)
        self.assertEqual(("ensure", "normal", "JP-02"), calls[0])
        self.assertEqual(("save", "demo@example.com"), calls[1])
        self.assertEqual(778, finish_attempt.call_args.args[0])

    def test_ext_submit_result_records_history_for_legacy_payload(self):
        api_routes = self._reload_api_routes()
        demo_password = "unit-test-pass"
        calls = []

        def _record_extension(req, run_id=0):
            calls.append(("history", req.token_data))
            return 123

        def _save_account(email, password, token_data):
            calls.append(("save", token_data))
            return True

        with patch.object(api_routes.db_manager, "save_account_to_db", side_effect=_save_account):
            with patch.object(
                api_routes.registration_history,
                "record_extension_result",
                side_effect=_record_extension,
            ) as record_extension_result:
                with patch.object(api_routes.registration_history, "patch_attempt") as patch_attempt:
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
        patch_attempt.assert_called_once_with(123, local_save_ok=1, linked_account_created_at="")
        call_req = record_extension_result.call_args.args[0]
        self.assertEqual("TASK-1", call_req.task_id)
        self.assertEqual("demo@example.com", call_req.email)
        self.assertEqual(("history", json.dumps({"email": "demo@example.com"})), calls[0])
        self.assertEqual(("save", json.dumps({"email": "demo@example.com"})), calls[1])

    def test_ext_submit_result_records_history_before_local_save_after_callback_exchange(self):
        api_routes = self._reload_api_routes()
        demo_password = "unit-test-pass"
        calls = []

        def _record_extension(req, run_id=0):
            calls.append(("history", req.token_data))
            return 456

        def _save_account(email, password, token_data):
            calls.append(("save", token_data))
            return True

        with patch.object(api_routes.db_manager, "save_account_to_db", side_effect=_save_account):
            with patch.object(
                api_routes.registration_history,
                "record_extension_result",
                side_effect=_record_extension,
            ) as record_extension_result:
                with patch.object(api_routes.registration_history, "patch_attempt") as patch_attempt:
                    result = api_routes.ext_submit_result(
                        api_routes.ExtResultReq(
                            status="success",
                            task_id="TASK-2",
                            email="demo@example.com",
                            password=demo_password,
                            token_data="",
                            callback_url="https://example.com/callback",
                            expected_state="state-1",
                            code_verifier="verifier-1",
                        ),
                        token="demo-token",
                    )

        self.assertEqual("success", result["status"])
        record_extension_result.assert_called_once()
        patch_attempt.assert_called_once_with(456, local_save_ok=1, linked_account_created_at="")
        self.assertEqual(("history", json.dumps({"email": "demo@example.com"})), calls[0])
        self.assertEqual(("save", json.dumps({"email": "demo@example.com"})), calls[1])

    def test_cluster_upload_accounts_records_history_before_local_save(self):
        api_routes = self._reload_api_routes()
        payload = {
            "email": "cluster@example.com",
            "password": "unit-pass",
            "token_data": json.dumps({"email": "cluster@example.com"}),
            "started_at": "2026-04-18 08:20:00",
            "finished_at": "2026-04-18 08:30:00",
        }

        with patch.object(api_routes.db_manager, "save_account_to_db", return_value=True):
            with patch.object(
                api_routes.registration_history,
                "record_cluster_account_result",
                return_value=321,
            ) as record_cluster:
                result = api_routes.cluster_upload_accounts(
                    api_routes.ClusterUploadAccountsReq(
                        node_name="NODE-2",
                        secret="wenfxl666",
                        accounts=[payload],
                    )
                )

        self.assertEqual("success", result["status"])
        record_cluster.assert_called_once()
        self.assertEqual(payload, record_cluster.call_args.args[0])
        self.assertEqual("NODE-2", record_cluster.call_args.kwargs["node_name"])

    def test_coverage_audit_endpoint_returns_history_audit_rows(self):
        api_routes = self._reload_api_routes()
        fake_rows = {
            "accounts_total": 2,
            "missing_total": 1,
            "rows": [
                {
                    "email": "missing@example.com",
                    "created_at": "2026-04-18 10:00:00",
                    "match_status": "missing",
                }
            ],
        }

        with patch.object(api_routes.registration_history, "list_coverage_audit", return_value=fake_rows) as audit:
            result = api_routes.get_analytics_coverage_audit(
                started_from="2026-04-18 00:00:00",
                started_to="2026-04-18 23:59:59",
                source_mode=None,
                proxy_name=None,
                email_domain=None,
                token="demo-token",
            )
            if hasattr(result, "__await__"):
                import asyncio
                result = asyncio.run(result)

        self.assertEqual("success", result["status"])
        self.assertEqual(fake_rows, result["data"])
        audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
