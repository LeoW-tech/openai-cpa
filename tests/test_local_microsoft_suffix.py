import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch

try:
    import curl_cffi  # noqa: F401
except Exception:
    fake_requests_module = types.SimpleNamespace(post=None, get=None)
    sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module)

from utils import config as cfg
from utils.email_providers.local_microsoft_service import LocalMicrosoftService


class LocalMicrosoftSuffixTests(unittest.TestCase):
    def setUp(self):
        self.service = LocalMicrosoftService()

    def _patch_cfg(self, **kwargs):
        defaults = {
            "LOCAL_MS_SUFFIX_MODE": "fixed",
            "LOCAL_MS_SUFFIX_LEN_MIN": 8,
            "LOCAL_MS_SUFFIX_LEN_MAX": 8,
            "LOCAL_MS_ENABLE_FISSION": False,
            "LOCAL_MS_MASTER_EMAIL": "",
            "LOCAL_MS_CLIENT_ID": "",
            "LOCAL_MS_REFRESH_TOKEN": "",
            "LOCAL_MS_POOL_FISSION": False,
        }
        defaults.update(kwargs)
        stack = ExitStack()
        for key, value in defaults.items():
            stack.enter_context(patch.object(cfg, key, value))
        return stack

    def test_fixed_mode_uses_min_length_hex(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="fixed",
            LOCAL_MS_SUFFIX_LEN_MIN=12,
            LOCAL_MS_SUFFIX_LEN_MAX=24,
        ):
            suffix = self.service.generate_suffix_v2(user_part="alpha")
        self.assertEqual(12, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_range_mode_uses_random_length_within_bounds(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=16,
        ):
            with patch("utils.email_providers.local_microsoft_service.random.randint", return_value=15):
                suffix = self.service.generate_suffix_v2(user_part="alpha")
        self.assertEqual(15, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_mystic_mode_is_alnum_and_respects_target_length(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="mystic",
            LOCAL_MS_SUFFIX_LEN_MIN=20,
            LOCAL_MS_SUFFIX_LEN_MAX=20,
        ):
            suffix = self.service.generate_suffix_v2(user_part="alpha")
        self.assertEqual(20, len(suffix))
        self.assertRegex(suffix, r"^[a-z0-9]+$")

    def test_invalid_mode_falls_back_to_fixed_mode(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="invalid-mode",
            LOCAL_MS_SUFFIX_LEN_MIN=11,
            LOCAL_MS_SUFFIX_LEN_MAX=22,
        ):
            suffix = self.service.generate_suffix_v2(user_part="alpha")
        self.assertEqual(11, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_suffix_bounds_normalize_when_max_less_than_min(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=20,
            LOCAL_MS_SUFFIX_LEN_MAX=8,
        ):
            suffix = self.service.generate_suffix_v2(user_part="alpha")
        self.assertEqual(20, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_suffix_returns_empty_when_local_part_has_no_room(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=32,
        ):
            suffix = self.service.generate_suffix_v2(user_part=("a" * 63))
        self.assertEqual("", suffix)

    def test_suffix_uses_remaining_space_even_when_below_minimum_length(self):
        with self._patch_cfg(
            LOCAL_MS_SUFFIX_MODE="fixed",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=8,
        ):
            suffix = self.service.generate_suffix_v2(user_part=("a" * 61))
        self.assertEqual(2, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_manual_fission_uses_configured_suffix_mode(self):
        with self._patch_cfg(
            LOCAL_MS_ENABLE_FISSION=True,
            LOCAL_MS_MASTER_EMAIL="seed@outlook.com",
            LOCAL_MS_CLIENT_ID="client",
            LOCAL_MS_REFRESH_TOKEN="rt",
            LOCAL_MS_SUFFIX_MODE="fixed",
            LOCAL_MS_SUFFIX_LEN_MIN=10,
            LOCAL_MS_SUFFIX_LEN_MAX=10,
        ):
            mailbox = self.service.get_unused_mailbox()
        self.assertIsNotNone(mailbox)
        self.assertIn("+", mailbox["email"])
        local_part = mailbox["email"].split("@")[0]
        suffix = local_part.split("+", 1)[1]
        self.assertEqual(10, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_manual_fission_returns_none_when_suffix_cannot_fit(self):
        master_email = ("a" * 63) + "@outlook.com"
        with self._patch_cfg(
            LOCAL_MS_ENABLE_FISSION=True,
            LOCAL_MS_MASTER_EMAIL=master_email,
            LOCAL_MS_CLIENT_ID="client",
            LOCAL_MS_REFRESH_TOKEN="rt",
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=32,
        ):
            mailbox = self.service.get_unused_mailbox()
        self.assertIsNone(mailbox)

    def test_pool_fission_uses_configured_suffix_mode(self):
        pool_mailboxes = [{
            "id": 100,
            "email": "seed@outlook.com",
            "retry_master": 0,
            "client_id": "pool-client",
            "refresh_token": "pool-rt",
        }]
        with self._patch_cfg(
            LOCAL_MS_POOL_FISSION=True,
            LOCAL_MS_SUFFIX_MODE="fixed",
            LOCAL_MS_SUFFIX_LEN_MIN=9,
            LOCAL_MS_SUFFIX_LEN_MAX=9,
        ):
            with patch(
                "utils.email_providers.local_microsoft_service.db_manager.get_mailboxes_for_pool_fission",
                return_value=pool_mailboxes,
            ):
                mailbox = self.service.get_unused_mailbox()
        self.assertIsNotNone(mailbox)
        self.assertIn("+", mailbox["email"])
        local_part = mailbox["email"].split("@")[0]
        suffix = local_part.split("+", 1)[1]
        self.assertEqual(9, len(suffix))
        self.assertRegex(suffix, r"^[0-9a-f]+$")

    def test_pool_fission_retry_master_still_returns_alias(self):
        pool_mailboxes = [{
            "id": 100,
            "email": "seed@outlook.com",
            "retry_master": 1,
            "client_id": "pool-client",
            "refresh_token": "pool-rt",
        }]
        with self._patch_cfg(
            LOCAL_MS_POOL_FISSION=True,
            LOCAL_MS_SUFFIX_MODE="fixed",
            LOCAL_MS_SUFFIX_LEN_MIN=9,
            LOCAL_MS_SUFFIX_LEN_MAX=9,
        ):
            with patch(
                "utils.email_providers.local_microsoft_service.db_manager.get_mailboxes_for_pool_fission",
                return_value=pool_mailboxes,
            ):
                mailbox = self.service.get_unused_mailbox()
        self.assertIsNotNone(mailbox)
        self.assertIn("+", mailbox["email"])
        self.assertEqual("seed@outlook.com", mailbox["master_email"])
        self.assertFalse(mailbox["is_raw_trial"])

    def test_pool_fission_skips_unusable_mailbox_and_uses_next_candidate(self):
        master_email = ("a" * 63) + "@outlook.com"
        pool_mailboxes = [
            {
                "id": 101,
                "email": master_email,
                "retry_master": 1,
                "client_id": "pool-client",
                "refresh_token": "pool-rt",
            },
            {
                "id": 102,
                "email": "usable@outlook.com",
                "retry_master": 0,
                "client_id": "pool-client-2",
                "refresh_token": "pool-rt-2",
            },
        ]
        with self._patch_cfg(
            LOCAL_MS_POOL_FISSION=True,
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=32,
        ):
            with patch(
                "utils.email_providers.local_microsoft_service.db_manager.get_mailboxes_for_pool_fission",
                return_value=pool_mailboxes,
            ):
                mailbox = self.service.get_unused_mailbox()
        self.assertIsNotNone(mailbox)
        self.assertTrue(mailbox["email"].startswith("usable+"))
        self.assertEqual("usable@outlook.com", mailbox["master_email"])

    def test_pool_fission_returns_none_when_all_candidates_are_unusable(self):
        master_email = ("a" * 63) + "@outlook.com"
        pool_mailboxes = [
            {
                "id": 101,
                "email": master_email,
                "retry_master": 1,
                "client_id": "pool-client",
                "refresh_token": "pool-rt",
            },
            {
                "id": 102,
                "email": master_email.replace("@", "b@"),
                "retry_master": 0,
                "client_id": "pool-client-2",
                "refresh_token": "pool-rt-2",
            },
        ]
        with self._patch_cfg(
            LOCAL_MS_POOL_FISSION=True,
            LOCAL_MS_SUFFIX_MODE="range",
            LOCAL_MS_SUFFIX_LEN_MIN=8,
            LOCAL_MS_SUFFIX_LEN_MAX=32,
        ):
            with patch(
                "utils.email_providers.local_microsoft_service.db_manager.get_mailboxes_for_pool_fission",
                return_value=pool_mailboxes,
            ):
                mailbox = self.service.get_unused_mailbox()
        self.assertIsNone(mailbox)


if __name__ == "__main__":
    unittest.main()
