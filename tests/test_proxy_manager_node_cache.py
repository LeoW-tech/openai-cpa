import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", elapsed_seconds=0.1):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.elapsed = SimpleNamespace(total_seconds=lambda: elapsed_seconds)

    def json(self):
        return self._payload


class ProxyManagerNodeCacheTests(unittest.TestCase):
    def _reload_proxy_manager(self):
        sys.modules.pop("utils.proxy_manager", None)
        return importlib.import_module("utils.proxy_manager")

    def test_switch_success_caches_raw_node_name(self):
        proxy_manager = self._reload_proxy_manager()
        raw_node_name = "🇯🇵 日本W03 | IEPL"
        proxy_url = "http://127.0.0.1:7890"

        proxies_payload = {
            "proxies": {
                "节点选择": {
                    "all": [raw_node_name],
                }
            }
        }

        with patch.object(proxy_manager, "ENABLE_NODE_SWITCH", True), \
             patch.object(proxy_manager, "POOL_MODE", False), \
             patch.object(proxy_manager, "FASTEST_MODE", False), \
             patch.object(proxy_manager, "PROXY_GROUP_NAME", "节点选择"), \
             patch.object(proxy_manager, "CLASH_API_URL", "http://127.0.0.1:9090"), \
             patch.object(proxy_manager, "test_proxy_liveness", return_value=True), \
             patch.object(proxy_manager.random, "choice", return_value=raw_node_name), \
             patch.object(proxy_manager.std_requests, "get", return_value=_FakeResponse(payload=proxies_payload)), \
             patch.object(proxy_manager.std_requests, "put", return_value=_FakeResponse(status_code=204)):
            self.assertTrue(proxy_manager.smart_switch_node(proxy_url))

        self.assertEqual(raw_node_name, proxy_manager.get_last_success_node_name(proxy_url))

    def test_switch_skips_current_node_when_alternative_exists(self):
        proxy_manager = self._reload_proxy_manager()
        current_node = "🇯🇵 日本W03 | IEPL"
        next_node = "🇰🇷 韩国W01"
        proxy_url = "http://127.0.0.1:17890"

        proxies_payload = {
            "proxies": {
                "节点选择": {
                    "all": [current_node, next_node],
                    "now": current_node,
                }
            }
        }

        with patch.object(proxy_manager, "ENABLE_NODE_SWITCH", True), \
             patch.object(proxy_manager, "POOL_MODE", False), \
             patch.object(proxy_manager, "FASTEST_MODE", False), \
             patch.object(proxy_manager, "PROXY_GROUP_NAME", "节点选择"), \
             patch.object(proxy_manager, "CLASH_API_URL", "http://127.0.0.1:19090"), \
             patch.object(proxy_manager, "test_proxy_liveness", return_value=True), \
             patch.object(proxy_manager.std_requests, "get", return_value=_FakeResponse(payload=proxies_payload)), \
             patch.object(proxy_manager.std_requests, "put", return_value=_FakeResponse(status_code=204)) as put_mock, \
             patch.object(proxy_manager.random, "choice", side_effect=lambda seq: seq[0]) as choice_mock:
            self.assertTrue(proxy_manager.smart_switch_node(proxy_url))

        choice_mock.assert_called_once_with([next_node])
        self.assertEqual(
            {"name": next_node},
            put_mock.call_args.kwargs["json"],
        )
        self.assertEqual(next_node, proxy_manager.get_last_success_node_name(proxy_url))

    def test_global_group_only_switches_leaf_proxies(self):
        proxy_manager = self._reload_proxy_manager()
        current_node = "🇯🇵 日本W10 | IEPL"
        next_node = "🇰🇷 韩国W01"
        nested_group = "🎮 Steam 登录/下载"
        proxy_url = "http://127.0.0.1:17890"

        proxies_payload = {
            "proxies": {
                "GLOBAL": {
                    "all": ["DIRECT", current_node, nested_group, next_node],
                    "now": current_node,
                },
                current_node: {"type": "Shadowsocks"},
                next_node: {"type": "Shadowsocks"},
                nested_group: {
                    "type": "Selector",
                    "all": ["DIRECT", "🔰 选择节点"],
                    "now": "DIRECT",
                },
            }
        }

        with patch.object(proxy_manager, "ENABLE_NODE_SWITCH", True), \
             patch.object(proxy_manager, "POOL_MODE", False), \
             patch.object(proxy_manager, "FASTEST_MODE", False), \
             patch.object(proxy_manager, "PROXY_GROUP_NAME", "GLOBAL"), \
             patch.object(proxy_manager, "CLASH_API_URL", "http://127.0.0.1:19090"), \
             patch.object(proxy_manager, "test_proxy_liveness", return_value=True), \
             patch.object(proxy_manager.std_requests, "get", return_value=_FakeResponse(payload=proxies_payload)), \
             patch.object(proxy_manager.std_requests, "put", return_value=_FakeResponse(status_code=204)) as put_mock, \
             patch.object(proxy_manager.random, "choice", side_effect=lambda seq: seq[0]) as choice_mock:
            self.assertTrue(proxy_manager.smart_switch_node(proxy_url))

        choice_mock.assert_called_once_with([next_node])
        self.assertEqual({"name": next_node}, put_mock.call_args.kwargs["json"])

    def test_proxy_liveness_accepts_http_probe_when_trace_unavailable(self):
        proxy_manager = self._reload_proxy_manager()

        with patch.object(
            proxy_manager.std_requests,
            "get",
            side_effect=[
                _FakeResponse(status_code=204),
                RuntimeError("trace down"),
            ],
        ):
            self.assertTrue(proxy_manager.test_proxy_liveness("http://127.0.0.1:41001"))

        self.assertEqual(
            "region_unknown",
            proxy_manager.get_last_liveness_result("http://127.0.0.1:41001").get("reason"),
        )

    def test_proxy_liveness_does_not_fail_when_only_trace_probe_breaks(self):
        proxy_manager = self._reload_proxy_manager()

        with patch.object(
            proxy_manager.std_requests,
            "get",
            side_effect=[
                _FakeResponse(status_code=204),
                _FakeResponse(status_code=502),
            ],
        ):
            self.assertTrue(proxy_manager.test_proxy_liveness("http://127.0.0.1:41002"))

        self.assertEqual(
            "region_unknown",
            proxy_manager.get_last_liveness_result("http://127.0.0.1:41002").get("reason"),
        )

    def test_switch_filters_out_unresolvable_servers(self):
        proxy_manager = self._reload_proxy_manager()
        proxy_url = "http://127.0.0.1:17890"
        bad_node = "美国-US-BAD"
        good_node = "日本-OS-GOOD"
        proxies_payload = {
            "proxies": {
                "节点选择": {
                    "all": [bad_node, good_node],
                    "now": bad_node,
                },
                bad_node: {"type": "Shadowsocks", "server": "bad.example.invalid"},
                good_node: {"type": "Shadowsocks", "server": "good.example.com"},
            }
        }

        with patch.object(proxy_manager, "ENABLE_NODE_SWITCH", True), \
             patch.object(proxy_manager, "POOL_MODE", False), \
             patch.object(proxy_manager, "FASTEST_MODE", False), \
             patch.object(proxy_manager, "PROXY_GROUP_NAME", "节点选择"), \
             patch.object(proxy_manager, "CLASH_API_URL", "http://127.0.0.1:19090"), \
             patch.object(proxy_manager, "test_proxy_liveness", return_value=True), \
             patch.object(proxy_manager.std_requests, "get", return_value=_FakeResponse(payload=proxies_payload)), \
             patch.object(proxy_manager.std_requests, "put", return_value=_FakeResponse(status_code=204)) as put_mock, \
             patch.object(proxy_manager, "_hostname_resolvable", side_effect=lambda host: host == "good.example.com"), \
             patch.object(proxy_manager.random, "choice", side_effect=lambda seq: seq[0]) as choice_mock:
            self.assertTrue(proxy_manager.smart_switch_node(proxy_url))

        choice_mock.assert_called_once_with([good_node])
        self.assertEqual({"name": good_node}, put_mock.call_args.kwargs["json"])

    def test_switch_returns_false_when_all_candidates_fail_dns_resolution(self):
        proxy_manager = self._reload_proxy_manager()
        proxy_url = "http://127.0.0.1:17890"
        proxies_payload = {
            "proxies": {
                "节点选择": {
                    "all": ["美国-US-BAD"],
                },
                "美国-US-BAD": {"type": "Shadowsocks", "server": "bad.example.invalid"},
            }
        }

        with patch.object(proxy_manager, "ENABLE_NODE_SWITCH", True), \
             patch.object(proxy_manager, "POOL_MODE", False), \
             patch.object(proxy_manager, "FASTEST_MODE", False), \
             patch.object(proxy_manager, "PROXY_GROUP_NAME", "节点选择"), \
             patch.object(proxy_manager, "CLASH_API_URL", "http://127.0.0.1:19090"), \
             patch.object(proxy_manager.std_requests, "get", return_value=_FakeResponse(payload=proxies_payload)), \
             patch.object(proxy_manager, "_hostname_resolvable", return_value=False), \
             patch.object(proxy_manager.std_requests, "put") as put_mock:
            self.assertFalse(proxy_manager.smart_switch_node(proxy_url))

        put_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
