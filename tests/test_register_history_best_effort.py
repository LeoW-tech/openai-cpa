import importlib
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class RegisterHistoryBestEffortTests(unittest.TestCase):
    def setUp(self):
        fake_requests_module = types.SimpleNamespace(Session=object)
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
                    "curl_cffi": types.SimpleNamespace(requests=fake_requests_module),
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        get_email_and_token=lambda *args, **kwargs: ("demo@example.com", "jwt-demo"),
                        get_oai_code=lambda *args, **kwargs: "112233",
                        mask_email=lambda value, force_mask=False: value,
                        record_ms_snapshot=lambda *args, **kwargs: None,
                    ),
                    "utils.integrations.hero_sms": types.SimpleNamespace(
                        _try_verify_phone_via_hero_sms=lambda *args, **kwargs: (False, "")
                    ),
                    "utils.auth_core": types.SimpleNamespace(
                        generate_payload=lambda *args, **kwargs: {},
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

    def test_history_helpers_swallow_registration_history_write_failures(self):
        run_ctx = {"analytics_attempt_id": 66}
        with patch.object(self.register.registration_history, "record_attempt_event", side_effect=RuntimeError("event-boom")):
            self.register._history_event(run_ctx, event_type="demo")
        with patch.object(self.register.registration_history, "patch_attempt", side_effect=RuntimeError("patch-boom")):
            self.register._history_patch(run_ctx, demo=1)

    def test_create_account_with_history_returns_response_when_history_writes_fail(self):
        run_ctx = {"analytics_attempt_id": 66}
        fake_resp = _FakeResponse(200, {"continue_url": "https://auth.openai.com/workspace"})
        with patch.object(self.register, "_post_with_retry", return_value=fake_resp):
            with patch.object(self.register.registration_history, "record_attempt_event", side_effect=RuntimeError("event-boom")):
                with patch.object(self.register.registration_history, "patch_attempt", side_effect=RuntimeError("patch-boom")):
                    resp = self.register._create_account_with_history(
                        session=object(),
                        headers={},
                        user_info={"name": "Demo", "birthdate": "1999-01-01"},
                        proxies=None,
                        run_ctx=run_ctx,
                    )

        self.assertIs(fake_resp, resp)

    def test_submit_callback_with_history_returns_token_when_history_writes_fail(self):
        run_ctx = {"analytics_attempt_id": 66}
        with patch.object(self.register, "submit_callback_url", return_value='{"email":"demo@example.com"}'):
            with patch.object(self.register.registration_history, "record_attempt_event", side_effect=RuntimeError("event-boom")):
                with patch.object(self.register.registration_history, "patch_attempt", side_effect=RuntimeError("patch-boom")):
                    token_json = self.register._submit_callback_with_history(
                        callback_url="http://localhost/?code=abc&state=demo",
                        expected_state="demo",
                        code_verifier="verifier",
                        proxies=None,
                        run_ctx=run_ctx,
                    )

        self.assertEqual('{"email":"demo@example.com"}', token_json)


if __name__ == "__main__":
    unittest.main()
