import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


class ConfigStartupMergeTests(unittest.TestCase):
    def _reload_config(self):
        import utils.config as config

        return importlib.reload(config)

    def test_init_config_only_backfills_missing_fields(self):
        config = self._reload_config()

        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            template_config = {
                "web_password": "admin",
                "disable_forced_takeover": True,
                "ai_service": {
                    "api_key": "template-key",
                    "model": "gpt-4.1",
                    "enable_profile": True,
                },
                "new_feature": {
                    "enabled": True,
                },
            }
            user_config = {
                "web_password": "my-secret",
                "disable_forced_takeover": False,
                "ai_service": {
                    "api_key": "",
                    "model": "custom-model",
                },
            }

            (base_dir / "config.example.yaml").write_text(
                yaml.safe_dump(template_config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (data_dir / "config.yaml").write_text(
                yaml.safe_dump(user_config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            with patch.object(config, "BASE_DIR", str(base_dir)):
                merged = config.init_config()

            saved = yaml.safe_load((data_dir / "config.yaml").read_text(encoding="utf-8"))

            self.assertEqual("my-secret", merged["web_password"])
            self.assertFalse(merged["disable_forced_takeover"])
            self.assertEqual("", merged["ai_service"]["api_key"])
            self.assertEqual("custom-model", merged["ai_service"]["model"])
            self.assertTrue(merged["ai_service"]["enable_profile"])
            self.assertEqual({"enabled": True}, merged["new_feature"])

            self.assertEqual(merged, saved)


if __name__ == "__main__":
    unittest.main()
