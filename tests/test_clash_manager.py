import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.modules.setdefault(
    "docker",
    types.SimpleNamespace(
        from_env=lambda: None,
        errors=types.SimpleNamespace(NotFound=RuntimeError),
    ),
)

from utils.integrations import clash_manager

clash_manager = importlib.reload(clash_manager)


class FakeContainer:
    def __init__(self, name, status="running", ports=None, mounts=None):
        self.name = name
        self.status = status
        self.attrs = {"HostConfig": {"PortBindings": ports or {}}, "Mounts": mounts or []}
        self.removed = False
        self.restarted = False

    def remove(self, force=False):
        self.removed = force

    def restart(self):
        self.restarted = True


class FakeContainers:
    def __init__(self, existing=None):
        self._items = {item.name: item for item in (existing or [])}
        self.run_calls = []

    def list(self, all=True, filters=None):
        prefix = (filters or {}).get("name")
        if not prefix:
            return list(self._items.values())
        return [item for item in self._items.values() if item.name.startswith(prefix)]

    def get(self, name):
        if name not in self._items:
            raise clash_manager.docker.errors.NotFound("missing")
        return self._items[name]

    def run(self, image, **kwargs):
        name = kwargs["name"]
        container = FakeContainer(
            name=name,
            status="running",
            ports={
                "7890/tcp": [{"HostPort": str(kwargs["ports"]["7890/tcp"])}],
                "9090/tcp": [{"HostPort": str(kwargs["ports"]["9090/tcp"])}],
            },
        )
        self._items[name] = container
        self.run_calls.append({"image": image, "kwargs": kwargs})
        return container


class FakeClient:
    def __init__(self, existing=None):
        self.containers = FakeContainers(existing)


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class ClashManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.base_path = self.root / "data" / "mihomo-pool"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.runtime_data_dir = self.root / "data"
        self.runtime_data_dir.mkdir(parents=True, exist_ok=True)
        (self.runtime_data_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "clash_proxy_pool": {
                        "secret": "unit-test-secret",
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

    def _patch_paths(self):
        return patch.multiple(
            clash_manager,
            BASE_PATH=str(self.base_path),
            HOST_PROJECT_PATH=str(self.root),
            HOST_BASE_PATH=str(self.base_path),
        )

    def test_deploy_clash_pool_mounts_instance_dir_and_ports(self):
        client = FakeClient()
        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(2)

        self.assertTrue(success, message)
        self.assertEqual(2, len(client.containers.run_calls))

        first_call = client.containers.run_calls[0]["kwargs"]
        self.assertEqual({"7890/tcp": 41001, "9090/tcp": 42001}, first_call["ports"])
        self.assertEqual(
            {
                str(self.base_path / "clash_1"): {
                    "bind": "/root/.config/mihomo",
                    "mode": "rw",
                }
            },
            first_call["volumes"],
        )
        self.assertTrue((self.base_path / "clash_1" / "config.yaml").is_file())

    def test_deploy_clash_pool_rejects_directory_config_path(self):
        client = FakeClient()
        clash_dir = self.base_path / "clash_1"
        clash_dir.mkdir(parents=True, exist_ok=True)
        (clash_dir / "config.yaml").mkdir()

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(1)

        self.assertFalse(success)
        self.assertIn("config.yaml", message)
        self.assertEqual([], client.containers.run_calls)

    def test_patch_and_update_writes_secret_and_runtime_patch(self):
        existing = [FakeContainer("clash_1"), FakeContainer("clash_2")]
        client = FakeClient(existing)
        sub_text = yaml.safe_dump(
            {
                "mixed-port": 9999,
                "external-controller": "127.0.0.1:9990",
                "proxy-groups": [{"name": "🔰 选择节点", "type": "select", "proxies": ["A"]}],
                "proxies": [{"name": "A", "type": "ss", "server": "a.example.com", "port": 443, "cipher": "aes-256-gcm", "password": "x"}],
            },
            allow_unicode=True,
        )

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client), patch.object(
            clash_manager.requests, "get", return_value=FakeResponse(sub_text)
        ):
            success, message = clash_manager.patch_and_update("https://example.com/sub", "all")

        self.assertTrue(success, message)
        for name in ("clash_1", "clash_2"):
            cfg = yaml.safe_load((self.base_path / name / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(7890, cfg["mixed-port"])
            self.assertEqual("0.0.0.0:9090", cfg["external-controller"])
            self.assertEqual("unit-test-secret", cfg["secret"])
            self.assertTrue(client.containers.get(name).restarted)

    def test_deploy_clash_pool_uses_host_data_mount_when_running_in_container(self):
        client = FakeClient()
        self_container = FakeContainer(
            "runtime-container",
            mounts=[
                {
                    "Type": "bind",
                    "Source": "/host/project/data",
                    "Destination": "/app/data",
                }
            ],
        )
        client.containers._items[self_container.name] = self_container
        real_exists = os.path.exists

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client), patch.object(
            clash_manager.os.path,
            "exists",
            side_effect=lambda path: True if path == "/.dockerenv" else real_exists(path),
        ), patch.object(clash_manager.os, "getenv", side_effect=lambda key, default=None: "runtime-container" if key == "HOSTNAME" else default):
            success, message = clash_manager.deploy_clash_pool(1)

        self.assertTrue(success, message)
        first_call = client.containers.run_calls[0]["kwargs"]
        self.assertEqual(
            {
                "/host/project/data/mihomo-pool/clash_1": {
                    "bind": "/root/.config/mihomo",
                    "mode": "rw",
                }
            },
            first_call["volumes"],
        )


if __name__ == "__main__":
    unittest.main()
