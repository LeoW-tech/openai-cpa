import importlib
import unittest
from unittest.mock import patch


class ConfigHeroSmsReuseTests(unittest.TestCase):
    def _reload_config(self):
        import utils.config as config

        return importlib.reload(config)

    def test_reload_all_configs_reads_hero_sms_reuse_max_uses(self):
        config = self._reload_config()
        config_payload = {
            "database": {"type": "sqlite", "mysql": {}},
            "hero_sms": {
                "enabled": True,
                "api_key": "demo-key",
                "reuse_max_uses": 3,
            },
            "sub2api_mode": {},
            "cpa_mode": {},
            "luckmail": {},
            "ai_service": {},
            "duckmail": {},
            "normal_mode": {},
            "clash_proxy_pool": {},
        }

        with patch.object(config, "init_config", return_value=config_payload):
            with patch.object(config, "reload_proxy_config"):
                config.reload_all_configs(new_config_dict=config_payload)

        self.assertEqual(3, config.HERO_SMS_REUSE_MAX_USES)

    def test_reload_all_configs_clamps_invalid_reuse_max_uses_to_minimum(self):
        config = self._reload_config()
        config_payload = {
            "database": {"type": "sqlite", "mysql": {}},
            "hero_sms": {
                "enabled": True,
                "api_key": "demo-key",
                "reuse_max_uses": 0,
            },
            "sub2api_mode": {},
            "cpa_mode": {},
            "luckmail": {},
            "ai_service": {},
            "duckmail": {},
            "normal_mode": {},
            "clash_proxy_pool": {},
        }

        with patch.object(config, "init_config", return_value=config_payload):
            with patch.object(config, "reload_proxy_config"):
                config.reload_all_configs(new_config_dict=config_payload)

        self.assertEqual(1, config.HERO_SMS_REUSE_MAX_USES)
