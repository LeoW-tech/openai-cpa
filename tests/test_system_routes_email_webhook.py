import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeAPIRouter:
    def get(self, *args, **kwargs):
        return self._decorate

    def post(self, *args, **kwargs):
        return self._decorate

    def websocket(self, *args, **kwargs):
        return self._decorate

    @staticmethod
    def _decorate(func):
        return func


class _FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeHTMLResponse:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeStreamingResponse(_FakeHTMLResponse):
    pass


class _FakeTTLCache(dict):
    def __init__(self, maxsize=None, ttl=None):
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl


class SystemRoutesEmailWebhookTests(unittest.TestCase):
    def setUp(self):
        fastapi_module = types.ModuleType("fastapi")
        fastapi_module.APIRouter = _FakeAPIRouter
        fastapi_module.Depends = lambda dependency=None: dependency
        fastapi_module.Header = lambda default=None, **kwargs: default
        fastapi_module.Query = lambda default=None, **kwargs: default
        fastapi_module.Request = type("Request", (), {})
        fastapi_module.WebSocket = type("WebSocket", (), {})
        fastapi_module.HTTPException = _FakeHTTPException

        fastapi_responses_module = types.ModuleType("fastapi.responses")
        fastapi_responses_module.HTMLResponse = _FakeHTMLResponse
        fastapi_responses_module.StreamingResponse = _FakeStreamingResponse

        self._module_patches = patch.dict(
            sys.modules,
            {
                "fastapi": fastapi_module,
                "fastapi.responses": fastapi_responses_module,
                "cachetools": types.SimpleNamespace(TTLCache=_FakeTTLCache),
                "utils.core_engine": types.SimpleNamespace(
                    cfg=types.SimpleNamespace(
                        FREEMAIL_LOCAL_WEBHOOK=True,
                        FREEMAIL_WEBHOOK_SECRET="secret-123",
                        CM_LOCAL_WEBHOOK=False,
                        CM_WEBHOOK_SECRET="cloud-secret",
                    ),
                    ts=lambda: "2026-04-25 12:00:00",
                    run_stats={},
                ),
                "utils.db_manager": types.SimpleNamespace(),
                "utils.integrations.tg_notifier": types.SimpleNamespace(send_tg_msg_async=lambda *args, **kwargs: None),
                "global_state": types.SimpleNamespace(
                    VALID_TOKENS=set(),
                    CLUSTER_NODES={},
                    NODE_COMMANDS={},
                    cluster_lock=types.SimpleNamespace(),
                    log_history=[],
                    engine=types.SimpleNamespace(is_running=lambda: False, stop=lambda: None),
                    verify_token=lambda: "token",
                    worker_status={},
                    append_log=lambda *args, **kwargs: None,
                ),
            },
        )
        self._module_patches.start()
        sys.modules.pop("routers.system_routes", None)

    def tearDown(self):
        sys.modules.pop("routers.system_routes", None)
        self._module_patches.stop()

    def _reload_system_routes(self):
        import routers.system_routes as system_routes

        system_routes = importlib.reload(system_routes)
        system_routes.core_engine = types.SimpleNamespace(
            cfg=types.SimpleNamespace(
                FREEMAIL_LOCAL_WEBHOOK=True,
                FREEMAIL_WEBHOOK_SECRET="secret-123",
                CM_LOCAL_WEBHOOK=False,
                CM_WEBHOOK_SECRET="cloud-secret",
                NORMAL_TARGET_COUNT=0,
            ),
            ts=lambda: "2026-04-25 12:00:00",
            run_stats={},
        )
        system_routes.processed_msgs.clear()
        system_routes.code_pool.clear()
        return system_routes

    @staticmethod
    def _build_raw_email(body: str) -> str:
        return (
            "From: OpenAI <noreply@openai.com>\r\n"
            "To: user@example.com\r\n"
            "Subject: Your verification code\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            f"{body}"
        )

    def test_receive_email_webhook_rejects_secret_mismatch(self):
        system_routes = self._reload_system_routes()
        req = system_routes.EmailWebhookReq(
            message_id="msg-1",
            to_addr="user@example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 123456"),
        )

        with self.assertRaises(_FakeHTTPException) as ctx:
            asyncio.run(system_routes.receive_email_webhook(req, x_webhook_secret="wrong-secret"))

        self.assertEqual(403, ctx.exception.status_code)
        self.assertEqual("Unauthorized: Secret mismatch", ctx.exception.detail)
        self.assertNotIn("user@example.com", system_routes.code_pool)

    def test_receive_email_webhook_ignores_duplicate_message_id(self):
        system_routes = self._reload_system_routes()
        first_req = system_routes.EmailWebhookReq(
            message_id="dup-1",
            to_addr="User@Example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 123456"),
        )
        second_req = system_routes.EmailWebhookReq(
            message_id="dup-1",
            to_addr="user@example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 654321"),
        )

        first_result = asyncio.run(system_routes.receive_email_webhook(first_req, x_webhook_secret="secret-123"))
        second_result = asyncio.run(system_routes.receive_email_webhook(second_req, x_webhook_secret="secret-123"))

        self.assertEqual({"status": "success"}, first_result)
        self.assertEqual({"status": "ignored"}, second_result)
        self.assertIn("123456", system_routes.code_pool["user@example.com"])

    def test_receive_email_webhook_returns_error_when_email_parse_fails(self):
        system_routes = self._reload_system_routes()
        req = system_routes.EmailWebhookReq(
            message_id="msg-parse",
            to_addr="user@example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 123456"),
        )

        with patch.object(system_routes.email, "message_from_string", side_effect=ValueError("bad mime")):
            result = asyncio.run(system_routes.receive_email_webhook(req, x_webhook_secret="secret-123"))

        self.assertEqual({"status": "error", "message": "Parse exception"}, result)
        self.assertNotIn("user@example.com", system_routes.code_pool)

    def test_receive_email_webhook_stores_text_body_in_code_pool(self):
        system_routes = self._reload_system_routes()
        req = system_routes.EmailWebhookReq(
            message_id="msg-success",
            to_addr="User@Example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 654321"),
        )

        result = asyncio.run(system_routes.receive_email_webhook(req, x_webhook_secret="secret-123"))

        self.assertEqual({"status": "success"}, result)
        self.assertIn("user@example.com", system_routes.code_pool)
        self.assertEqual("Your ChatGPT code is 654321", system_routes.code_pool["user@example.com"])

    def test_receive_email_webhook_accepts_cloudmail_secret_when_cloudmail_mode_enabled(self):
        system_routes = self._reload_system_routes()
        system_routes.core_engine.cfg.FREEMAIL_LOCAL_WEBHOOK = False
        system_routes.core_engine.cfg.CM_LOCAL_WEBHOOK = True
        req = system_routes.EmailWebhookReq(
            message_id="msg-cloudmail",
            to_addr="cloud@example.com",
            raw_content=self._build_raw_email("Your ChatGPT code is 998877"),
            from_addr="noreply@cloud-mail.test",
        )

        result = asyncio.run(system_routes.receive_email_webhook(req, x_webhook_secret="cloud-secret"))

        self.assertEqual({"status": "success"}, result)
        self.assertEqual("Your ChatGPT code is 998877", system_routes.code_pool["cloud@example.com"])


if __name__ == "__main__":
    unittest.main()
