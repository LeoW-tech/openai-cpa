import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault(
    "utils.email_providers.mail_service",
    types.SimpleNamespace(
        mask_email=lambda value, force_mask=False: value,
        _extract_otp_code_from_email_parts=lambda **kwargs: "",
    ),
)

from utils.email_providers.postman_center import PostmanFleet


class _FakeThread:
    created = []

    def __init__(self, target=None, args=None, daemon=None):
        self.target = target
        self.args = args or ()
        self.daemon = daemon
        self.started = False
        _FakeThread.created.append(self)

    def start(self):
        self.started = True


class PostmanCenterLifecycleTests(unittest.TestCase):
    def test_same_master_mailbox_can_stop_and_restart_listener_without_stale_signal(self):
        fleet = PostmanFleet()
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
        }
        first_service = object()
        second_service = object()

        _FakeThread.created = []
        with patch("utils.email_providers.postman_center.threading.Thread", _FakeThread):
            fleet.ensure_mailbox_listener(first_service, mailbox)
            first_event = fleet.postman_signals["user@example.com"]

            fleet.stop_mailbox_listener("user@example.com")
            self.assertTrue(first_event.is_set())
            self.assertNotIn("user@example.com", fleet.postman_signals)

            fleet.ensure_mailbox_listener(second_service, mailbox)
            second_event = fleet.postman_signals["user@example.com"]

        self.assertIsNot(first_event, second_event)
        self.assertFalse(second_event.is_set())
        self.assertEqual(2, len(_FakeThread.created))
        self.assertTrue(all(thread.started for thread in _FakeThread.created))


if __name__ == "__main__":
    unittest.main()
