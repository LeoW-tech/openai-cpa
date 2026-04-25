import importlib
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch
from fastapi import APIRouter


class ApiRoutesSub2APIReconcileTests(unittest.TestCase):
    def setUp(self):
        self._module_stack = ExitStack()
        clash_manager_stub = types.SimpleNamespace(
            list_instances=lambda *args, **kwargs: [],
            create_pool=lambda *args, **kwargs: {"status": "success"},
            delete_pool=lambda *args, **kwargs: {"status": "success"},
            get_container_ip=lambda *args, **kwargs: None,
            get_controller_base=lambda *args, **kwargs: None,
            sync_subscription=lambda *args, **kwargs: {"status": "success"},
            refresh_instance=lambda *args, **kwargs: {"status": "success"},
            patch_and_update=lambda *args, **kwargs: {"status": "success"},
        )
        integrations_stub = types.ModuleType("utils.integrations")
        integrations_stub.clash_manager = clash_manager_stub
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
                    "routers.system_routes": types.SimpleNamespace(router=APIRouter()),
                    "routers.account_routes": types.SimpleNamespace(router=APIRouter()),
                    "routers.service_routes": types.SimpleNamespace(router=APIRouter()),
                    "routers.sms_routes": types.SimpleNamespace(router=APIRouter()),
                    "utils.auth_core": types.SimpleNamespace(
                        router=APIRouter(),
                        code_pool={},
                        cache_lock=object(),
                        generate_payload=lambda *args, **kwargs: "",
                    ),
                    "utils.proxy_manager": types.SimpleNamespace(
                        smart_switch_node=lambda *args, **kwargs: True,
                        reload_proxy_config=lambda *args, **kwargs: None,
                        get_last_success_node_name=lambda *args, **kwargs: None,
                    ),
                    "curl_cffi": types.SimpleNamespace(requests=types.SimpleNamespace(get=None, post=None), CurlMime=object),
                    "utils.integrations.sub2api_client": types.SimpleNamespace(
                        Sub2APIClient=lambda api_url, api_key: types.SimpleNamespace(api_url=api_url, api_key=api_key),
                        build_default_model_mapping=lambda: {},
                        build_sub2api_export_bundle=lambda *args, **kwargs: {},
                        get_sub2api_push_settings=lambda: {"concurrency": 10, "load_factor": 10, "priority": 1, "rate_multiplier": 1.0},
                    ),
                    "utils.integrations.tg_notifier": types.SimpleNamespace(
                        send_tg_msg_sync=lambda *args, **kwargs: None,
                        send_tg_msg_async=lambda *args, **kwargs: None,
                    ),
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        clear_sticky_domain=lambda: None,
                        mask_email=lambda value, force_mask=False: value,
                        get_last_email=lambda: "demo@example.com",
                    ),
                    "utils.register": types.SimpleNamespace(
                        run=lambda *args, **kwargs: None,
                        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
                    ),
                    "utils.integrations": integrations_stub,
                    "utils.email_providers.gmail_oauth_handler": types.SimpleNamespace(GmailOAuthHandler=object),
                    "utils.integrations.clash_manager": clash_manager_stub,
                    "cloudflare": types.SimpleNamespace(Cloudflare=object),
                },
            )
        )
        sys.modules.pop("routers.api_routes", None)

    def tearDown(self):
        sys.modules.pop("routers.api_routes", None)
        if hasattr(builtins, "_openai_cpa_real_print"):
            builtins.print = builtins._openai_cpa_real_print
        self._module_stack.close()

    def _reload_api_routes(self):
        import routers.api_routes as api_routes

        return importlib.reload(api_routes)

    def test_get_sub2api_reconcile_returns_audit_payload(self):
        api_routes = self._reload_api_routes()
        fake_audit = {
            "local_success_total": 2,
            "cloud_total": 1,
            "missing_total": 1,
            "rows": [{"email": "missing@example.com"}],
        }

        with patch.object(api_routes.core_engine.cfg, "SUB2API_URL", "http://127.0.0.1:8080"), \
             patch.object(api_routes.core_engine.cfg, "SUB2API_KEY", "demo-key"), \
             patch.object(api_routes.sub2api_reconcile, "list_missing_sub2api_accounts", return_value=fake_audit) as reconcile:
            result = api_routes.get_sub2api_reconcile(limit=5, token="demo-token")

        self.assertEqual("success", result["status"])
        self.assertEqual(fake_audit, result["data"])
        reconcile.assert_called_once()
        self.assertEqual(5, reconcile.call_args.kwargs["limit"])

    def test_repair_sub2api_reconcile_returns_warning_when_any_row_fails(self):
        api_routes = self._reload_api_routes()
        fake_result = {
            "missing_total": 2,
            "repaired_total": 1,
            "failed_total": 1,
            "results": [
                {"email": "ok@example.com", "status": "repaired"},
                {"email": "fail@example.com", "status": "failed"},
            ],
        }

        with patch.object(api_routes.core_engine.cfg, "SUB2API_URL", "http://127.0.0.1:8080"), \
             patch.object(api_routes.core_engine.cfg, "SUB2API_KEY", "demo-key"), \
             patch.object(api_routes.sub2api_reconcile, "repair_missing_sub2api_accounts", return_value=fake_result) as reconcile:
            result = api_routes.repair_sub2api_reconcile(
                api_routes.Sub2APIReconcileRepairReq(emails=["fail@example.com"], limit=3, max_attempts=4),
                token="demo-token",
            )

        self.assertEqual("warning", result["status"])
        self.assertEqual(fake_result, result["data"])
        reconcile.assert_called_once()
        kwargs = reconcile.call_args.kwargs
        self.assertEqual(["fail@example.com"], kwargs["emails"])
        self.assertEqual(3, kwargs["limit"])
        self.assertEqual(4, kwargs["max_attempts"])


if __name__ == "__main__":
    unittest.main()
