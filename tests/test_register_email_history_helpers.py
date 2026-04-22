import importlib
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None

    def close(self):
        return None


class RegisterEmailHistoryHelperTests(unittest.TestCase):
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

    def _assert_email_history_patch(self, email: str, expected_local: str, expected_domain: str, expected_master: str):
        captured_fields = {}

        def capture_patch(run_ctx, **fields):
            captured_fields.update(fields)

        with patch.object(self.register, "_skip_net_check", return_value=True):
            with patch.object(self.register, "get_email_and_token", return_value=(email, '{"email":"%s"}' % email)):
                with patch.object(self.register, "_history_patch", side_effect=capture_patch):
                    with patch.object(self.register, "_history_event", side_effect=RuntimeError("stop-after-patch")):
                        with self.assertRaises(RuntimeError) as ctx:
                            self.register.run("http://127.0.0.1:7890", run_ctx={"analytics_attempt_id": 1})

        self.assertEqual("stop-after-patch", str(ctx.exception))
        self.assertEqual(email, captured_fields["email_full"])
        self.assertEqual(expected_local, captured_fields["email_local_part"])
        self.assertEqual(expected_domain, captured_fields["email_domain"])
        self.assertEqual(expected_master, captured_fields["master_email"])

    def test_run_patches_alias_email_fields_before_main_flow(self):
        self._assert_email_history_patch(
            email="user+alias@example.com",
            expected_local="user+alias",
            expected_domain="example.com",
            expected_master="user@example.com",
        )

    def test_run_patches_plain_email_fields_before_main_flow(self):
        self._assert_email_history_patch(
            email="plain@example.com",
            expected_local="plain",
            expected_domain="example.com",
            expected_master="plain@example.com",
        )


if __name__ == "__main__":
    unittest.main()
