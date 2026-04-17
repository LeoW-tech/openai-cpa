import importlib
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
    types.SimpleNamespace(
        send_tg_msg_sync=lambda *args, **kwargs: None,
        send_tg_msg_async=lambda *args, **kwargs: None,
    ),
)
sys.modules.setdefault(
    "utils.email_providers.gmail_oauth_handler",
    types.SimpleNamespace(GmailOAuthHandler=object),
)
sys.modules.setdefault("cloudflare", types.SimpleNamespace(Cloudflare=object))
sys.modules.setdefault(
    "utils.integrations.clash_manager",
    types.SimpleNamespace(
        list_instances=lambda *args, **kwargs: [],
        create_pool=lambda *args, **kwargs: {"status": "success"},
        delete_pool=lambda *args, **kwargs: {"status": "success"},
        get_container_ip=lambda *args, **kwargs: None,
        get_controller_base=lambda *args, **kwargs: None,
        sync_subscription=lambda *args, **kwargs: {"status": "success"},
        refresh_instance=lambda *args, **kwargs: {"status": "success"},
    ),
)


class CloudAccountsCpaGuardTests(unittest.TestCase):
    def _reload_api_routes(self):
        import routers.api_routes as api_routes

        return importlib.reload(api_routes)

    def test_cloud_accounts_skip_cpa_when_mode_disabled(self):
        api_routes = self._reload_api_routes()

        fake_sub2_items = [
            {
                "id": "sub2-1",
                "name": "sub2-demo",
                "status": "active",
                "updated_at": "2026-04-17T10:00:00.000Z",
                "credentials": {"plan_type": "plus"},
                "extra": {"codex_5h_used_percent": 10, "codex_7d_used_percent": 20},
            }
        ]

        class FakeSub2APIClient:
            def __init__(self, api_url, api_key):
                self.api_url = api_url
                self.api_key = api_key

            def get_all_accounts(self):
                return True, fake_sub2_items

        with patch.object(api_routes.cfg, "ENABLE_CPA_MODE", False), \
             patch.object(api_routes.cfg, "CPA_API_URL", "http://your-domain.com:8317"), \
             patch.object(api_routes.cfg, "CPA_API_TOKEN", "xxxx"), \
             patch.object(api_routes.cfg, "SUB2API_URL", "http://127.0.0.1:8080"), \
             patch.object(api_routes.cfg, "SUB2API_KEY", "demo-key"), \
             patch.object(api_routes, "Sub2APIClient", FakeSub2APIClient), \
             patch("curl_cffi.requests.get", side_effect=AssertionError("CPA request should not be called")):
            result = api_routes.get_cloud_accounts(types="sub2api,cpa", page=1, page_size=50, token="demo-token")

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["total"])
        self.assertEqual(["sub2api"], [item["account_type"] for item in result["data"]])

    def test_cloud_accounts_skip_cpa_when_placeholder_config_left_in_place(self):
        api_routes = self._reload_api_routes()

        with patch.object(api_routes.cfg, "ENABLE_CPA_MODE", True), \
             patch.object(api_routes.cfg, "CPA_API_URL", "http://your-domain.com:8317"), \
             patch.object(api_routes.cfg, "CPA_API_TOKEN", "xxxx"), \
             patch("curl_cffi.requests.get", side_effect=AssertionError("Placeholder CPA config should be ignored")):
            result = api_routes.get_cloud_accounts(types="cpa", page=1, page_size=50, token="demo-token")

        self.assertEqual("success", result["status"])
        self.assertEqual([], result["data"])
        self.assertEqual(0, result["total"])


if __name__ == "__main__":
    unittest.main()
