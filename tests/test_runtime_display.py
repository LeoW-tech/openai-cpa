import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.runtime_display import get_local_storage_paths, get_public_console_url


class RuntimeDisplayTests(unittest.TestCase):
    def test_public_console_url_defaults_to_loopback_18000(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("http://127.0.0.1:18000", get_public_console_url())

    def test_public_console_url_uses_env_override(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_CPA_PUBLIC_HOST": "127.0.0.1",
                "OPENAI_CPA_PUBLIC_PORT": "18000",
            },
            clear=True,
        ):
            self.assertEqual("http://127.0.0.1:18000", get_public_console_url())

    def test_local_storage_paths_prefers_host_project_path(self):
        repo_root = Path("/repo")
        with patch.dict(os.environ, {"HOST_PROJECT_PATH": "/host/project"}, clear=True):
            data_dir, db_path = get_local_storage_paths(repo_root)
        self.assertEqual("/host/project/data", data_dir)
        self.assertEqual("/host/project/data/data.db", db_path)

    def test_local_storage_paths_falls_back_to_repo_root(self):
        repo_root = Path("/repo")
        with patch.dict(os.environ, {}, clear=True):
            data_dir, db_path = get_local_storage_paths(repo_root)
        self.assertEqual("/repo/data", data_dir)
        self.assertEqual("/repo/data/data.db", db_path)


if __name__ == "__main__":
    unittest.main()
