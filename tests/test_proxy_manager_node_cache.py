import importlib
import sys
import unittest
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

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


if __name__ == "__main__":
    unittest.main()
