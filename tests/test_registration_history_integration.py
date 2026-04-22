import importlib
import asyncio
import json
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch


class _FakeRouter:
    def __getattr__(self, name):
        def _decorator(*args, **kwargs):
            def _wrap(func):
                return func

            return _wrap

        return _decorator


class _FakeHTTPException(Exception):
    pass


class RegistrationHistoryIntegrationTests(unittest.TestCase):
    DEMO_PASSWORD = "__TEST_PASSWORD_PLACEHOLDER__"

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
                    "fastapi": types.SimpleNamespace(
                        APIRouter=lambda *args, **kwargs: _FakeRouter(),
                        Depends=lambda *args, **kwargs: None,
                        Header=lambda default=None, **kwargs: default,
                        Query=lambda default=None, **kwargs: default,
                        Request=object,
                        WebSocket=object,
                        HTTPException=_FakeHTTPException,
                    ),
                    "fastapi.responses": types.SimpleNamespace(
                        HTMLResponse=object,
                        StreamingResponse=object,
                    ),
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

    @staticmethod
    def _run_history_inline(label, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    def test_handle_registration_result_finishes_history_attempt(self):
        core_engine = self._reload_core_engine()
        demo_password = self.DEMO_PASSWORD
        result = (json.dumps({"email": "demo@example.com"}), demo_password)

        with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True):
            with patch.object(core_engine, "send_tg_msg_sync"):
                with patch.object(core_engine.cfg, "EMAIL_API_MODE", "local_microsoft"):
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

    def test_handle_registration_result_ensures_attempt_after_local_save(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), self.DEMO_PASSWORD)
        calls = []

        def _ensure_attempt(run_ctx, **kwargs):
            calls.append(("ensure", kwargs["source_mode"], kwargs["proxy_name"]))
            run_ctx["analytics_attempt_id"] = 778
            return 778

        def _save_account(email, password, token_data):
            calls.append(("save", email))
            return True

        with patch.object(core_engine, "_run_history_task", side_effect=self._run_history_inline):
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
        self.assertEqual(1, ensure_attempt.call_count)
        self.assertEqual(("save", "demo@example.com"), calls[0])
        self.assertEqual(("ensure", "normal", "JP-02"), calls[1])
        self.assertEqual(778, finish_attempt.call_args.args[0])

    def test_handle_registration_result_keeps_success_when_history_finalize_fails(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), self.DEMO_PASSWORD)

        with patch.object(core_engine, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True) as save_account:
                with patch.object(core_engine, "send_tg_msg_sync"):
                    with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                        with patch.object(core_engine.registration_history, "ensure_attempt", side_effect=RuntimeError("ensure-boom")):
                            status = core_engine.handle_registration_result(
                                result,
                                cpa_upload=False,
                                run_ctx={"sub2api_proxy_name": "JP-03"},
                            )

        self.assertEqual("success", status)
        save_account.assert_called_once()

    def test_handle_registration_result_snapshots_run_id_before_background_finalize(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), self.DEMO_PASSWORD)
        captured = {}

        def _run_history_after_run_id_changes(label, func, *args, **kwargs):
            core_engine.run_stats["analytics_run_id"] = 202
            return func(*args, **kwargs)

        def _ensure_attempt(run_ctx, **kwargs):
            captured["run_id"] = kwargs["run_id"]
            run_ctx["analytics_attempt_id"] = 909
            return 909

        core_engine.run_stats["analytics_run_id"] = 101
        with patch.object(core_engine, "_run_history_task", side_effect=_run_history_after_run_id_changes):
            with patch.object(core_engine.registration_history, "ensure_attempt", side_effect=_ensure_attempt):
                with patch.object(core_engine.registration_history, "finish_attempt"):
                    with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True):
                        with patch.object(core_engine, "send_tg_msg_sync"):
                            with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                                status = core_engine.handle_registration_result(
                                    result,
                                    cpa_upload=False,
                                    run_ctx={"sub2api_proxy_name": "JP-04"},
                                )

        self.assertEqual("success", status)
        self.assertEqual(101, captured["run_id"])

    def test_ext_submit_result_records_history_for_legacy_payload(self):
        api_routes = self._reload_api_routes()
        demo_password = self.DEMO_PASSWORD
        calls = []

        def _record_extension(req, run_id=0):
            calls.append(("history", req.token_data))
            return 123

        def _save_account(email, password, token_data):
            calls.append(("save", token_data))
            return True

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
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
        self.assertEqual(("save", json.dumps({"email": "demo@example.com"})), calls[0])
        self.assertEqual(("history", json.dumps({"email": "demo@example.com"})), calls[1])

    def test_ext_generate_task_includes_current_analytics_run_id(self):
        api_routes = self._reload_api_routes()
        api_routes.core_engine.run_stats["analytics_run_id"] = 4321

        with patch.dict(
            sys.modules,
            {
                "utils.email_providers.mail_service": types.SimpleNamespace(
                    mask_email=lambda value, force_mask=False: value,
                    get_email_and_token=lambda proxies=None: ("demo@example.com", "jwt-demo"),
                    clear_sticky_domain=lambda: None,
                ),
                "utils.register": types.SimpleNamespace(
                    _generate_password=lambda: "DemoPass123!",
                    generate_random_user_info=lambda: {"name": "Demo User", "birthdate": "1999-01-01"},
                    generate_oauth_url=lambda: types.SimpleNamespace(
                        auth_url="https://auth.example/start",
                        code_verifier="verifier-demo",
                        state="state-demo",
                    ),
                ),
            },
            clear=False,
        ):
            result = api_routes.ext_generate_task(token="demo-token")

        self.assertEqual("success", result["status"])
        self.assertEqual(4321, result["task_data"]["analytics_run_id"])

    def test_ext_submit_result_success_keeps_main_path_when_history_write_fails(self):
        api_routes = self._reload_api_routes()

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.db_manager, "save_account_to_db", return_value=True) as save_account:
                with patch.object(
                    api_routes.registration_history,
                    "record_extension_result",
                    side_effect=RuntimeError("history-boom"),
                ):
                    result = api_routes.ext_submit_result(
                        api_routes.ExtResultReq(
                            status="success",
                            task_id="TASK-3",
                            email="demo@example.com",
                            password=self.DEMO_PASSWORD,
                            token_data=json.dumps({"email": "demo@example.com"}),
                        ),
                        token="demo-token",
                    )

        self.assertEqual({"status": "success", "message": "战利品已入库"}, result)
        save_account.assert_called_once()

    def test_ext_submit_result_failure_keeps_main_path_when_history_write_fails(self):
        api_routes = self._reload_api_routes()

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(
                api_routes.registration_history,
                "record_extension_result",
                side_effect=RuntimeError("history-boom"),
            ):
                result = api_routes.ext_submit_result(
                    api_routes.ExtResultReq(
                        status="failed",
                        task_id="TASK-4",
                        email="demo@example.com",
                        password=self.DEMO_PASSWORD,
                        error_type="phone_verify",
                    ),
                    token="demo-token",
                )

        self.assertEqual({"status": "success", "message": "异常统计已录入看板"}, result)

    def test_ext_submit_result_uses_reported_run_id_instead_of_global_run_id(self):
        api_routes = self._reload_api_routes()
        observed = {}
        api_routes.core_engine.run_stats["analytics_run_id"] = 9999

        def _record_extension(req, run_id=0):
            observed["run_id"] = run_id
            return 123

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.db_manager, "save_account_to_db", return_value=True):
                with patch.object(api_routes.db_manager, "set_account_analytics_run_id") as set_run_id:
                    with patch.object(api_routes.registration_history, "record_extension_result", side_effect=_record_extension):
                        with patch.object(api_routes.registration_history, "patch_attempt"):
                            result = api_routes.ext_submit_result(
                                api_routes.ExtResultReq(
                                    status="success",
                                    task_id="TASK-RUN",
                                    analytics_run_id=1234,
                                    email="demo@example.com",
                                    password=self.DEMO_PASSWORD,
                                    token_data=json.dumps({"email": "demo@example.com"}),
                                ),
                                token="demo-token",
                            )

        self.assertEqual("success", result["status"])
        self.assertEqual(1234, observed["run_id"])
        set_run_id.assert_called_once_with("demo@example.com", 1234)

    def test_ext_submit_result_records_history_after_local_save_after_callback_exchange(self):
        api_routes = self._reload_api_routes()
        demo_password = "unit-test-pass"
        calls = []

        def _record_extension(req, run_id=0):
            calls.append(("history", req.token_data))
            return 456

        def _save_account(email, password, token_data):
            calls.append(("save", token_data))
            return True

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
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
        self.assertEqual(("save", json.dumps({"email": "demo@example.com"})), calls[0])
        self.assertEqual(("history", json.dumps({"email": "demo@example.com"})), calls[1])

    def test_cluster_upload_accounts_records_history_after_local_save(self):
        api_routes = self._reload_api_routes()
        payload = {
            "analytics_run_id": 2468,
            "email": "cluster@example.com",
            "password": "unit-pass",
            "token_data": json.dumps({"email": "cluster@example.com"}),
            "started_at": "2026-04-18 08:20:00",
            "finished_at": "2026-04-18 08:30:00",
        }
        calls = []

        def _save_account(email, password, token_data):
            calls.append(("save", email))
            return True

        def _record_cluster(payload_arg, **kwargs):
            calls.append(("history", payload_arg["email"]))
            return 321

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.db_manager, "save_account_to_db", side_effect=_save_account):
                with patch.object(api_routes.db_manager, "set_account_analytics_run_id") as set_run_id:
                    with patch.object(
                        api_routes.registration_history,
                        "record_cluster_account_result",
                        side_effect=_record_cluster,
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
        self.assertEqual(2468, record_cluster.call_args.kwargs["run_id"])
        set_run_id.assert_called_once_with("cluster@example.com", 2468)
        self.assertEqual(("save", "cluster@example.com"), calls[0])
        self.assertEqual(("history", "cluster@example.com"), calls[1])

    def test_start_task_keeps_main_path_when_start_run_fails(self):
        api_routes = self._reload_api_routes()
        api_routes.engine = types.SimpleNamespace(
            is_running=lambda: False,
            start_cpa=lambda args: None,
            start_sub2api=lambda args: None,
            start_normal=lambda args: None,
        )

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes, "reload_all_configs"):
                with patch.object(api_routes.registration_history, "start_run", side_effect=RuntimeError("start-run-boom")):
                    result = asyncio.run(api_routes.start_task(token="demo-token"))

        self.assertEqual("success", result["status"])
        self.assertGreater(api_routes.core_engine.run_stats["analytics_run_id"], 0)

    def test_ext_reset_stats_keeps_main_path_when_start_run_fails(self):
        api_routes = self._reload_api_routes()
        api_routes.core_engine.cfg.NORMAL_TARGET_COUNT = 3

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.registration_history, "start_run", side_effect=RuntimeError("start-run-boom")):
                result = api_routes.ext_reset_stats(token="demo-token")

        self.assertEqual({"status": "success"}, result)
        self.assertGreater(api_routes.core_engine.run_stats["analytics_run_id"], 0)

    def test_stop_task_keeps_main_path_when_finish_run_fails(self):
        api_routes = self._reload_api_routes()
        api_routes.engine = types.SimpleNamespace(is_running=lambda: True, stop=lambda: None)
        api_routes.core_engine.run_stats.update({
            "success": 1,
            "failed": 0,
            "retries": 0,
            "start_time": 100.0,
            "target": 1,
            "pwd_blocked": 0,
            "phone_verify": 0,
            "analytics_run_id": 55,
        })

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.asyncio, "create_task"):
                with patch.object(api_routes.registration_history, "finish_run", side_effect=RuntimeError("finish-run-boom")):
                    with patch.object(api_routes.time, "time", return_value=102.0):
                        result = asyncio.run(api_routes.stop_task(token="demo-token"))

        self.assertEqual("success", result["status"])

    def test_ext_stop_keeps_main_path_when_finish_run_fails(self):
        api_routes = self._reload_api_routes()
        api_routes.core_engine.run_stats["analytics_run_id"] = 66

        with patch.object(api_routes, "_run_history_task", side_effect=self._run_history_inline):
            with patch.object(api_routes.registration_history, "finish_run", side_effect=RuntimeError("finish-run-boom")):
                result = api_routes.ext_stop(token="demo-token")

        self.assertEqual({"status": "success"}, result)

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
