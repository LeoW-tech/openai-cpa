import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(post=None, get=None, Response=object)
sys.modules.setdefault("curl_cffi", types.SimpleNamespace(requests=fake_requests_module))
sys.modules.setdefault(
    "utils.integrations.ai_service",
    types.SimpleNamespace(AIService=object),
)
sys.modules.setdefault(
    "utils.email_providers.gmail_service",
    types.SimpleNamespace(get_gmail_otp_via_oauth=lambda *args, **kwargs: ""),
)
sys.modules.setdefault(
    "utils.email_providers.duckmail_service",
    types.SimpleNamespace(DuckMailService=object),
)

from utils.email_providers.mail_service import _extract_otp_code, _poll_local_ms_for_oai_code_graph


class _AbuseStopService:
    def __init__(self):
        self.calls = 0

    def fetch_openai_messages(self, mailbox):
        self.calls += 1
        mailbox["_polling_stopped"] = "abuse_mode"
        return []


class _StaticMessageService:
    def __init__(self, message_batches):
        self._message_batches = list(message_batches)
        self.calls = 0

    def fetch_openai_messages(self, mailbox):
        index = min(self.calls, len(self._message_batches) - 1)
        self.calls += 1
        return self._message_batches[index]


def _graph_message(
    *,
    msg_id,
    received,
    subject,
    code,
    to_address,
    body_content=None,
    body_preview=None,
):
    return {
        "id": msg_id,
        "subject": subject,
        "from": {"emailAddress": {"address": "noreply@openai.com"}},
        "toRecipients": [{"emailAddress": {"address": to_address}}],
        "receivedDateTime": received,
        "bodyPreview": body_preview or f"Your ChatGPT code is {code}",
        "body": {"content": body_content or f"Your ChatGPT code is {code}"},
    }


