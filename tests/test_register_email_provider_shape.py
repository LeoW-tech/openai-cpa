import importlib
import sys
import types
import unittest
from pathlib import Path
from contextlib import ExitStack


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None

    def close(self):
        return None


class RegisterUpstreamSemanticsTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(
            get=None,
            post=None,
            Session=_FakeSession,
        )
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            unittest.mock.patch.dict(
                sys.modules,
                {
                    "curl_cffi": types.SimpleNamespace(requests=fake_requests_module),
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        get_email_and_token=lambda *args, **kwargs: ("", ""),
                        get_oai_code=lambda *args, **kwargs: "",
                        mask_email=lambda value, force_mask=False: value,
                        clear_sticky_domain=lambda: None,
                        get_last_email=lambda: "demo@example.com",
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
        self.source = Path(self.register.__file__).read_text(encoding="utf-8")

    def tearDown(self):
        sys.modules.pop("utils.register", None)
        self._module_stack.close()

    def test_register_source_uses_upstream_proxy_contract(self):
        self.assertNotIn("_normalize_proxy_input", self.source)
        self.assertIn("proxy = cfg.format_docker_url(proxy)", self.source)

    def test_register_source_directly_imports_and_uses_init_auth(self):
        self.assertIn("from utils.auth_core import generate_payload, init_auth", self.source)
        self.assertNotIn("except ImportError", self.source)

    def test_register_source_restores_upstream_email_unpacking(self):
        self.assertIn("email, email_jwt = get_email_and_token(proxies)", self.source)
        self.assertNotIn("email_result = get_email_and_token(proxies)", self.source)

    def test_register_source_removes_local_oauth_retry_flag(self):
        self.assertNotIn("retry_oauth_after_phone_gate", self.source)


if __name__ == "__main__":
    unittest.main()
