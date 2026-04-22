import unittest

from utils.integrations import mihomo_runtime_tools as tools


class MihomoRuntimeToolsTests(unittest.TestCase):
    def _source_config(self):
        return {
            "port": 7890,
            "socks-port": 7891,
            "allow-lan": False,
            "external-controller": "127.0.0.1:9000",
            "proxy-groups": [
                {"name": "Proxy", "type": "select", "proxies": ["Auto", "日本W03 | IEPL"]},
                {"name": "Auto", "type": "url-test", "proxies": ["日本W03 | IEPL"]},
            ],
            "proxies": [{"name": "日本W03 | IEPL", "type": "ss", "server": "jp03.example.com", "port": 443}],
            "rules": ["DOMAIN-SUFFIX,openai.com,Proxy", "MATCH,DIRECT"],
            "dns": {"enable": True, "nameserver": ["223.5.5.5"]},
        }

    def test_summarize_config_reports_proxy_groups(self):
        summary = tools.summarize_config(self._source_config())
        self.assertEqual(["Proxy", "Auto"], summary["proxy_group_names"])
        self.assertEqual(2, summary["rule_count"])
        self.assertEqual(1, summary["proxy_groups"][1]["proxy_count"])

    def test_diff_focus_sections_detects_mac_only_and_changed_values(self):
        linux_config = self._source_config()
        mac_config = self._source_config()
        mac_config["tun"] = {"enable": True}
        mac_config["dns"] = {"enable": True, "nameserver": ["192.168.31.1"]}

        diff = tools.diff_focus_sections(linux_config, mac_config)
        self.assertIn("tun", diff["only_in_mac"])
        self.assertIn("dns", diff["different"])
        self.assertEqual(["223.5.5.5"], diff["different"]["dns"]["linux"]["nameserver"])

    def test_build_host_test_config_preserves_ports_and_applies_overlay(self):
        source = self._source_config()
        overlay = {
            "dns": {"enable": True, "nameserver": ["192.168.31.1"]},
            "tun": {"enable": True},
        }

        config, applied_keys = tools.build_host_test_config(
            source,
            overlay_config=overlay,
            overlay_keys=["dns", "tun", "sniffer"],
            port=41041,
            socks_port=41042,
            controller_port=42041,
            log_level="debug",
        )

        self.assertEqual(41041, config["port"])
        self.assertEqual(41042, config["socks-port"])
        self.assertEqual("127.0.0.1:42041", config["external-controller"])
        self.assertEqual("debug", config["log-level"])
        self.assertEqual(["192.168.31.1"], config["dns"]["nameserver"])
        self.assertTrue(config["tun"]["enable"])
        self.assertNotIn("mixed-port", config)
        self.assertEqual(["dns", "tun"], applied_keys)


if __name__ == "__main__":
    unittest.main()
