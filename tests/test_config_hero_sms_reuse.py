import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


class ConfigHeroSmsReuseTests(unittest.TestCase):
    def _reload_config(self):
        import utils.config as config

        return importlib.reload(config)

    def test_reload_all_configs_ignores_legacy_hero_sms_reuse_max_uses(self):
        config = self._reload_config()
        config_payload = {
            "database": {"type": "sqlite", "mysql": {}},
            "hero_sms": {
                "enabled": True,
                "api_key": "demo-key",
                "reuse_phone": True,
                "reuse_max_uses": 9,
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

        self.assertTrue(config.HERO_SMS_REUSE_PHONE)
        self.assertFalse(hasattr(config, "HERO_SMS_REUSE_MAX_USES"))

    def test_reload_all_configs_does_not_truncate_existing_config_when_dump_fails(self):
        config = self._reload_config()
        config_payload = {
            "database": {"type": "sqlite", "mysql": {}},
            "hero_sms": {"enabled": True},
            "sub2api_mode": {},
            "cpa_mode": {},
            "luckmail": {},
            "ai_service": {},
            "duckmail": {},
            "normal_mode": {},
            "clash_proxy_pool": {},
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"
            original_text = yaml.safe_dump({"hero_sms": {"enabled": False}}, allow_unicode=True, sort_keys=False)
            config_path.write_text(original_text, encoding="utf-8")

            with patch.object(config, "CONFIG_PATH", str(config_path)):
                with patch.object(config, "init_config", return_value=config_payload):
                    with patch.object(config, "reload_proxy_config"):
                        with patch.object(config.yaml, "dump", side_effect=RuntimeError("write interrupted")):
                            with self.assertRaises(RuntimeError):
                                config.reload_all_configs(new_config_dict=config_payload)

            self.assertEqual(original_text, config_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
