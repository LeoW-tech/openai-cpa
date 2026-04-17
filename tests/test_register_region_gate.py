import importlib
import io
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeSession:
    next_trace_text = "loc=US\n"

    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None

    def get(self, url, **kwargs):
        return _FakeResponse(self.next_trace_text)

    def close(self):
        return None


class RegisterRegionGateTests(unittest.TestCase):
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
                    ),
                    "utils.integrations.hero_sms": types.SimpleNamespace(
                        _try_verify_phone_via_hero_sms=lambda *args, **kwargs: (False, "")
                    ),
                    "utils.auth_core": types.SimpleNamespace(generate_payload=lambda *args, **kwargs: "sentinel-token"),
                },
            )
        )
        sys.modules.pop("utils.register", None)
        import utils.register as register

        self.register = importlib.reload(register)

    def tearDown(self):
        sys.modules.pop("utils.register", None)
        self._module_stack.close()

    def test_run_allows_hk_region_to_reach_email_stage(self):
        _FakeSession.next_trace_text = "fl=29f17\nloc=HK\n"

        with patch.object(self.register, "_skip_net_check", return_value=False):
            with patch.object(self.register, "get_email_and_token", return_value=("", "")) as email_mock:
                with redirect_stdout(io.StringIO()) as stdout:
                    result = self.register.run("http://127.0.0.1:7890")

        self.assertEqual((None, None), result)
        email_mock.assert_called_once()
        self.assertNotIn("代理所在地不支持 OpenAI (HK)", stdout.getvalue())

    def test_run_blocks_cn_region_before_email_stage(self):
        _FakeSession.next_trace_text = "fl=29f17\nloc=CN\n"

        with patch.object(self.register, "_skip_net_check", return_value=False):
            with patch.object(self.register, "get_email_and_token", return_value=("", "")) as email_mock:
                with redirect_stdout(io.StringIO()) as stdout:
                    result = self.register.run("http://127.0.0.1:7890")

        self.assertEqual((None, None), result)
        email_mock.assert_not_called()
        self.assertIn("代理所在地不支持 OpenAI (CN)", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
