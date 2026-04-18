import importlib
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch


class RegisterPendingTokenHistoryTests(unittest.TestCase):
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
                    "utils.auth_core": types.SimpleNamespace(generate_payload=lambda *args, **kwargs: {}),
                    "utils.region_policy": types.SimpleNamespace(is_openai_region_blocked=lambda *args, **kwargs: False),
                },
            )
        )
        sys.modules.pop("utils.register", None)

    def tearDown(self):
        sys.modules.pop("utils.register", None)
        self._module_stack.close()

    def _reload_register(self):
        import utils.register as register

        return importlib.reload(register)

    def test_record_pending_account_registration_only_writes_history(self):
        register = self._reload_register()
        run_ctx = {"analytics_attempt_id": 66}
        demo_password = "unit-test-pass"

        with patch.object(register, "_history_patch") as history_patch:
            with patch.object(register, "_history_event") as history_event:
                with patch.object(register, "db_manager", create=True) as db_manager:
                    register._record_pending_account_registration(
                        email="demo@example.com",
                        password=demo_password,
                        run_ctx=run_ctx,
                    )

        db_manager.save_account_to_db.assert_not_called()
        history_patch.assert_called_once_with(run_ctx, account_registered_flag=1)
        history_event.assert_called_once()
        self.assertEqual(
            "account_registered_pending_token",
            history_event.call_args.kwargs["event_type"],
        )


if __name__ == "__main__":
    unittest.main()
