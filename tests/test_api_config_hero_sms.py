import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class ApiConfigHeroSmsTests(unittest.TestCase):
    def setUp(self):
        self._module_patches = patch.dict(
            sys.modules,
            {
                "utils.core_engine": types.SimpleNamespace(cfg=types.SimpleNamespace(_c={})),
                "utils.db_manager": types.SimpleNamespace(),
                "utils.registration_history": types.SimpleNamespace(),
                "utils.integrations.sub2api_client": types.SimpleNamespace(
                    Sub2APIClient=object,
                    build_default_model_mapping=lambda: {},
                ),
                "utils.integrations.tg_notifier": types.SimpleNamespace(send_tg_msg_async=lambda *args, **kwargs: None),
                "utils.email_providers.gmail_oauth_handler": types.SimpleNamespace(GmailOAuthHandler=object),
                "global_state": types.SimpleNamespace(
                    VALID_TOKENS=set(),
                    CLUSTER_NODES={},
                    NODE_COMMANDS={},
                    cluster_lock=types.SimpleNamespace(),
                    log_history=[],
                    engine=None,
                    verify_token=lambda: "token",
                    worker_status={},
                ),
                "cloudflare": types.SimpleNamespace(Cloudflare=object),
                "curl_cffi": types.SimpleNamespace(requests=types.SimpleNamespace()),
            },
        )
        self._module_patches.start()
        sys.modules.pop("routers.api_routes", None)

    def tearDown(self):
        sys.modules.pop("routers.api_routes", None)
        self._module_patches.stop()

    def _reload_api_routes(self):
        import routers.api_routes as api_routes

        return importlib.reload(api_routes)

    def test_get_config_strips_legacy_hero_sms_reuse_max_uses(self):
        api_routes = self._reload_api_routes()
        api_routes.core_engine.cfg._c = {
            "hero_sms": {
                "enabled": True,
                "reuse_phone": True,
                "reuse_max_uses": 3,
            }
        }

        result = asyncio.run(api_routes.get_config(token="demo"))

        self.assertNotIn("reuse_max_uses", result["hero_sms"])

    def test_save_config_strips_legacy_hero_sms_reuse_max_uses_before_reload(self):
        api_routes = self._reload_api_routes()
        new_config = {
            "hero_sms": {
                "enabled": True,
                "reuse_phone": True,
                "reuse_max_uses": 5,
            }
        }

        with patch.object(api_routes, "reload_all_configs") as reload_configs:
            result = asyncio.run(api_routes.save_config(new_config=new_config, token="demo"))

        self.assertEqual("success", result["status"])
        saved_config = reload_configs.call_args.kwargs["new_config_dict"]
        self.assertNotIn("reuse_max_uses", saved_config["hero_sms"])


if __name__ == "__main__":
    unittest.main()
