import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

fake_requests_module = types.SimpleNamespace(post=None, get=None, Response=object)
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.modules["curl_cffi"] = types.SimpleNamespace(requests=fake_requests_module)

from utils.email_providers.local_microsoft_service import LocalMicrosoftService, MailboxAbuseModeError


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttpxClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, data=None):
        self.calls.append(("post", url, data))
        return self._responses.pop(0)

    def get(self, url, params=None, headers=None):
        self.calls.append(("get", url, params, headers))
        return self._responses.pop(0)


class LocalMicrosoftServiceAbuseModeTests(unittest.TestCase):
    def test_exchange_refresh_token_uses_httpx_client_instead_of_curl_cffi(self):
        service = LocalMicrosoftService(proxies={"https": "http://127.0.0.1:41001"})
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "refresh_token": "refresh-token",
            "client_id": "client-id",
        }
        fake_client = _FakeHttpxClient(
            [
                _FakeResponse(
                    200,
                    {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token-2",
                        "scope": "https://graph.microsoft.com/Mail.Read offline_access",
                    },
                )
            ]
        )

        with patch(
            "utils.email_providers.local_microsoft_service.httpx.Client",
            return_value=fake_client,
        ) as client_cls:
            with patch(
                "utils.email_providers.local_microsoft_service.cffi_requests.post",
                side_effect=AssertionError("微软 token 请求不应再走 curl_cffi"),
            ):
                token = service._exchange_refresh_token(mailbox)

        self.assertEqual("access-token", token)
        self.assertEqual("graph_full", mailbox["token_type"])
        client_cls.assert_called_once()
        self.assertNotIn("http2", client_cls.call_args.kwargs)
        self.assertEqual("refresh-token-2", mailbox["refresh_token"])

    def test_fetch_openai_messages_uses_httpx_graph_client_instead_of_curl_cffi(self):
        service = LocalMicrosoftService(proxies={"https": "http://127.0.0.1:41001"})
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
        }
        fake_client = _FakeHttpxClient(
            [
                _FakeResponse(
                    200,
                    {
                        "value": [
                            {
                                "id": "msg-1",
                                "subject": "Your OpenAI code",
                                "from": {"emailAddress": {"address": "noreply@openai.com"}},
                                "toRecipients": [{"emailAddress": {"address": "user+alias@example.com"}}],
                                "receivedDateTime": "2026-04-19T00:00:00Z",
                                "bodyPreview": "123456",
                                "body": {"content": "123456"},
                            }
                        ]
                    },
                )
            ]
        )

        with patch.object(service, "_exchange_refresh_token", return_value="access-token"):
            with patch(
                "utils.email_providers.local_microsoft_service.httpx.Client",
                return_value=fake_client,
            ) as client_cls:
                with patch(
                    "utils.email_providers.local_microsoft_service.cffi_requests.get",
                    side_effect=AssertionError("微软 Graph 拉信不应再走 curl_cffi"),
                ):
                    messages = service.fetch_openai_messages(mailbox)

        self.assertEqual(1, len(messages))
        self.assertEqual("msg-1", messages[0]["id"])
        client_cls.assert_called_once()
        self.assertNotIn("http2", client_cls.call_args.kwargs)

    def test_service_abuse_mode_marks_master_mailbox_dead(self):
        service = LocalMicrosoftService()
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
            "refresh_token": "refresh-token",
            "client_id": "client-id",
        }
        responses = [
            _FakeResponse(
                400,
                {
                    "error": "invalid_scope",
                    "error_description": "AADSTS70000 invalid_scope",
                },
            ),
            _FakeResponse(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "AADSTS70000: User account is found to be in service abuse mode.",
                },
            ),
        ]

        def fake_post(*args, **kwargs):
            return responses.pop(0)

        with patch(
            "utils.email_providers.local_microsoft_service.httpx.Client",
            return_value=_FakeHttpxClient(responses),
        ):
            with patch(
                "utils.email_providers.local_microsoft_service.db_manager.update_local_mailbox_status"
            ) as update_status:
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(MailboxAbuseModeError) as ctx:
                        service._exchange_refresh_token(mailbox)

        self.assertIn("service abuse mode", str(ctx.exception))
        update_status.assert_called_once_with("user@example.com", 3)

    def test_fetch_openai_messages_logs_warning_instead_of_debug_for_service_abuse(self):
        service = LocalMicrosoftService()
        mailbox = {
            "email": "user+alias@example.com",
            "master_email": "user@example.com",
        }

        with patch.object(
            service,
            "_exchange_refresh_token",
            side_effect=MailboxAbuseModeError("user@example.com"),
        ):
            captured = io.StringIO()
            with redirect_stdout(captured):
                messages = service.fetch_openai_messages(mailbox)

        self.assertEqual([], messages)
        self.assertEqual("abuse_mode", mailbox.get("_polling_stopped"))
        output = captured.getvalue()
        self.assertIn("service abuse mode", output)
        self.assertNotIn("[DEBUG-GRAPH]", output)


if __name__ == "__main__":
    unittest.main()
