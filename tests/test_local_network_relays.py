import unittest

from utils.local_network import (
    build_host_relay_specs,
    rewrite_url_for_host_relay,
    should_use_host_relay,
)


class LocalNetworkRelayTests(unittest.TestCase):
    def test_should_use_host_relay_for_private_lan_http_url(self):
        self.assertTrue(should_use_host_relay("http://192.168.31.214:8080"))
        self.assertTrue(should_use_host_relay("https://10.0.0.8:9443"))
        self.assertFalse(should_use_host_relay("http://127.0.0.1:8080"))
        self.assertFalse(should_use_host_relay("http://localhost:8080"))
        self.assertFalse(should_use_host_relay("https://example.com"))

    def test_rewrite_url_for_host_relay_preserves_scheme_and_path(self):
        self.assertEqual(
            "http://host.docker.internal:18080/api/v1/admin/accounts",
            rewrite_url_for_host_relay(
                "http://192.168.31.214:8080/api/v1/admin/accounts",
                18080,
            ),
        )
        self.assertEqual(
            "https://host.docker.internal:18443/base",
            rewrite_url_for_host_relay("https://10.0.0.8:9443/base", 18443),
        )

    def test_build_host_relay_specs_collects_supported_services(self):
        config = {
            "sub2api_mode": {
                "api_url": "http://192.168.31.214:8080",
                "host_relay_port": 18080,
            },
            "cpa_mode": {
                "api_url": "http://192.168.31.215:8317",
                "host_relay_port": 18317,
            },
        }

        specs = build_host_relay_specs(config)

        self.assertEqual(
            [
                {
                    "name": "sub2api",
                    "target_host": "192.168.31.214",
                    "target_port": 8080,
                    "listen_host": "0.0.0.0",
                    "listen_port": 18080,
                    "source_url": "http://192.168.31.214:8080",
                },
                {
                    "name": "cpa",
                    "target_host": "192.168.31.215",
                    "target_port": 8317,
                    "listen_host": "0.0.0.0",
                    "listen_port": 18317,
                    "source_url": "http://192.168.31.215:8317",
                },
            ],
            specs,
        )

    def test_build_host_relay_specs_ignores_public_or_disabled_entries(self):
        config = {
            "sub2api_mode": {
                "api_url": "https://api.example.com",
                "host_relay_port": 18080,
            },
            "cpa_mode": {
                "api_url": "http://192.168.31.215:8317",
                "host_relay_port": 0,
            },
        }

        self.assertEqual([], build_host_relay_specs(config))


if __name__ == "__main__":
    unittest.main()
