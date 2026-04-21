import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeAPIRouter:
    def get(self, *args, **kwargs):
        return self._decorate

    def post(self, *args, **kwargs):
        return self._decorate

    def websocket(self, *args, **kwargs):
        return self._decorate

    @staticmethod
    def _decorate(func):
        return func


class _FakeHTMLResponse:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeStreamingResponse(_FakeHTMLResponse):
    pass


class ApiConfigHeroSmsTests(unittest.TestCase):
    def setUp(self):
        fastapi_module = types.ModuleType("fastapi")
        fastapi_module.APIRouter = _FakeAPIRouter
        fastapi_module.Depends = lambda dependency=None: dependency
        fastapi_module.Header = lambda default=None, **kwargs: default
        fastapi_module.Query = lambda default=None, **kwargs: default
        fastapi_module.Request = type("Request", (), {})
        fastapi_module.WebSocket = type("WebSocket", (), {})
        fastapi_module.HTTPException = type("HTTPException", (Exception,), {})

        fastapi_responses_module = types.ModuleType("fastapi.responses")
        fastapi_responses_module.HTMLResponse = _FakeHTMLResponse
        fastapi_responses_module.StreamingResponse = _FakeStreamingResponse

        self._module_patches = patch.dict(
            sys.modules,
            {
                "fastapi": fastapi_module,
                "fastapi.responses": fastapi_responses_module,
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

    def test_save_config_merges_missing_sections_from_existing_runtime_config(self):
        api_routes = self._reload_api_routes()
        api_routes.core_engine.cfg._c = {
            "hero_sms": {
                "enabled": True,
                "reuse_phone": True,
                "api_key": "existing-key",
                "base_url": "https://hero-sms.example/api",
            },
            "sub2api_mode": {
                "enable": False,
                "api_url": "https://sub2api.example",
                "api_key": "sub-key",
                "threads": 10,
            },
            "cpa_mode": {
                "enable": False,
                "api_url": "https://cpa.example",
                "api_token": "cpa-token",
            },
            "tg_bot": {
                "enable": True,
                "chat_id": "chat-1",
            },
            "web_password": "secret-pass",
        }
        new_config = {
            "hero_sms": {
                "enabled": False,
            },
            "sub2api_mode": {},
            "cpa_mode": {},
        }

        with patch.object(api_routes, "reload_all_configs") as reload_configs:
            result = asyncio.run(api_routes.save_config(new_config=new_config, token="demo"))

        self.assertEqual("success", result["status"])
        saved_config = reload_configs.call_args.kwargs["new_config_dict"]
        self.assertEqual(False, saved_config["hero_sms"]["enabled"])
        self.assertEqual("existing-key", saved_config["hero_sms"]["api_key"])
        self.assertEqual("https://hero-sms.example/api", saved_config["hero_sms"]["base_url"])
        self.assertEqual("https://sub2api.example", saved_config["sub2api_mode"]["api_url"])
        self.assertEqual("sub-key", saved_config["sub2api_mode"]["api_key"])
        self.assertEqual("https://cpa.example", saved_config["cpa_mode"]["api_url"])
        self.assertEqual("cpa-token", saved_config["cpa_mode"]["api_token"])
        self.assertEqual({"enable": True, "chat_id": "chat-1"}, saved_config["tg_bot"])
        self.assertEqual("secret-pass", saved_config["web_password"])


if __name__ == "__main__":
    unittest.main()
