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
        self.managed_sub_rel = Path("data") / "mihomo-pool" / "subscription-source.yaml"
        self.managed_sub_path = self.root / self.managed_sub_rel
        (self.runtime_data_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "clash_proxy_pool": {
                        "secret": "unit-test-secret",
                        "group_name": "Proxy",
                        "sub_file_path": str(self.managed_sub_rel),
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

    def _write_managed_subscription(self, data):
        self.managed_sub_path.parent.mkdir(parents=True, exist_ok=True)
        self.managed_sub_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _sample_subscription(self):
        return {
            "port": 7890,
            "socks-port": 7891,
            "allow-lan": False,
            "external-controller": "127.0.0.1:9000",
            "proxy-groups": [
                {"name": "Proxy", "type": "select", "proxies": ["Auto", "日本W03 | IEPL"]},
                {"name": "Auto", "type": "url-test", "proxies": ["日本W03 | IEPL"]},
            ],
            "proxies": [
                {
                    "name": "日本W03 | IEPL",
                    "type": "ss",
                    "server": "jp03.example.com",
                    "port": 443,
                    "cipher": "aes-256-gcm",
                    "password": "x",
                }
            ],
            "rules": ["DOMAIN-SUFFIX,openai.com,Proxy", "MATCH,DIRECT"],
        }

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
        cfg = yaml.safe_load((self.base_path / "clash_1" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(7890, cfg["mixed-port"])
        self.assertEqual("0.0.0.0:9090", cfg["external-controller"])
        self.assertEqual("unit-test-secret", cfg["secret"])

    def test_apply_runtime_patch_preserves_port_and_socks_port(self):
        with self._patch_paths():
            patched = clash_manager._apply_runtime_patch(self._sample_subscription())

        self.assertEqual(7890, patched["port"])
        self.assertEqual(7891, patched["socks-port"])
        self.assertNotIn("mixed-port", patched)
        self.assertTrue(patched["allow-lan"])
        self.assertEqual("0.0.0.0:9090", patched["external-controller"])
        self.assertEqual("Proxy", patched["proxy-groups"][0]["name"])

    def test_deploy_clash_pool_copies_existing_subscription_template_to_new_instances(self):
        client = FakeClient([FakeContainer("clash_1")])
        clash_1_dir = self.base_path / "clash_1"
        clash_1_dir.mkdir(parents=True, exist_ok=True)
        (clash_1_dir / "config.yaml").write_text(
            yaml.safe_dump(self._sample_subscription(), allow_unicode=True),
            encoding="utf-8",
        )

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(2)

        self.assertTrue(success, message)
        cfg = yaml.safe_load((self.base_path / "clash_2" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(7890, cfg["port"])
        self.assertEqual(7891, cfg["socks-port"])
        self.assertEqual("0.0.0.0:9090", cfg["external-controller"])
        self.assertEqual("Proxy", cfg["proxy-groups"][0]["name"])

    def test_deploy_clash_pool_prefers_managed_subscription_file(self):
        client = FakeClient([FakeContainer("clash_1")])
        managed = self._sample_subscription()
        managed["proxy-groups"][0]["proxies"] = ["Auto", "托管节点"]
        managed["proxy-groups"][1]["proxies"] = ["托管节点"]
        managed["proxies"] = [
            {
                "name": "托管节点",
                "type": "ss",
                "server": "managed.example.com",
                "port": 443,
                "cipher": "aes-256-gcm",
                "password": "y",
            }
        ]
        self._write_managed_subscription(managed)

        clash_1_dir = self.base_path / "clash_1"
        clash_1_dir.mkdir(parents=True, exist_ok=True)
        (clash_1_dir / "config.yaml").write_text(
            yaml.safe_dump(self._sample_subscription(), allow_unicode=True),
            encoding="utf-8",
        )

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(2)

        self.assertTrue(success, message)
        cfg = yaml.safe_load((self.base_path / "clash_2" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual("托管节点", cfg["proxies"][0]["name"])
        self.assertEqual("Proxy", cfg["proxy-groups"][0]["name"])

    def test_deploy_clash_pool_warns_when_target_group_missing_after_sync(self):
        client = FakeClient()

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(1)

        self.assertTrue(success, message)
        self.assertIn("Proxy", message)
        self.assertIn("请执行订阅更新", message)

    def test_deploy_clash_pool_rejects_directory_config_path(self):
        client = FakeClient()
        clash_dir = self.base_path / "clash_1"
        clash_dir.mkdir(parents=True, exist_ok=True)
        (clash_dir / "config.yaml").mkdir()

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.deploy_clash_pool(1)

        self.assertFalse(success)
        self.assertIn("config.yaml", message)

    def test_patch_and_update_writes_secret_and_preserves_ports(self):
        existing = [FakeContainer("clash_1"), FakeContainer("clash_2")]
        client = FakeClient(existing)
        sub_text = yaml.safe_dump(self._sample_subscription(), allow_unicode=True)

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client), patch.object(
            clash_manager.requests, "get", return_value=FakeResponse(sub_text)
        ):
            success, message = clash_manager.patch_and_update(sub_url="https://example.com/sub", target="all")

        self.assertTrue(success, message)
        for name in ("clash_1", "clash_2"):
            cfg = yaml.safe_load((self.base_path / name / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(7890, cfg["port"])
            self.assertEqual(7891, cfg["socks-port"])
            self.assertEqual("0.0.0.0:9090", cfg["external-controller"])
            self.assertEqual("unit-test-secret", cfg["secret"])
            self.assertTrue(client.containers.get(name).restarted)

    def test_patch_and_update_reads_local_subscription_file_and_restarts_instances(self):
        existing = [FakeContainer("clash_1"), FakeContainer("clash_2")]
        client = FakeClient(existing)
        local_sub = self._sample_subscription()
        local_sub["proxies"][0]["name"] = "本地节点"
        local_sub["proxy-groups"][0]["proxies"] = ["Auto", "本地节点"]
        local_sub["proxy-groups"][1]["proxies"] = ["本地节点"]
        self._write_managed_subscription(local_sub)

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.patch_and_update(
                sub_file_path=str(self.managed_sub_rel),
                target="all",
            )

        self.assertTrue(success, message)
        for name in ("clash_1", "clash_2"):
            cfg = yaml.safe_load((self.base_path / name / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual("本地节点", cfg["proxies"][0]["name"])
            self.assertEqual("Proxy", cfg["proxy-groups"][0]["name"])
            self.assertEqual(7890, cfg["port"])
            self.assertTrue(client.containers.get(name).restarted)

    def test_patch_and_update_rejects_missing_local_subscription_file(self):
        client = FakeClient([FakeContainer("clash_1")])

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.patch_and_update(
                sub_file_path="data/mihomo-pool/missing.yaml",
                target="all",
            )

        self.assertFalse(success)
        self.assertIn("本地订阅文件不存在", message)

    def test_patch_and_update_rejects_invalid_local_yaml(self):
        client = FakeClient([FakeContainer("clash_1")])
        self.managed_sub_path.parent.mkdir(parents=True, exist_ok=True)
        self.managed_sub_path.write_text("proxy-groups: [\n", encoding="utf-8")

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.patch_and_update(
                sub_file_path=str(self.managed_sub_rel),
                target="all",
            )

        self.assertFalse(success)
        self.assertIn("YAML 解析失败", message)

    def test_patch_and_update_rejects_local_subscription_without_groups(self):
        client = FakeClient([FakeContainer("clash_1")])
        self._write_managed_subscription({"proxies": []})

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client):
            success, message = clash_manager.patch_and_update(
                sub_file_path=str(self.managed_sub_rel),
                target="all",
            )

        self.assertFalse(success)
        self.assertIn("缺少 proxy-groups", message)

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

    def test_get_pool_status_reports_per_instance_config_health(self):
        existing = [
            FakeContainer("clash_1", ports={"7890/tcp": [{"HostPort": "41001"}], "9090/tcp": [{"HostPort": "42001"}]}),
            FakeContainer("clash_2", ports={"7890/tcp": [{"HostPort": "41002"}], "9090/tcp": [{"HostPort": "42002"}]}),
        ]
        client = FakeClient(existing)

        clash_1_dir = self.base_path / "clash_1"
        clash_1_dir.mkdir(parents=True, exist_ok=True)
        (clash_1_dir / "config.yaml").write_text(
            yaml.safe_dump(self._sample_subscription(), allow_unicode=True),
            encoding="utf-8",
        )

        clash_2_dir = self.base_path / "clash_2"
        clash_2_dir.mkdir(parents=True, exist_ok=True)
        (clash_2_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "allow-lan": True,
                    "port": 7890,
                    "socks-port": 7891,
                    "external-controller": "0.0.0.0:9090",
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        runtime_side_effect = [
            {"controller_api_ok": True, "proxy_port_ok": True},
            {"controller_api_ok": False, "proxy_port_ok": False},
        ]

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client), patch.object(
            clash_manager,
            "_probe_instance_runtime",
            side_effect=runtime_side_effect,
        ):
            result = clash_manager.get_pool_status()

        self.assertEqual(["clash_2"], result["health"]["instances_missing_group"])
        self.assertEqual([], result["health"]["instances_missing_config"])
        self.assertEqual("Proxy", result["health"]["expected_group_name"])
        self.assertEqual(1, result["health"]["instances_with_target_group_count"])
        self.assertEqual("Proxy", result["groups"][0]["name"])
        clash_1_status = next(item for item in result["instances"] if item["name"] == "clash_1")
        clash_2_status = next(item for item in result["instances"] if item["name"] == "clash_2")
        self.assertTrue(clash_1_status["config_exists"])
        self.assertTrue(clash_1_status["has_target_group"])
        self.assertTrue(clash_1_status["controller_api_ok"])
        self.assertTrue(clash_1_status["proxy_port_ok"])
        self.assertTrue(clash_2_status["config_exists"])
        self.assertFalse(clash_2_status["has_target_group"])
        self.assertFalse(clash_2_status["controller_api_ok"])
        self.assertFalse(clash_2_status["proxy_port_ok"])
        self.assertEqual(["clash_2"], result["health"]["instances_api_unreachable"])
        self.assertEqual(["clash_2"], result["health"]["instances_proxy_unreachable"])

    def test_deploy_clash_pool_recreates_unhealthy_instance(self):
        existing = [
            FakeContainer(
                "clash_1",
                ports={"7890/tcp": [{"HostPort": "41001"}], "9090/tcp": [{"HostPort": "42001"}]},
                mounts=[
                    {
                        "Type": "bind",
                        "Source": str(self.base_path / "clash_1"),
                        "Destination": "/root/.config/mihomo",
                    }
                ],
            )
        ]
        client = FakeClient(existing)
        clash_1_dir = self.base_path / "clash_1"
        clash_1_dir.mkdir(parents=True, exist_ok=True)
        (clash_1_dir / "config.yaml").write_text(
            yaml.safe_dump(self._sample_subscription(), allow_unicode=True),
            encoding="utf-8",
        )
        self._write_managed_subscription(self._sample_subscription())

        with self._patch_paths(), patch.object(clash_manager, "get_client", return_value=client), patch.object(
            clash_manager,
            "_probe_instance_runtime",
            return_value={"controller_api_ok": False, "proxy_port_ok": True},
        ):
            success, message = clash_manager.deploy_clash_pool(1)

        self.assertTrue(success, message)
        self.assertTrue(existing[0].removed)
        self.assertEqual(1, len(client.containers.run_calls))


if __name__ == "__main__":
    unittest.main()
