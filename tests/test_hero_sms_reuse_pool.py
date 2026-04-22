import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(get=None, post=None, Session=object, Response=object)
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module, CurlMime=object)


class HeroSmsReusePoolTests(unittest.TestCase):
    def _reload_hero_sms(self, saved_state=None):
        import utils.integrations.hero_sms as hero_sms

        with patch.object(hero_sms.db_manager, "get_sys_kv", return_value=saved_state):
            with patch.object(hero_sms.db_manager, "set_sys_kv"):
                return importlib.reload(hero_sms)

    def test_reuse_layer_is_disabled_even_if_config_requests_it(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_PHONE", True, create=True):
            self.assertFalse(hero_sms._hero_sms_reuse_enabled())

    def test_reuse_snapshot_stays_empty(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        hero_sms._hero_sms_reuse_set("reuse-1", "+6699990000", "dr", 52)
        hero_sms._hero_sms_reuse_touch("reuse-1", increase=True)
        hero_sms._hero_sms_confirm_reuse_usage("reuse-1")
        snapshot = hero_sms.get_hero_sms_reuse_pool_snapshot()
        self.assertEqual({"entries": [], "updated_at": 0.0}, snapshot)

    def test_reuse_get_always_returns_empty(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        self.assertEqual(("", "", 0), hero_sms._hero_sms_reuse_get("dr", 52))

    def test_reuse_storage_health_is_ok_when_layer_disabled(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        self.assertEqual({"ok": True, "scope": "system_kv", "reason": ""}, hero_sms.get_hero_sms_reuse_storage_health())

    def test_verify_phone_ignores_reuse_setting_and_goes_direct_to_new_purchase(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()

        with patch.object(hero_sms.cfg, "HERO_SMS_ENABLED", True, create=True):
            with patch.object(hero_sms.cfg, "HERO_SMS_API_KEY", "demo-key", create=True):
                with patch.object(hero_sms.cfg, "HERO_SMS_REUSE_PHONE", True, create=True):
                    with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                        with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                            with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                                with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                                    with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                        with patch.object(hero_sms, "_hero_sms_get_number", return_value=("", "", "NO_NUMBERS")) as get_number:
                                            with patch.object(hero_sms, "_sleep_interruptible", return_value=False):
                                                ok, reason = hero_sms._try_verify_phone_via_hero_sms(
                                                    session,
                                                    proxies=None,
                                                    run_ctx={},
                                                )

        self.assertFalse(ok)
        self.assertEqual("取号失败: NO_NUMBERS", reason)
        get_number.assert_called_once()

    def test_verify_phone_persists_structured_phone_fields_on_success(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()
        run_ctx = {"analytics_attempt_id": 88}

        class _Resp:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = json.dumps(self._payload)

            def json(self):
                return self._payload

        with patch.object(hero_sms.cfg, "HERO_SMS_ENABLED", True, create=True):
            with patch.object(hero_sms.cfg, "HERO_SMS_API_KEY", "demo-key", create=True):
                with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                    with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                        with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                            with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                                with patch.object(hero_sms, "_hero_sms_reuse_get", return_value=("", "", 0)):
                                    with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                        with patch.object(hero_sms, "_hero_sms_get_number", return_value=("act-1", "+85251234567", "")):
                                            with patch.object(hero_sms, "_hero_sms_mark_ready"):
                                                with patch.object(hero_sms, "_hero_sms_poll_code", return_value="112233"):
                                                    with patch.object(hero_sms, "_post_with_retry", side_effect=[
                                                        _Resp(200, {"success": True}),
                                                        _Resp(200, {"continue_url": "https://auth.openai.com/consent"}),
                                                    ]):
                                                        with patch.object(hero_sms.registration_history, "patch_attempt") as patch_attempt:
                                                            ok, next_url = hero_sms._try_verify_phone_via_hero_sms(
                                                                session,
                                                                proxies=None,
                                                                run_ctx=run_ctx,
                                                            )

        self.assertTrue(ok)
        self.assertEqual("https://auth.openai.com/consent", next_url)
        patched = {}
        for call in patch_attempt.call_args_list:
            patched.update(call.kwargs)
        self.assertEqual("+85251234567", patched["phone_number_full"])
        self.assertEqual("+85251234567", patched["phone_number_e164"])
        self.assertEqual("+852", patched["phone_country_calling_code"])
        self.assertEqual("HK", patched["phone_country_iso"])
        self.assertEqual("Hong Kong", patched["phone_country_name"])
        self.assertEqual("51234567", patched["phone_national_number"])
        self.assertEqual("act-1", patched["phone_activation_id"])
        self.assertEqual("hero_sms", patched["phone_bind_provider"])
        self.assertEqual("otp_validated", patched["phone_bind_stage"])
        self.assertEqual(1, patched["phone_bind_attempted_flag"])
        self.assertEqual(1, patched["phone_bind_success_flag"])

    def test_verify_phone_persists_phone_fields_even_when_validation_fails(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()
        run_ctx = {"analytics_attempt_id": 99}

        class _Resp:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = json.dumps(self._payload)

            def json(self):
                return self._payload

        with patch.object(hero_sms.cfg, "HERO_SMS_ENABLED", True, create=True):
            with patch.object(hero_sms.cfg, "HERO_SMS_API_KEY", "demo-key", create=True):
                with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                    with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                        with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                            with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                                with patch.object(hero_sms, "_hero_sms_reuse_get", return_value=("", "", 0)):
                                    with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                        with patch.object(hero_sms, "_hero_sms_get_number", return_value=("act-2", "+819012345678", "")):
                                            with patch.object(hero_sms, "_hero_sms_mark_ready"):
                                                with patch.object(hero_sms, "_hero_sms_poll_code", return_value="112233"):
                                                    with patch.object(hero_sms, "_post_with_retry", side_effect=[
                                                        _Resp(200, {"success": True}),
                                                        _Resp(400, {"error": "bad otp"}),
                                                    ]):
                                                        with patch.object(hero_sms.registration_history, "patch_attempt") as patch_attempt:
                                                            ok, reason = hero_sms._try_verify_phone_via_hero_sms(
                                                                session,
                                                                proxies=None,
                                                                run_ctx=run_ctx,
                                                            )

        self.assertFalse(ok)
        self.assertIn("手机验证码校验失败", reason)
        patched = {}
        for call in patch_attempt.call_args_list:
            patched.update(call.kwargs)
        self.assertEqual("+819012345678", patched["phone_number_full"])
        self.assertEqual("+81", patched["phone_country_calling_code"])
        self.assertEqual("JP", patched["phone_country_iso"])
        self.assertEqual("Japan", patched["phone_country_name"])
        self.assertEqual("failed", patched["phone_bind_stage"])
        self.assertEqual(1, patched["phone_bind_attempted_flag"])
        self.assertEqual(1, patched["phone_bind_failed_flag"])
        self.assertEqual(0, patched["phone_bind_success_flag"])
        self.assertIn("手机验证码校验失败", patched["phone_bind_failure_reason"])

    def test_verify_phone_succeeds_even_when_history_writes_raise(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()
        run_ctx = {"analytics_attempt_id": 101}

        class _Resp:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = json.dumps(self._payload)

            def json(self):
                return self._payload

        with patch.object(hero_sms.cfg, "HERO_SMS_ENABLED", True, create=True):
            with patch.object(hero_sms.cfg, "HERO_SMS_API_KEY", "demo-key", create=True):
                with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                    with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                        with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                            with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                                with patch.object(hero_sms, "_hero_sms_reuse_get", return_value=("", "", 0)):
                                    with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                        with patch.object(hero_sms, "_hero_sms_get_number", return_value=("act-best-effort", "+85251234567", "")):
                                            with patch.object(hero_sms, "_hero_sms_mark_ready"):
                                                with patch.object(hero_sms, "_hero_sms_poll_code", return_value="112233"):
                                                    with patch.object(hero_sms, "_post_with_retry", side_effect=[
                                                        _Resp(200, {"success": True}),
                                                        _Resp(200, {"continue_url": "https://auth.openai.com/consent"}),
                                                    ]):
                                                        with patch.object(hero_sms.registration_history, "patch_attempt", side_effect=RuntimeError("patch-boom")):
                                                            with patch.object(hero_sms.registration_history, "record_attempt_event", side_effect=RuntimeError("event-boom")):
                                                                ok, next_url = hero_sms._try_verify_phone_via_hero_sms(
                                                                    session,
                                                                    proxies=None,
                                                                    run_ctx=run_ctx,
                                                                )

        self.assertTrue(ok)
        self.assertEqual("https://auth.openai.com/consent", next_url)

    def test_verify_phone_failure_path_is_preserved_when_history_writes_raise(self):
        hero_sms = self._reload_hero_sms(saved_state=None)
        session = object()
        run_ctx = {"analytics_attempt_id": 102}

        class _Resp:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = json.dumps(self._payload)

            def json(self):
                return self._payload

        with patch.object(hero_sms.cfg, "HERO_SMS_ENABLED", True, create=True):
            with patch.object(hero_sms.cfg, "HERO_SMS_API_KEY", "demo-key", create=True):
                with patch.object(hero_sms, "hero_sms_get_balance", return_value=(3.5, "")):
                    with patch.object(hero_sms, "_hero_sms_resolve_service_code", return_value="dr"):
                        with patch.object(hero_sms, "_hero_sms_resolve_country_id", return_value=52):
                            with patch.object(hero_sms, "_hero_sms_pick_country_id", return_value=52):
                                with patch.object(hero_sms, "_hero_sms_reuse_get", return_value=("", "", 0)):
                                    with patch.object(hero_sms, "_hero_sms_max_tries", return_value=1):
                                        with patch.object(hero_sms, "_hero_sms_get_number", return_value=("act-best-effort-fail", "+85251234567", "")):
                                            with patch.object(hero_sms, "_hero_sms_mark_ready"):
                                                with patch.object(hero_sms, "_hero_sms_poll_code", return_value="112233"):
                                                    with patch.object(hero_sms, "_post_with_retry", side_effect=[
                                                        _Resp(200, {"success": True}),
                                                        _Resp(400, {"error": "bad otp"}),
                                                    ]):
                                                        with patch.object(hero_sms.registration_history, "patch_attempt", side_effect=RuntimeError("patch-boom")):
                                                            with patch.object(hero_sms.registration_history, "record_attempt_event", side_effect=RuntimeError("event-boom")):
                                                                ok, reason = hero_sms._try_verify_phone_via_hero_sms(
                                                                    session,
                                                                    proxies=None,
                                                                    run_ctx=run_ctx,
                                                                )

        self.assertFalse(ok)
        self.assertIn("手机验证码校验失败", reason)


if __name__ == "__main__":
    unittest.main()
