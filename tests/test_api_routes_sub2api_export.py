import asyncio
import importlib
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch
from fastapi import APIRouter

EXPECTED_MODEL_MAPPING = {
    "gpt-5.1": "gpt-5.1",
    "gpt-5.1-codex": "gpt-5.1-codex",
    "gpt-5.1-codex-max": "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
    "gpt-5.2": "gpt-5.2",
    "gpt-5.2-codex": "gpt-5.2-codex",
    "gpt-5.3": "gpt-5.3",
    "gpt-5.3-codex": "gpt-5.3-codex",
    "gpt-5.4": "gpt-5.4",
}


class ApiRoutesSub2ApiExportTests(unittest.TestCase):
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
                        Sub2APIClient=object,
                        build_default_model_mapping=lambda: EXPECTED_MODEL_MAPPING.copy(),
                        build_sub2api_export_bundle=lambda token_items, settings=None, rotate_missing_proxy=False: {
                            "exported_at": "2026-04-25T00:00:00Z",
                            "proxies": [],
                            "accounts": [
                                {
                                    "name": str(token_items[0].get("email", "unknown"))[:64],
                                    "platform": "openai",
                                    "type": "oauth",
                                    "credentials": {
                                        "refresh_token": token_items[0].get("refresh_token", ""),
                                        "model_mapping": EXPECTED_MODEL_MAPPING.copy(),
                                    },
                                    "concurrency": 10,
                                    "priority": 1,
                                    "rate_multiplier": 1.0,
                                    "extra": {"load_factor": 10},
                                    "proxy_name": token_items[0].get("sub2api_proxy_name", ""),
                                }
                            ],
                        },
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

    def test_export_sub2api_accounts_includes_proxy_name(self):
        api_routes = self._reload_api_routes()
        tokens = [{
            "email": "demo@example.com",
            "refresh_token": "refresh-token",
            "sub2api_proxy_name": "🇯🇵 日本W03 | IEPL",
        }]

        with patch.object(api_routes.db_manager, "get_tokens_by_emails", return_value=tokens):
            result = asyncio.run(
                api_routes.export_sub2api_accounts(
                    api_routes.ExportReq(emails=["demo@example.com"]),
                    token="demo-token",
                )
            )

        self.assertEqual("success", result["status"])
        account = result["data"]["accounts"][0]
        self.assertEqual("🇯🇵 日本W03 | IEPL", account["proxy_name"])
        self.assertEqual("refresh-token", account["credentials"]["refresh_token"])
        self.assertEqual(EXPECTED_MODEL_MAPPING, account["credentials"]["model_mapping"])


if __name__ == "__main__":
    unittest.main()
