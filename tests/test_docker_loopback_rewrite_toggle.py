import importlib
import os
import sys
import unittest
from unittest.mock import patch


class DockerLoopbackRewriteToggleTests(unittest.TestCase):
    def _reload_config_module(self):
        sys.modules.pop("utils.config", None)
        return importlib.import_module("utils.config")

    def _reload_proxy_manager_module(self):
        sys.modules.pop("utils.proxy_manager", None)
        return importlib.import_module("utils.proxy_manager")

    def test_config_format_docker_url_keeps_loopback_when_disable_flag_enabled(self):
        config = self._reload_config_module()

        with patch.dict(os.environ, {"OPENAI_CPA_DISABLE_DOCKER_LOOPBACK_REWRITE": "1"}, clear=False), \
             patch.object(config.os.path, "exists", side_effect=lambda path: True if path == "/.dockerenv" else os.path.exists(path)):
            self.assertEqual(
                "http://127.0.0.1:8080/",
                config.format_docker_url("http://127.0.0.1:8080/"),
            )
            self.assertEqual(
                "http://localhost:9090",
                config.format_docker_url("http://localhost:9090"),
            )

    def test_proxy_manager_format_docker_url_keeps_loopback_when_disable_flag_enabled(self):
        proxy_manager = self._reload_proxy_manager_module()

        with patch.dict(os.environ, {"OPENAI_CPA_DISABLE_DOCKER_LOOPBACK_REWRITE": "true"}, clear=False), \
             patch.object(proxy_manager, "_IS_IN_DOCKER", True):
            self.assertEqual(
                "http://127.0.0.1:7890",
                proxy_manager.format_docker_url("http://127.0.0.1:7890"),
            )
            self.assertEqual(
                "http://localhost:9090",
                proxy_manager.format_docker_url("http://localhost:9090"),
            )


if __name__ == "__main__":
    unittest.main()
