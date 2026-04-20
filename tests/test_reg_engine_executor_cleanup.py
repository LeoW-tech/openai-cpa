import unittest
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

_stubs = {
    "utils.email_providers.mail_service": types.SimpleNamespace(
        mask_email=lambda value: value,
    ),
    "utils.register": types.SimpleNamespace(
        run=lambda *args, **kwargs: None,
        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
    ),
    "utils.proxy_manager": types.SimpleNamespace(
        get_last_success_node_name=lambda *args, **kwargs: "",
        smart_switch_node=lambda *args, **kwargs: True,
        reload_proxy_config=lambda *args, **kwargs: None,
    ),
    "utils.integrations.sub2api_client": types.SimpleNamespace(
        Sub2APIClient=lambda *args, **kwargs: Mock(),
    ),
    "utils.integrations.tg_notifier": types.SimpleNamespace(
        send_tg_msg_sync=lambda *args, **kwargs: None,
    ),
}

with patch.dict(sys.modules, _stubs, clear=False):
    from utils.core_engine import RegEngine


class RegEngineExecutorCleanupTests(unittest.TestCase):
    def test_start_normal_reclaims_executor_after_natural_completion(self):
        engine = RegEngine()
        executor = Mock()
        engine._executor = executor
        args = SimpleNamespace(once=False, proxy=None)

        def _fake_run_in_thread(_args):
            engine._finalize_thread_run()

        with patch.object(engine, "_run_normal_in_thread", side_effect=_fake_run_in_thread):
            engine.start_normal(args)
            engine.current_thread.join(timeout=2)

        self.assertFalse(engine.current_thread.is_alive())
        executor.shutdown.assert_called_once_with(wait=False)
        self.assertIsNone(engine._executor)

    def test_run_threads_reclaim_executor_after_natural_completion(self):
        cases = [
            ("_run_cpa_in_thread", "_cpa_wrapper"),
            ("_run_sub2api_in_thread", "sub2api_main_loop"),
            ("_run_check_in_thread", "manual_check_main_loop"),
        ]

        for runner_name, target_name in cases:
            with self.subTest(runner=runner_name):
                engine = RegEngine()
                executor = Mock()
                engine._executor = executor
                args = SimpleNamespace(once=False, proxy=None)
                fake_loop = Mock()
                fake_loop.run_until_complete.side_effect = (
                    lambda coro: coro.close() if hasattr(coro, "close") else None
                )

                if target_name.startswith("_"):
                    setattr(engine, target_name, AsyncMock(return_value=None))
                    with patch("utils.core_engine.asyncio.new_event_loop", return_value=fake_loop), \
                         patch("utils.core_engine.asyncio.set_event_loop"):
                        getattr(engine, runner_name)(args)
                else:
                    with patch(f"utils.core_engine.{target_name}", new=AsyncMock(return_value=None)), \
                         patch("utils.core_engine.asyncio.new_event_loop", return_value=fake_loop), \
                         patch("utils.core_engine.asyncio.set_event_loop"):
                        getattr(engine, runner_name)(args)

                executor.shutdown.assert_called_once_with(wait=False)
                self.assertIsNone(engine._executor)


if __name__ == "__main__":
    unittest.main()
