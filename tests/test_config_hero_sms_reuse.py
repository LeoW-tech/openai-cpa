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

    @staticmethod
    def _build_config_payload(hero_sms: dict) -> dict:
        return {
            "database": {"type": "sqlite", "mysql": {}},
            "hero_sms": hero_sms,
            "sub2api_mode": {},
            "cpa_mode": {},
            "luckmail": {},
            "ai_service": {},
            "duckmail": {},
            "normal_mode": {},
            "clash_proxy_pool": {},
        }

    def test_reload_all_configs_keeps_canonical_hero_sms_reuse_max(self):
        config = self._reload_config()
        config_payload = self._build_config_payload(
            {
                "enabled": True,
                "api_key": "demo-key",
                "reuse_phone": True,
                "reuse_max": 9,
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"

            with patch.object(config, "CONFIG_PATH", str(config_path)):
                with patch.object(config, "init_config", return_value=config_payload):
                    with patch.object(config, "reload_proxy_config"):
                        config.reload_all_configs(new_config_dict=config_payload)

            saved_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        self.assertTrue(config.HERO_SMS_REUSE_PHONE)
        self.assertEqual(9, config.HERO_SMS_REUSE_MAX)
        self.assertEqual(9, config.HERO_SMS_REUSE_MAX_USES)
        self.assertTrue(saved_payload["hero_sms"]["enabled"])
        self.assertEqual("demo-key", saved_payload["hero_sms"]["api_key"])
        self.assertEqual(9, saved_payload["hero_sms"]["reuse_max"])
        self.assertNotIn("reuse_max_uses", saved_payload["hero_sms"])

    def test_reload_all_configs_accepts_legacy_hero_sms_reuse_max_uses(self):
        config = self._reload_config()
        config_payload = self._build_config_payload(
            {
                "enabled": True,
                "api_key": "demo-key",
                "reuse_phone": True,
                "reuse_max": 2,
                "reuse_max_uses": 7,
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"

            with patch.object(config, "CONFIG_PATH", str(config_path)):
                with patch.object(config, "init_config", return_value=config_payload):
                    with patch.object(config, "reload_proxy_config"):
                        config.reload_all_configs(new_config_dict=config_payload)

        self.assertTrue(config.HERO_SMS_REUSE_PHONE)
        self.assertEqual(7, config.HERO_SMS_REUSE_MAX)
        self.assertEqual(7, config.HERO_SMS_REUSE_MAX_USES)

    def test_reload_all_configs_does_not_truncate_existing_config_when_dump_fails(self):
        config = self._reload_config()
        config_payload = self._build_config_payload({"enabled": True})

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
