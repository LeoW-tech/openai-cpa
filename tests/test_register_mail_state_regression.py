import importlib
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeCookies(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self.headers = {"User-Agent": "unit-test-agent"}
        self.timeout = None
        self.cookies = _FakeCookies({"oai-did": "did-demo"})

    def get(self, *args, **kwargs):
        return _FakeResponse()

    def close(self):
        return None


class RegisterMailStateRegressionTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(
            get=None,
            post=None,
            Session=_FakeSession,
        )
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
                    "curl_cffi": types.SimpleNamespace(requests=fake_requests_module),
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        get_email_and_token=lambda *args, **kwargs: ("demo@example.com", '{"email":"demo@example.com"}'),
                        get_oai_code=lambda *args, **kwargs: "",
                        mask_email=lambda value, force_mask=False: value,
                        record_ms_snapshot=lambda *args, **kwargs: None,
                    ),
                    "utils.integrations.hero_sms": types.SimpleNamespace(
                        _try_verify_phone_via_hero_sms=lambda *args, **kwargs: (False, "")
                    ),
                    "utils.auth_core": types.SimpleNamespace(
                        generate_payload=lambda *args, **kwargs: "sentinel-token",
                        init_auth=lambda *args, **kwargs: ("did-demo", "unit-test-agent"),
                    ),
                    "utils.region_policy": types.SimpleNamespace(is_openai_region_blocked=lambda *args, **kwargs: False),
                },
            )
        )
        sys.modules.pop("utils.register", None)
        import utils.register as register

        self.register = importlib.reload(register)

    def tearDown(self):
        sys.modules.pop("utils.register", None)
        self._module_stack.close()

    def test_takeover_flow_calls_get_oai_code_with_upstream_signature(self):
        captured = {}

        def strict_get_oai_code(email, jwt="", proxies=None, processed_mail_ids=None):
            captured["email"] = email
            captured["jwt"] = jwt
            captured["proxies"] = proxies
            captured["processed_mail_ids"] = processed_mail_ids
            return "112233"

        def fake_post_with_retry(session, url, **kwargs):
            if url == "https://auth.openai.com/api/accounts/authorize/continue":
                return _FakeResponse(200, {"continue_url": "https://auth.openai.com/log-in/password"})
            if url == "https://auth.openai.com/api/accounts/passwordless/send-otp":
                return _FakeResponse(200, {})
            raise RuntimeError("stop-after-get-oai-code")

        with patch.object(self.register, "_skip_net_check", return_value=True), \
             patch.object(self.register, "get_email_and_token", return_value=("demo@example.com", '{"email":"demo@example.com"}')), \
             patch.object(self.register, "get_oai_code", side_effect=strict_get_oai_code), \
             patch.object(self.register, "_post_with_retry", side_effect=fake_post_with_retry), \
             patch.object(self.register, "_record_token_wait_history", side_effect=RuntimeError("stop-after-get-oai-code")), \
             patch.object(self.register.time, "sleep", return_value=None):
            with redirect_stdout(StringIO()):
                result = self.register.run("http://127.0.0.1:7890", run_ctx={"analytics_attempt_id": 1})

        self.assertEqual((None, None), result)
        self.assertEqual("demo@example.com", captured["email"])
        self.assertEqual('{"email":"demo@example.com"}', captured["jwt"])
        self.assertEqual(
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            captured["proxies"],
        )
        self.assertIsInstance(captured["processed_mail_ids"], set)


if __name__ == "__main__":
    unittest.main()
