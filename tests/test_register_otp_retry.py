import ast
import importlib
import io
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import call, patch


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class RegisterOtpRetryTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(
            get=None,
            post=None,
            Session=object,
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

    def test_validate_email_otp_retries_after_first_401_and_succeeds_with_new_code(self):
        responses = [
            _FakeResponse(401, {"detail": "stale code"}),
            _FakeResponse(200, {"continue_url": "https://auth.openai.com/success"}),
        ]
        processed_mail_ids = {"old-message"}

        with patch.object(self.register, "_post_with_retry", side_effect=responses) as post_mock:
            with patch.object(self.register, "get_oai_code", return_value="654321") as code_mock:
                with patch.object(self.register, "generate_payload", return_value="retry-sentinel"):
                    with patch.object(self.register.time, "sleep") as sleep_mock:
                        with redirect_stdout(io.StringIO()):
                            resp = self.register._validate_email_otp_with_401_backoff(
                                session=object(),
                                did="did-1",
                                ctx={"flow": "ctx"},
                                proxy="http://127.0.0.1:7890",
                                user_agent="ua",
                                referer="https://auth.openai.com/email-verification",
                                email="demo@example.com",
                                email_jwt='{"email":"demo@example.com"}',
                                processed_mail_ids=processed_mail_ids,
                                code="123456",
                                proxies={"https": "http://127.0.0.1:7890"},
                                label="接管验证码",
                            )

        self.assertEqual(200, resp.status_code)
        sleep_mock.assert_called_once_with(10)
        code_mock.assert_called_once_with(
            "demo@example.com",
            jwt='{"email":"demo@example.com"}',
            proxies={"https": "http://127.0.0.1:7890"},
            processed_mail_ids=processed_mail_ids,
            max_attempts=1,
        )
        self.assertEqual("123456", post_mock.call_args_list[0].kwargs["json_body"]["code"])
        self.assertEqual("654321", post_mock.call_args_list[1].kwargs["json_body"]["code"])

    def test_validate_email_otp_stops_after_three_401_backoffs(self):
        responses = [
            _FakeResponse(401, {"detail": "first"}),
            _FakeResponse(401, {"detail": "second"}),
            _FakeResponse(401, {"detail": "third"}),
            _FakeResponse(401, {"detail": "fourth"}),
        ]

        with patch.object(self.register, "_post_with_retry", side_effect=responses):
            with patch.object(self.register, "get_oai_code", side_effect=["222222", "333333", "444444"]) as code_mock:
                with patch.object(self.register, "generate_payload", return_value="retry-sentinel"):
                    with patch.object(self.register.time, "sleep") as sleep_mock:
                        with redirect_stdout(io.StringIO()):
                            resp = self.register._validate_email_otp_with_401_backoff(
                                session=object(),
                                did="did-2",
                                ctx={"flow": "ctx"},
                                proxy="http://127.0.0.1:7890",
                                user_agent="ua",
                                referer="https://auth.openai.com/email-verification",
                                email="demo@example.com",
                                email_jwt='{"email":"demo@example.com"}',
                                processed_mail_ids=set(),
                                code="111111",
                                proxies={"https": "http://127.0.0.1:7890"},
                                label="普通验证码",
                            )

        self.assertEqual(401, resp.status_code)
        self.assertEqual([call(10), call(20), call(30)], sleep_mock.call_args_list)
        self.assertEqual(3, code_mock.call_count)

    def test_validate_email_otp_succeeds_on_third_backoff_after_missing_new_codes(self):
        responses = [
            _FakeResponse(401, {"detail": "stale"}),
            _FakeResponse(200, {"continue_url": "https://auth.openai.com/workspace"}),
        ]

        with patch.object(self.register, "_post_with_retry", side_effect=responses) as post_mock:
            with patch.object(self.register, "get_oai_code", side_effect=["", "", "888888"]) as code_mock:
                with patch.object(self.register, "generate_payload", return_value="retry-sentinel"):
                    with patch.object(self.register.time, "sleep") as sleep_mock:
                        with redirect_stdout(io.StringIO()):
                            resp = self.register._validate_email_otp_with_401_backoff(
                                session=object(),
                                did="did-3",
                                ctx={"flow": "ctx"},
                                proxy="http://127.0.0.1:7890",
                                user_agent="ua",
                                referer="https://auth.openai.com/email-verification",
                                email="demo@example.com",
                                email_jwt='{"email":"demo@example.com"}',
                                processed_mail_ids=set(),
                                code="777777",
                                proxies={"https": "http://127.0.0.1:7890"},
                                label="OAuth 验证码",
                            )

        self.assertEqual(200, resp.status_code)
        self.assertEqual([call(10), call(20), call(30)], sleep_mock.call_args_list)
        self.assertEqual(3, code_mock.call_count)
        self.assertEqual(2, post_mock.call_count)
        self.assertEqual("888888", post_mock.call_args_list[-1].kwargs["json_body"]["code"])

    def test_validate_email_otp_does_not_retry_non_401_failure(self):
        with patch.object(self.register, "_post_with_retry", return_value=_FakeResponse(400, {"detail": "bad request"})):
            with patch.object(self.register, "get_oai_code") as code_mock:
                with patch.object(self.register.time, "sleep") as sleep_mock:
                    with redirect_stdout(io.StringIO()):
                        resp = self.register._validate_email_otp_with_401_backoff(
                            session=object(),
                            did="did-4",
                            ctx={"flow": "ctx"},
                            proxy="http://127.0.0.1:7890",
                            user_agent="ua",
                            referer="https://auth.openai.com/email-verification",
                            email="demo@example.com",
                            email_jwt='{"email":"demo@example.com"}',
                            processed_mail_ids=set(),
                            code="123123",
                            proxies={"https": "http://127.0.0.1:7890"},
                            label="二次安全验证",
                        )

        self.assertEqual(400, resp.status_code)
        code_mock.assert_not_called()
        sleep_mock.assert_not_called()

    def test_run_uses_shared_otp_retry_helper_in_four_validate_call_sites(self):
        source = Path("/Users/meilinwang/Projects/openai-cpa-Public/utils/register.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        run_fn = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        helper_calls = [
            node for node in ast.walk(run_fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_validate_email_otp_with_401_backoff"
        ]

        self.assertEqual(4, len(helper_calls))


if __name__ == "__main__":
    unittest.main()