class MailServiceAbuseModeTests(unittest.TestCase):
    def test_extract_otp_code_ignores_openai_template_css_digits(self):
        html = """
        <html>
          <head>
            <style>
              .top { color: #202123; }
              .main { color: #353740; }
            </style>
          </head>
          <body>
            <p>Enter this temporary verification code to continue:</p>
            <p><span>283329</span></p>
          </body>
        </html>
        """

        self.assertEqual("283329", _extract_otp_code(html))

    def test_extract_otp_code_preserves_subject_style_messages(self):
        self.assertEqual("344271", _extract_otp_code("Your ChatGPT code is 344271"))

    def test_extract_otp_code_prefers_semantic_match_over_first_six_digit(self):
        content = "Brand color 202123. Backup color 353740. Your ChatGPT code is 344271."

        self.assertEqual("344271", _extract_otp_code(content))

    def test_graph_poll_stops_immediately_after_mailbox_enters_abuse_mode(self):
        service = _AbuseStopService()
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 0,
        }

        with patch("utils.email_providers.mail_service.time.sleep") as sleep_mock:
            with redirect_stdout(io.StringIO()):
                code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=set(),
                    mail_state={},
                    max_attempts=5,
                )

        self.assertEqual("", code)
        self.assertEqual("abuse_mode", mailbox.get("_polling_stopped"))
        self.assertEqual(1, service.calls)
        sleep_mock.assert_not_called()

    def test_graph_poll_prefers_newest_matching_message(self):
        service = _StaticMessageService([
            [
                _graph_message(
                    msg_id="msg-new",
                    received="2026-04-17T10:00:05+00:00",
                    subject="Your ChatGPT code",
                    code="654321",
                    to_address="user+alias@example.com",
                ),
                _graph_message(
                    msg_id="msg-old",
                    received="2026-04-17T10:00:01+00:00",
                    subject="Your ChatGPT code",
                    code="123456",
                    to_address="user+alias@example.com",
                ),
            ]
        ])
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 1_760_400_000.0,
        }
        processed_mail_ids = set()
        mail_state = {}

        with patch("utils.email_providers.mail_service.time.sleep") as sleep_mock:
            with redirect_stdout(io.StringIO()):
                code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=processed_mail_ids,
                    mail_state=mail_state,
                    max_attempts=1,
                )

        self.assertEqual("654321", code)
        self.assertEqual({"msg-new"}, processed_mail_ids)
        self.assertEqual(
            1_776_420_005.0,
            mail_state["user+alias@example.com"]["local_microsoft"]["last_accepted_received_ts"],
        )
        sleep_mock.assert_not_called()

    def test_graph_poll_prefers_body_preview_over_html_template_digits(self):
        html = """
        <html>
          <head>
            <style>
              .top { color: #202123; }
              .main { color: #353740; }
            </style>
          </head>
          <body>
            <p>Enter this temporary verification code to continue:</p>
            <p><span>283329</span></p>
          </body>
        </html>
        """
        service = _StaticMessageService([
            [
                _graph_message(
                    msg_id="msg-preview",
                    received="2026-04-17T10:00:05+00:00",
                    subject="Your temporary OpenAI login code",
                    code="283329",
                    to_address="user+alias@example.com",
                    body_content=html,
                    body_preview="Enter this temporary verification code to continue:\n\n283329",
                )
            ]
        ])
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 1_760_400_000.0,
        }

        with patch("utils.email_providers.mail_service.time.sleep") as sleep_mock:
            with redirect_stdout(io.StringIO()):
                code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=set(),
                    mail_state={},
                    max_attempts=1,
                )

        self.assertEqual("283329", code)
        sleep_mock.assert_not_called()

    def test_graph_poll_does_not_reuse_same_message_or_fall_back_to_older_mail(self):
        service = _StaticMessageService([
            [
                _graph_message(
                    msg_id="msg-new",
                    received="2026-04-17T10:00:05+00:00",
                    subject="Your ChatGPT code",
                    code="654321",
                    to_address="user+alias@example.com",
                ),
                _graph_message(
                    msg_id="msg-old",
                    received="2026-04-17T10:00:01+00:00",
                    subject="Your ChatGPT code",
                    code="123456",
                    to_address="user+alias@example.com",
                ),
            ]
        ])
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 1_760_400_000.0,
        }
        processed_mail_ids = set()
        mail_state = {}

        with patch("utils.email_providers.mail_service.time.sleep"):
            with redirect_stdout(io.StringIO()):
                first_code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=processed_mail_ids,
                    mail_state=mail_state,
                    max_attempts=1,
                )
            with redirect_stdout(io.StringIO()):
                second_code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=processed_mail_ids,
                    mail_state=mail_state,
                    max_attempts=1,
                )

        self.assertEqual("654321", first_code)
        self.assertEqual("", second_code)
        self.assertEqual({"msg-new"}, processed_mail_ids)
        self.assertEqual(
            1_776_420_005.0,
            mail_state["user+alias@example.com"]["local_microsoft"]["last_accepted_received_ts"],
        )

    def test_graph_poll_accepts_later_message_after_previous_one_was_consumed(self):
        service = _StaticMessageService([
            [
                _graph_message(
                    msg_id="msg-current",
                    received="2026-04-17T10:00:01+00:00",
                    subject="Your ChatGPT code",
                    code="111111",
                    to_address="user+alias@example.com",
                )
            ],
            [
                _graph_message(
                    msg_id="msg-latest",
                    received="2026-04-17T10:00:07+00:00",
                    subject="Your ChatGPT code",
                    code="222222",
                    to_address="user+alias@example.com",
                ),
                _graph_message(
                    msg_id="msg-current",
                    received="2026-04-17T10:00:01+00:00",
                    subject="Your ChatGPT code",
                    code="111111",
                    to_address="user+alias@example.com",
                ),
            ],
        ])
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 1_760_400_000.0,
        }
        processed_mail_ids = set()
        mail_state = {}

        with patch("utils.email_providers.mail_service.time.sleep"):
            with redirect_stdout(io.StringIO()):
                first_code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=processed_mail_ids,
                    mail_state=mail_state,
                    max_attempts=1,
                )
            with redirect_stdout(io.StringIO()):
                second_code = _poll_local_ms_for_oai_code_graph(
                    ms_service=service,
                    target_email="user+alias@example.com",
                    mailbox_dict=mailbox,
                    processed_mail_ids=processed_mail_ids,
                    mail_state=mail_state,
                    max_attempts=1,
                )

        self.assertEqual("111111", first_code)
        self.assertEqual("222222", second_code)
        self.assertEqual({"msg-current", "msg-latest"}, processed_mail_ids)
        self.assertEqual(
            1_776_420_007.0,
            mail_state["user+alias@example.com"]["local_microsoft"]["last_accepted_received_ts"],
        )

    def test_graph_poll_does_not_accept_master_email_when_alias_is_missing(self):
        service = _StaticMessageService([
            [
                _graph_message(
                    msg_id="msg-master-only",
                    received="2026-04-17T10:00:05+00:00",
                    subject="Your ChatGPT code",
                    code="654321",
                    to_address="user@example.com",
                ),
            ]
        ])
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "assigned_at": 1_760_400_000.0,
        }

        with patch("utils.email_providers.mail_service.time.sleep"):
            with patch("utils.email_providers.mail_service.time.time", return_value=1_776_420_010.0):
                with redirect_stdout(io.StringIO()):
                    code = _poll_local_ms_for_oai_code_graph(
                        ms_service=service,
                        target_email="user+alias@example.com",
                        mailbox_dict=mailbox,
                        processed_mail_ids=set(),
                        mail_state={},
                        max_attempts=1,
                    )

        self.assertEqual("", code)


if __name__ == "__main__":
    unittest.main()
