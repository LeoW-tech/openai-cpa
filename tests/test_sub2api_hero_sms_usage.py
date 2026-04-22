import importlib
import json
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch


class Sub2ApiHeroSmsUsageTests(unittest.TestCase):
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
                    ),
                    "utils.proxy_manager": types.SimpleNamespace(
                        smart_switch_node=lambda *args, **kwargs: True,
                        reload_proxy_config=lambda *args, **kwargs: None,
                        get_last_success_node_name=lambda *args, **kwargs: None,
                    ),
                    "utils.integrations.sub2api_client": types.SimpleNamespace(Sub2APIClient=object),
                    "utils.integrations.tg_notifier": types.SimpleNamespace(
                        send_tg_msg_sync=lambda *args, **kwargs: None
                    ),
                },
            )
        )
        sys.modules.pop("utils.core_engine", None)
        sys.modules.pop("utils.integrations.hero_sms", None)

    def tearDown(self):
        sys.modules.pop("utils.core_engine", None)
        sys.modules.pop("utils.integrations.hero_sms", None)
        if hasattr(builtins, "_openai_cpa_real_print"):
            builtins.print = builtins._openai_cpa_real_print
        self._module_stack.close()

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

    def test_handle_registration_result_emits_celebratory_safe_store_log(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), "Password123!")
        captured_logs = []

        with patch.dict(
            sys.modules,
            {
                "global_state": types.SimpleNamespace(append_log=captured_logs.append),
            },
        ):
            with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True):
                with patch.object(core_engine, "send_tg_msg_sync"):
                    with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                        status = core_engine.handle_registration_result(result, cpa_upload=False, run_ctx={})

        self.assertEqual("success", status)
        self.assertTrue(
            any("🎉🎉🥳🥳🎊✨🔥 账号密码与 Token 已安全存入: demo@example.com" in log for log in captured_logs)
        )

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

    def test_handle_registration_result_keeps_original_token_data_unchanged(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com"}), "Password123!")

        with patch.object(core_engine.db_manager, "save_account_to_db", return_value=True) as save_account:
            with patch.object(core_engine, "send_tg_msg_sync"):
                with patch.object(core_engine.mail_service, "get_last_email", return_value="demo@example.com"):
                    run_ctx = {"sub2api_proxy_name": "🇯🇵 日本W03 | IEPL"}
                    status = core_engine.handle_registration_result(result, cpa_upload=False, run_ctx=run_ctx)

        self.assertEqual("success", status)
        saved_token_data = json.loads(save_account.call_args.args[2])
        self.assertEqual({"email": "demo@example.com"}, saved_token_data)

    def test_reload_core_engine_does_not_stack_print_wrapper(self):
        first = self._reload_core_engine()
        second = self._reload_core_engine()

        self.assertIs(first._orig_print, second._orig_print)
        self.assertIs(sys.modules["builtins"].print, second.web_print)

    def test_core_engine_no_longer_exposes_deferred_hero_sms_confirmation_helpers(self):
        core_engine = self._reload_core_engine()
        self.assertFalse(hasattr(core_engine, "confirm_effective_hero_sms_usage"))
        self.assertFalse(hasattr(core_engine, "confirm_sub2api_hero_sms_usage"))

    def test_run_and_refresh_does_not_seed_deferred_hero_sms_counting_mode(self):
        core_engine = self._reload_core_engine()

        with patch.object(core_engine, "smart_switch_node", return_value=True):
            with patch.object(core_engine.registration_history, "start_attempt", return_value=1):
                with patch.object(core_engine, "run", return_value=("{}", "Password123!")) as run_mock:
                    with patch.object(core_engine, "handle_registration_result", return_value="success"):
                        status = core_engine.run_and_refresh("http://127.0.0.1:7890", args=object(), cpa_upload=False)

        self.assertEqual("success", status)
        run_ctx = run_mock.call_args.kwargs["run_ctx"]
        self.assertNotIn("hero_sms_counting_mode", run_ctx)

    def test_add_result_account_to_sub2api_applies_proxy_name_before_remote_push(self):
        core_engine = self._reload_core_engine()
        result = (json.dumps({"email": "demo@example.com", "refresh_token": "rt-demo"}), "Password123!")
        run_ctx = {"sub2api_proxy_name": "🇯🇵 日本W03 | IEPL"}

        class _FakeClient:
            def __init__(self):
                self.payload = None

            def add_account(self, payload):
                self.payload = payload
                return True, "ok"

        client = _FakeClient()
        ok, msg, token_dict = core_engine.add_result_account_to_sub2api(
            client=client,
            result=result,
            run_ctx=run_ctx,
            proxy_url="http://127.0.0.1:7890",
        )

        self.assertTrue(ok)
        self.assertEqual("ok", msg)
        self.assertEqual("🇯🇵 日本W03 | IEPL", token_dict["sub2api_proxy_name"])
        self.assertEqual("🇯🇵 日本W03 | IEPL", client.payload["sub2api_proxy_name"])

    def test_log_sub2api_restock_success_emits_celebratory_log(self):
        core_engine = self._reload_core_engine()
        captured_logs = []

        with patch.dict(
            sys.modules,
            {
                "global_state": types.SimpleNamespace(append_log=captured_logs.append),
            },
        ):
            core_engine._log_sub2api_restock_success()

        self.assertTrue(any("🚀🚀🎊🥳✨🔥 Sub2API 补货入库成功" in log for log in captured_logs))

    def test_borrow_proxy_queue_item_unwraps_generation_tuple(self):
        core_engine = self._reload_core_engine()
        original_queue = list(core_engine.cfg.PROXY_QUEUE.queue)
        original_unfinished_tasks = core_engine.cfg.PROXY_QUEUE.unfinished_tasks

        try:
            with core_engine.cfg.PROXY_QUEUE.mutex:
                core_engine.cfg.PROXY_QUEUE.queue.clear()
                core_engine.cfg.PROXY_QUEUE.unfinished_tasks = 0
                core_engine.cfg.PROXY_QUEUE.all_tasks_done.notify_all()

            core_engine.cfg.PROXY_QUEUE.put((7, "http://127.0.0.1:41001"))
            borrowed_generation, proxy = core_engine._borrow_proxy_queue_item()

            self.assertEqual(7, borrowed_generation)
            self.assertEqual("http://127.0.0.1:41001", proxy)
        finally:
            with core_engine.cfg.PROXY_QUEUE.mutex:
                core_engine.cfg.PROXY_QUEUE.queue.clear()
                core_engine.cfg.PROXY_QUEUE.unfinished_tasks = original_unfinished_tasks
                for item in original_queue:
                    core_engine.cfg.PROXY_QUEUE.queue.append(item)
                if core_engine.cfg.PROXY_QUEUE.unfinished_tasks == 0:
                    core_engine.cfg.PROXY_QUEUE.all_tasks_done.notify_all()

    def test_return_proxy_queue_item_requeues_generation_wrapped_proxy(self):
        core_engine = self._reload_core_engine()
        original_queue = list(core_engine.cfg.PROXY_QUEUE.queue)
        original_unfinished_tasks = core_engine.cfg.PROXY_QUEUE.unfinished_tasks

        try:
            with core_engine.cfg.PROXY_QUEUE.mutex:
                core_engine.cfg.PROXY_QUEUE.queue.clear()
                core_engine.cfg.PROXY_QUEUE.unfinished_tasks = 0
                core_engine.cfg.PROXY_QUEUE.all_tasks_done.notify_all()

            core_engine.cfg.PROXY_QUEUE.put((9, "http://127.0.0.1:41009"))
            borrowed_generation, proxy = core_engine._borrow_proxy_queue_item()
            core_engine._return_proxy_queue_item(proxy, borrowed_generation, preserve_stale=True)

            self.assertEqual([(9, "http://127.0.0.1:41009")], list(core_engine.cfg.PROXY_QUEUE.queue))
            self.assertEqual(1, core_engine.cfg.PROXY_QUEUE.unfinished_tasks)
        finally:
            with core_engine.cfg.PROXY_QUEUE.mutex:
                core_engine.cfg.PROXY_QUEUE.queue.clear()
                core_engine.cfg.PROXY_QUEUE.unfinished_tasks = original_unfinished_tasks
                for item in original_queue:
                    core_engine.cfg.PROXY_QUEUE.queue.append(item)
                if core_engine.cfg.PROXY_QUEUE.unfinished_tasks == 0:
                    core_engine.cfg.PROXY_QUEUE.all_tasks_done.notify_all()


if __name__ == "__main__":
    unittest.main()
