import sys
import types
import unittest
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(post=None, get=None, Response=object)
sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module, CurlMime=object)
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


class MailServiceGmailOAuthModeTests(unittest.TestCase):
    def test_get_email_and_token_returns_generated_tuple_for_gmail_oauth_mode(self):
        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "Gmail_OAuth"), \
             patch.object(mail_service.cfg, "MAIL_DOMAINS", "example.com"), \
             patch.object(mail_service.cfg, "ENABLE_SUB_DOMAINS", False), \
             patch.object(mail_service.cfg, "GLOBAL_STOP", False, create=True), \
             patch.object(mail_service.cfg, "AI_ENABLE_PROFILE", False), \
             patch.object(mail_service, "_get_ai_data_package", return_value=("gmailoauth", False)):
            mail_service.clear_sticky_domain()
            email, token = mail_service.get_email_and_token()

        self.assertEqual("gmailoauth@example.com", email)
        self.assertEqual("", token)
        self.assertEqual("gmailoauth@example.com", mail_service.get_last_email())


if __name__ == "__main__":
    unittest.main()
