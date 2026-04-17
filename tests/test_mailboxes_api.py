import asyncio
import importlib
import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from utils import db_manager


class DbManagerPathTests(unittest.TestCase):
    def test_db_path_is_anchored_to_project_data_dir_even_if_cwd_changes(self):
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.chdir(tmp_dir)
                reloaded = importlib.reload(db_manager)
                expected = Path(reloaded.__file__).resolve().parents[1] / "data" / "data.db"

                self.assertTrue(os.path.isabs(reloaded.DB_PATH))
                self.assertEqual(str(expected), reloaded.DB_PATH)
        finally:
            os.chdir(original_cwd)
            importlib.reload(db_manager)


class MailboxesApiTests(unittest.TestCase):
    def _load_api_routes(self):
        async def _fake_verify_token(*args, **kwargs):
            return "test-token"

        integrations_pkg = types.ModuleType("utils.integrations")
        clash_manager_module = types.ModuleType("utils.integrations.clash_manager")
        integrations_pkg.clash_manager = clash_manager_module

        stub_modules = {
            "cloudflare": types.SimpleNamespace(Cloudflare=object),
            "curl_cffi": types.SimpleNamespace(
                requests=types.SimpleNamespace(post=None, get=None, Response=object),
                CurlMime=object,
            ),
            "utils.integrations.ai_service": types.SimpleNamespace(AIService=object),
            "utils.email_providers.gmail_service": types.SimpleNamespace(
                get_gmail_otp_via_oauth=lambda *args, **kwargs: ""
            ),
            "utils.email_providers.duckmail_service": types.SimpleNamespace(DuckMailService=object),
            "utils.core_engine": types.SimpleNamespace(run_stats={}, ts=lambda: "00:00:00"),
            "utils.integrations": integrations_pkg,
            "utils.integrations.sub2api_client": types.SimpleNamespace(Sub2APIClient=object),
            "utils.integrations.tg_notifier": types.SimpleNamespace(
                send_tg_msg_async=lambda *args, **kwargs: None
            ),
            "utils.email_providers.gmail_oauth_handler": types.SimpleNamespace(GmailOAuthHandler=object),
            "utils.integrations.clash_manager": clash_manager_module,
            "global_state": types.SimpleNamespace(
                VALID_TOKENS=set(),
                CLUSTER_NODES={},
                NODE_COMMANDS={},
                cluster_lock=None,
                log_history=[],
                engine=types.SimpleNamespace(is_running=lambda: False, stop=lambda: None),
                verify_token=_fake_verify_token,
                worker_status={},
            ),
        }

        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, stub_modules))
            sys.modules.pop("routers.api_routes", None)
            import routers.api_routes as api_routes

            return api_routes

    def test_get_mailboxes_returns_error_payload_when_query_fails(self):
        try:
            api_routes = self._load_api_routes()
            with patch.object(
                api_routes.db_manager,
                "get_local_mailboxes_page",
                side_effect=RuntimeError("database temporarily unavailable"),
            ):
                result = asyncio.run(api_routes.get_mailboxes(page=1, page_size=10, token="test-token"))

            self.assertEqual("error", result["status"])
            self.assertIn("message", result)
        finally:
            sys.modules.pop("routers.api_routes", None)


if __name__ == "__main__":
    unittest.main()
