import asyncio
import importlib
import sys
import types
import unittest
import builtins
from contextlib import ExitStack
from unittest.mock import patch


class ApiRoutesSub2ApiExportTests(unittest.TestCase):
    def setUp(self):
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
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
                    "utils.integrations.clash_manager": types.SimpleNamespace(
                        list_instances=lambda *args, **kwargs: [],
                        create_pool=lambda *args, **kwargs: {"status": "success"},
                        delete_pool=lambda *args, **kwargs: {"status": "success"},
                        get_container_ip=lambda *args, **kwargs: None,
                        get_controller_base=lambda *args, **kwargs: None,
                        sync_subscription=lambda *args, **kwargs: {"status": "success"},
                        refresh_instance=lambda *args, **kwargs: {"status": "success"},
                        patch_and_update=lambda *args, **kwargs: {"status": "success"},
                    ),
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


if __name__ == "__main__":
    unittest.main()
