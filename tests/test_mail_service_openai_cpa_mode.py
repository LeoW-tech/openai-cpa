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


class MailServiceOpenAICPATests(unittest.TestCase):
    def test_get_email_and_token_returns_direct_email_in_openai_cpa_mode(self):
        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "openai_cpa"), \
             patch.object(mail_service.cfg, "MAIL_DOMAINS", "example.com"), \
             patch.object(mail_service.cfg, "ENABLE_SUB_DOMAINS", False), \
             patch.object(mail_service.cfg, "GLOBAL_STOP", False, create=True), \
             patch.object(mail_service.cfg, "AI_ENABLE_PROFILE", False), \
             patch.object(mail_service.cfg, "OPENAI_CPA_WEBHOOK_SECRET", "secret-123", create=True), \
             patch.object(mail_service, "_get_ai_data_package", return_value=("openaicpa", False)):
            mail_service.clear_sticky_domain()
            email, token = mail_service.get_email_and_token()

        self.assertEqual("openaicpa@example.com", email)
        self.assertEqual("", token)
        self.assertEqual("openaicpa@example.com", mail_service.get_last_email())

    def test_get_oai_code_reads_and_consumes_auth_core_code_pool(self):
        auth_core_pool = {"openaicpa@example.com": "Your ChatGPT code is 112233"}

        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "openai_cpa"), \
             patch.object(mail_service.cfg, "OPENAI_CPA_WEBHOOK_SECRET", "secret-123", create=True), \
             patch.dict(sys.modules, {"utils.auth_core": types.SimpleNamespace(code_pool=auth_core_pool)}):
            code = mail_service.get_oai_code("openaicpa@example.com", max_attempts=1)

        self.assertEqual("112233", code)
        self.assertNotIn("openaicpa@example.com", auth_core_pool)


if __name__ == "__main__":
    unittest.main()
