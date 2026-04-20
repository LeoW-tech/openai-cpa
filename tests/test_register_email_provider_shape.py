import importlib
import io
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None

    def close(self):
        return None


class RegisterEmailProviderShapeTests(unittest.TestCase):
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
                        get_email_and_token=lambda *args, **kwargs: ("", ""),
                        get_oai_code=lambda *args, **kwargs: "",
                        mask_email=lambda value, force_mask=False: value,
                        clear_sticky_domain=lambda: None,
                        get_last_email=lambda: "demo@example.com",
                    ),
                    "utils.integrations.hero_sms": types.SimpleNamespace(
                        _try_verify_phone_via_hero_sms=lambda *args, **kwargs: (False, "")
                    ),
                    "utils.auth_core": types.SimpleNamespace(generate_payload=lambda *args, **kwargs: "sentinel-token"),
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

    def test_run_handles_non_tuple_email_provider_result_without_unpacking_exception(self):
        with patch.object(self.register, "_skip_net_check", return_value=True), \
             patch.object(self.register, "get_email_and_token", return_value=None), \
             patch.object(self.register, "_set_failure") as set_failure_mock:
            with redirect_stdout(io.StringIO()):
                result = self.register.run("http://127.0.0.1:7890")

        self.assertEqual((None, None), result)
        set_failure_mock.assert_called_once()
        self.assertEqual("email_acquire", set_failure_mock.call_args.kwargs["stage"])

    def test_run_accepts_tuple_proxy_queue_items(self):
        with patch.object(self.register, "_skip_net_check", return_value=True), \
             patch.object(self.register, "get_email_and_token", return_value=None), \
             patch.object(self.register, "_set_failure") as set_failure_mock:
            with redirect_stdout(io.StringIO()):
                result = self.register.run((3, "http://127.0.0.1:7890"))

        self.assertEqual((None, None), result)
        set_failure_mock.assert_called_once()
        self.assertEqual("email_acquire", set_failure_mock.call_args.kwargs["stage"])


if __name__ == "__main__":
    unittest.main()
