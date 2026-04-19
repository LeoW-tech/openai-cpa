import ast
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class RegisterOtpRetryRemovalTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(
            get=None,
            post=None,
            Session=object,
        )
        self._module_patch = patch.dict(
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
        self._module_patch.start()
        sys.modules.pop("utils.register", None)
        import utils.register as register

        self.register = importlib.reload(register)
        self.source = Path(self.register.__file__).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def tearDown(self):
        sys.modules.pop("utils.register", None)
        self._module_patch.stop()

    def test_register_source_no_longer_defines_401_backoff_helper(self):
        helper_names = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
        }

        helper_name = "_validate_email_otp_with_" + "401_backoff"
        self.assertNotIn(helper_name, helper_names)

    def test_run_uses_four_direct_email_otp_validate_calls(self):
        run_fn = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )

        validate_calls = [
            node for node in ast.walk(run_fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_post_with_retry"
            and any(
                isinstance(arg, ast.Constant)
                and arg.value == "https://auth.openai.com/api/accounts/email-otp/validate"
                for arg in node.args
            )
        ]

        self.assertEqual(4, len(validate_calls))

    def test_register_source_no_longer_contains_401_backoff_logs(self):
        forbidden_snippets = [
            "首次校验返回 401，进入 401 " + "退避补救",
            "退避" + "补救，等待",
            "补救未获取到新" + "验证码",
            "补救提交" + "结果",
        ]

        for snippet in forbidden_snippets:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, self.source)

    def test_register_source_no_longer_updates_401_retry_counter(self):
        counter_name = "email_otp_" + "401_retry_count"
        self.assertNotIn(counter_name, self.source)


if __name__ == "__main__":
    unittest.main()
