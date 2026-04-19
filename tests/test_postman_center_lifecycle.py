import importlib
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch


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
    def setUp(self):
        self._module_stack = ExitStack()
        self._module_stack.enter_context(
            patch.dict(
                sys.modules,
                {
                    "utils.email_providers.mail_service": types.SimpleNamespace(
                        mask_email=lambda value, force_mask=False: value,
                        _extract_otp_code_from_email_parts=lambda **kwargs: "",
                    ),
                },
            )
        )
        sys.modules.pop("utils.email_providers.postman_center", None)
        import utils.email_providers.postman_center as postman_center

        self.postman_center = importlib.reload(postman_center)
        self.PostmanFleet = self.postman_center.PostmanFleet

    def tearDown(self):
        sys.modules.pop("utils.email_providers.postman_center", None)
        self._module_stack.close()

    def test_same_master_mailbox_reuses_listener_until_ref_count_reaches_zero(self):
        fleet = self.PostmanFleet()
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
        }
        first_service = object()
        second_service = object()

        _FakeThread.created = []
        with patch.object(self.postman_center.threading, "Thread", _FakeThread):
            first_lease = fleet.acquire_mailbox_listener(first_service, mailbox)
            second_lease = fleet.acquire_mailbox_listener(second_service, mailbox)

            registry_entry = fleet.listener_registry["user@example.com"]
            stop_event = registry_entry["stop_event"]

            self.assertTrue(first_lease["created"])
            self.assertFalse(second_lease["created"])
            self.assertEqual(2, registry_entry["ref_count"])
            self.assertEqual(1, len(_FakeThread.created))
            self.assertTrue(_FakeThread.created[0].started)

            fleet.release_mailbox_listener("user@example.com")
            self.assertIn("user@example.com", fleet.listener_registry)
            self.assertEqual(1, fleet.listener_registry["user@example.com"]["ref_count"])
            self.assertFalse(stop_event.is_set())

            fleet.release_mailbox_listener("user@example.com")

        self.assertTrue(stop_event.is_set())
        self.assertNotIn("user@example.com", fleet.listener_registry)


if __name__ == "__main__":
    unittest.main()
