import importlib
import sys
import unittest

from unittest.mock import patch

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
    "gpt-5.4-mini": "gpt-5.4-mini",
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeUuid:
    def __init__(self, hex_value):
        self.hex = hex_value


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
            captured["headers"] = dict(headers or {})
            return _FakeResponse(status_code=200, payload={"status": "success"})

        token_data = {
            "email": "demo@example.com",
            "refresh_token": "refresh-token",
            "sub2api_proxy_name": "🇯🇵 日本W03 | IEPL",
        }

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post), \
             patch.object(sub2api_client.uuid, "uuid4", return_value=_FakeUuid("test-uuid")):
            ok, msg = client.add_account(token_data)

        self.assertTrue(ok)
        self.assertEqual("Sub2API account import succeeded", msg)
        self.assertEqual("http://127.0.0.1:8080/api/v1/admin/accounts/data", captured["url"])
        account = captured["json"]["data"]["accounts"][0]
        self.assertEqual("🇯🇵 日本W03 | IEPL", account["proxy_name"])
        self.assertEqual("refresh-token", account["credentials"]["refresh_token"])
        self.assertEqual(EXPECTED_MODEL_MAPPING, account["credentials"]["model_mapping"])
        self.assertIn("load_factor", account["extra"])
        self.assertEqual("import-test-uuid", captured["headers"]["Idempotency-Key"])

    def test_add_account_import_uses_unique_idempotency_key_per_request(self):
        sub2api_client = self._reload_client_module()
        client = sub2api_client.Sub2APIClient(api_url="http://127.0.0.1:8080", api_key="demo-key")
        captured_headers = []

        def fake_post(url, json=None, headers=None, timeout=None, impersonate=None, proxies=None):
            captured_headers.append(dict(headers or {}))
            return _FakeResponse(status_code=200, payload={"status": "success"})

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post), \
             patch.object(sub2api_client.uuid, "uuid4", side_effect=[_FakeUuid("uuid-one"), _FakeUuid("uuid-two")]):
            ok_first, _ = client.add_account({
                "email": "first@example.com",
                "access_token": "access-one",
                "refresh_token": "refresh-one",
            })
            ok_second, _ = client.add_account({
                "email": "second@example.com",
                "access_token": "access-two",
                "refresh_token": "refresh-two",
            })

        self.assertTrue(ok_first)
        self.assertTrue(ok_second)
        self.assertEqual("import-uuid-one", captured_headers[0]["Idempotency-Key"])
        self.assertEqual("import-uuid-two", captured_headers[1]["Idempotency-Key"])
        self.assertNotEqual(captured_headers[0]["Idempotency-Key"], captured_headers[1]["Idempotency-Key"])

    def test_add_account_with_access_token_and_no_proxy_uses_import_endpoint(self):
        sub2api_client = self._reload_client_module()
        client = sub2api_client.Sub2APIClient(api_url="http://127.0.0.1:8080", api_key="demo-key")
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None, impersonate=None, proxies=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(status_code=200, payload={"status": "success"})

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post), \
             patch.object(sub2api_client.cfg, "get_next_sub2api_proxy_url", return_value=""):
            ok, msg = client.add_account({
                "email": "demo@example.com",
                "access_token": "access-token",
                "client_id": "client-id",
                "refresh_token": "refresh-token",
            })

        self.assertTrue(ok)
        self.assertEqual("Sub2API account import succeeded", msg)
        self.assertEqual("http://127.0.0.1:8080/api/v1/admin/accounts/data", captured["url"])
        account = captured["json"]["data"]["accounts"][0]
        self.assertEqual("access-token", account["credentials"]["access_token"])
        self.assertEqual("client-id", account["credentials"]["client_id"])
        self.assertEqual("refresh-token", account["credentials"]["refresh_token"])
        self.assertEqual(EXPECTED_MODEL_MAPPING, account["credentials"]["model_mapping"])

    def test_add_account_refresh_only_without_proxy_uses_direct_create_endpoint(self):
        sub2api_client = self._reload_client_module()
        client = sub2api_client.Sub2APIClient(api_url="http://127.0.0.1:8080", api_key="demo-key")
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None, impersonate=None, proxies=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(status_code=200, payload={"status": "success"})

        with patch.object(sub2api_client.cffi_requests, "post", side_effect=fake_post), \
             patch.object(sub2api_client.cfg, "get_next_sub2api_proxy_url", return_value=""):
            ok, msg = client.add_account({
                "email": "demo@example.com",
                "refresh_token": "refresh-token",
            })

        self.assertTrue(ok)
        self.assertEqual("Sub2API account created successfully", msg)
        self.assertEqual("http://127.0.0.1:8080/api/v1/admin/accounts", captured["url"])
        account = captured["json"]
        self.assertEqual({"refresh_token": "refresh-token"}, account["credentials"])


if __name__ == "__main__":
    unittest.main()
