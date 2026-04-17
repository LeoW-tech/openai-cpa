import importlib
import sys
import unittest

from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class Sub2APIClientProxyBindingTests(unittest.TestCase):
    def _reload_client_module(self):
        sys.modules.pop("utils.integrations.sub2api_client", None)
        return importlib.import_module("utils.integrations.sub2api_client")

    def test_add_account_with_proxy_name_uses_import_endpoint(self):
        sub2api_client = self._reload_client_module()
        client = sub2api_client.Sub2APIClient(api_url="http://127.0.0.1:8080", api_key="demo-key")
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None, impersonate=None, proxies=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(status_code=200, payload={"status": "success"})

        token_data = {
            "email": "demo@example.com",
            "refresh_token": "refresh-token",
            "sub2api_proxy_name": "🇯🇵 日本W03 | IEPL",
        }

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post):
            ok, msg = client.add_account(token_data)

        self.assertTrue(ok)
        self.assertEqual("Sub2API account import succeeded", msg)
        self.assertEqual("http://127.0.0.1:8080/api/v1/admin/accounts/data", captured["url"])
        account = captured["json"]["data"]["accounts"][0]
        self.assertEqual("🇯🇵 日本W03 | IEPL", account["proxy_name"])
        self.assertEqual("refresh-token", account["credentials"]["refresh_token"])
        self.assertIn("load_factor", account["extra"])

    def test_add_account_without_proxy_name_keeps_direct_create(self):
        sub2api_client = self._reload_client_module()
        client = sub2api_client.Sub2APIClient(api_url="http://127.0.0.1:8080", api_key="demo-key")
        called_urls = []

        def fake_post(url, json=None, headers=None, timeout=None, impersonate=None, proxies=None):
            called_urls.append(url)
            if url.endswith("/api/v1/admin/accounts"):
                return _FakeResponse(status_code=200, payload={"data": {"id": "acc-1"}})
            return _FakeResponse(status_code=204, payload={})

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post):
            ok, msg = client.add_account({
                "email": "demo@example.com",
                "refresh_token": "refresh-token",
            })

        self.assertTrue(ok)
        self.assertEqual("Sub2API account created successfully", msg)
        self.assertEqual("http://127.0.0.1:8080/api/v1/admin/accounts", called_urls[0])


if __name__ == "__main__":
    unittest.main()
