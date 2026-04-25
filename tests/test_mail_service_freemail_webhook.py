import sys
import types
import unittest
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(post=None, get=None, Response=object)
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module, CurlMime=object)

try:
    import socks  # noqa: F401
except Exception:
    sys.modules["socks"] = types.SimpleNamespace(
        SOCKS5=1,
        HTTP=2,
        socksocket=object,
    )

sys.modules.setdefault(
    "utils.integrations.ai_service",
    types.SimpleNamespace(AIService=object),
)
sys.modules.setdefault(
    "utils.email_providers.gmail_service",
    types.SimpleNamespace(get_gmail_otp_via_oauth=lambda *args, **kwargs: ""),
)
sys.modules.setdefault(
    "utils.email_providers.duckmail_service",
    types.SimpleNamespace(DuckMailService=object),
)

from utils.email_providers import mail_service


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class MailServiceFreemailWebhookTests(unittest.TestCase):
    def test_get_email_and_token_returns_direct_email_in_local_webhook_mode(self):
        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "freemail"), \
             patch.object(mail_service.cfg, "MAIL_DOMAINS", "example.com"), \
             patch.object(mail_service.cfg, "ENABLE_SUB_DOMAINS", False), \
             patch.object(mail_service.cfg, "GLOBAL_STOP", False, create=True), \
             patch.object(mail_service.cfg, "AI_ENABLE_PROFILE", False), \
             patch.object(mail_service.cfg, "FREEMAIL_LOCAL_WEBHOOK", True, create=True), \
             patch.object(mail_service, "_get_ai_data_package", return_value=("freemailhook", False)), \
             patch.object(mail_service.requests, "post") as post_mock:
            mail_service.clear_sticky_domain()
            email, token = mail_service.get_email_and_token()

        self.assertEqual("freemailhook@example.com", email)
        self.assertEqual("", token)
        self.assertEqual("freemailhook@example.com", mail_service.get_last_email())
        post_mock.assert_not_called()

    def test_get_oai_code_reads_from_local_webhook_code_pool(self):
        local_pool = {"freemailhook@example.com": "Your ChatGPT code is 112233"}

        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "freemail"), \
             patch.object(mail_service.cfg, "FREEMAIL_LOCAL_WEBHOOK", True, create=True), \
             patch.object(mail_service.cfg, "USE_PROXY_FOR_EMAIL", False), \
             patch.dict(sys.modules, {"routers.system_routes": types.SimpleNamespace(code_pool=local_pool)}):
            code = mail_service.get_oai_code("freemailhook@example.com", max_attempts=1)

        self.assertEqual("112233", code)
        self.assertNotIn("freemailhook@example.com", local_pool)

    def test_get_oai_code_uses_remote_freemail_api_when_local_webhook_disabled(self):
        emails_response = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "id": "mail-1",
                        "subject": "Your ChatGPT code is 654321",
                    }
                ]
            },
        )

        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "freemail"), \
             patch.object(mail_service.cfg, "FREEMAIL_LOCAL_WEBHOOK", False, create=True), \
             patch.object(mail_service.cfg, "FREEMAIL_API_URL", "https://freemail.test", create=True), \
             patch.object(mail_service.cfg, "FREEMAIL_API_TOKEN", "demo-token", create=True), \
             patch.object(mail_service.cfg, "USE_PROXY_FOR_EMAIL", False), \
             patch.object(mail_service.requests, "get", return_value=emails_response) as get_mock, \
             patch.dict(
                 sys.modules,
                 {"routers.system_routes": types.SimpleNamespace(code_pool={"remote@example.com": "111111"})},
             ):
            code = mail_service.get_oai_code("remote@example.com", max_attempts=1)

        self.assertEqual("654321", code)
        get_mock.assert_called_once()
        self.assertEqual("https://freemail.test/api/emails", get_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
