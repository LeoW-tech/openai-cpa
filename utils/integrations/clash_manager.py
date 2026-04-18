import copy
import os

import docker
import requests
import yaml

BASE_PATH = os.path.join(os.getcwd(), "data", "mihomo-pool")
os.makedirs(BASE_PATH, exist_ok=True)

HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", os.getcwd())
HOST_BASE_PATH = os.path.join(HOST_PROJECT_PATH, "data", "mihomo-pool")

IMAGE_NAME = "metacubex/mihomo:latest"
INSTANCE_PROXY_PORT = 7890
INSTANCE_CONTROLLER_PORT = 9090
HOST_PROXY_PORT_BASE = 41000
HOST_CONTROLLER_PORT_BASE = 42000
CONTAINER_CONFIG_DIR = "/root/.config/mihomo"
CONTAINER_DATA_DIR = "/app/data"


def get_client():
    try:
        return docker.from_env()
    except Exception as e:
        print(f"[!] Docker 连接失败: {e}")
        return None


def _runtime_config_path():
    return os.path.join(HOST_PROJECT_PATH, "data", "config.yaml")


def _load_runtime_config():
    cfg_path = _runtime_config_path()
    if not os.path.isfile(cfg_path):
        return {}

    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _pool_secret():
    return str(_load_runtime_config().get("clash_proxy_pool", {}).get("secret", "")).strip()


def _instance_name(index):
    return f"clash_{index}"


def _instance_dir(base_path, name):
    return os.path.join(base_path, name)


def _config_file(base_path, name):
    return os.path.join(_instance_dir(base_path, name), "config.yaml")


def _default_config():
    config = {
        "allow-lan": True,
        "mixed-port": INSTANCE_PROXY_PORT,
        "external-controller": f"0.0.0.0:{INSTANCE_CONTROLLER_PORT}",
    }
    secret = _pool_secret()
    if secret:
        config["secret"] = secret
    return config


def _ensure_config_file(base_path, name):
    inst_dir = _instance_dir(base_path, name)
    cfg_file = _config_file(base_path, name)
    os.makedirs(inst_dir, exist_ok=True)

    if os.path.isdir(cfg_file):
        raise ValueError(f"{cfg_file} 是目录，无法作为 Mihomo 配置文件使用")

    if not os.path.exists(cfg_file):
        with open(cfg_file, "w", encoding="utf-8") as fh:
            yaml.safe_dump(_default_config(), fh, allow_unicode=True, sort_keys=False)

    if not os.path.isfile(cfg_file):
        raise ValueError(f"{cfg_file} 不存在或不可读")

    return inst_dir, cfg_file


def _desired_ports(index):
    return {
        "7890/tcp": HOST_PROXY_PORT_BASE + index,
        "9090/tcp": HOST_CONTROLLER_PORT_BASE + index,
    }


def _is_container_runtime():
    return os.path.exists("/.dockerenv")


def _host_data_dir(client):
    fallback = os.path.join(HOST_PROJECT_PATH, "data")
    if not _is_container_runtime() or client is None:
        return fallback

    hostname = os.getenv("HOSTNAME", "").strip()
    if not hostname:
        return fallback

    try:
        current = client.containers.get(hostname)
    except Exception:
        return fallback

    for mount in current.attrs.get("Mounts") or []:
        if mount.get("Type") != "bind":
            continue
        destination = mount.get("Destination")
        source = mount.get("Source")
        if destination in {CONTAINER_DATA_DIR, os.path.join(os.getcwd(), "data")} and source:
            return source

    return fallback


def _host_base_path(client):
    return os.path.join(_host_data_dir(client), "mihomo-pool")


def _desired_volumes(name, host_base_path):
    return {
        os.path.join(host_base_path, name): {
            "bind": CONTAINER_CONFIG_DIR,
            "mode": "rw",
        }
    }


def _normalize_mounts(container):
    mounts = container.attrs.get("Mounts") or []
    result = []
    for mount in mounts:
        result.append(
            (
                mount.get("Type"),
                mount.get("Source"),
                mount.get("Destination"),
            )
        )
    return result


def _normalize_port_bindings(container):
    bindings = container.attrs.get("HostConfig", {}).get("PortBindings", {}) or {}
    normalized = {}
    for port, entries in bindings.items():
        if entries:
            normalized[port] = int(entries[0]["HostPort"])
    return normalized


def _needs_recreate(container, name, index, host_base_path):
    desired_mount = ("bind", os.path.join(host_base_path, name), CONTAINER_CONFIG_DIR)
    mount_set = set(_normalize_mounts(container))
    if desired_mount not in mount_set:
        return True

    return _normalize_port_bindings(container) != _desired_ports(index)


def _sorted_clash_containers(client):
    containers = client.containers.list(all=True, filters={"name": "clash_"})
    containers = [c for c in containers if c.name.startswith("clash_")]
    containers.sort(key=lambda item: int(item.name.split("_")[1]) if "_" in item.name else 999)
    return containers


def get_pool_status():
    client = get_client()
    if not client:
        return {"instances": [], "groups": [], "error": "Docker 套接字未挂载"}

    instances = []
    for c in _sorted_clash_containers(client):
        p_map = c.attrs.get("HostConfig", {}).get("PortBindings", {})
        ports = [f"{b[0]['HostPort']}->{p.split('/')[0]}" for p, b in p_map.items() if b]
        instances.append({"name": c.name, "status": c.status, "ports": ", ".join(ports)})

    groups = []
    sample_cfg = os.path.join(BASE_PATH, "clash_1", "config.yaml")
    if os.path.isfile(sample_cfg):
        try:
            with open(sample_cfg, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for g in data.get("proxy-groups", []):
                groups.append(
                    {
                        "name": g.get("name", "N/A"),
                        "count": len(g.get("proxies", [])),
                        "type": g.get("type", "N/A"),
                    }
                )
        except Exception:
            pass

    return {"instances": instances, "groups": groups}


def deploy_clash_pool(count):
    client = get_client()
    if not client:
        return False, "Docker未就绪"

    host_base_path = _host_base_path(client)

    for container in _sorted_clash_containers(client):
        try:
            if int(container.name.split("_")[1]) > count:
                container.remove(force=True)
        except Exception:
            pass

    for i in range(1, count + 1):
        name = _instance_name(i)
        try:
            _ensure_config_file(BASE_PATH, name)
        except ValueError as exc:
            return False, str(exc)

        recreate = False
        container = None
        try:
            container = client.containers.get(name)
            recreate = _needs_recreate(container, name, i, host_base_path)
        except docker.errors.NotFound:
            recreate = True

        if container and recreate:
            try:
                container.remove(force=True)
            except Exception as exc:
                return False, f"移除旧实例 {name} 失败: {exc}"
            container = None

        if recreate:
            client.containers.run(
                IMAGE_NAME,
                name=name,
                detach=True,
                restart_policy={"Name": "always"},
                ports=_desired_ports(i),
                volumes=_desired_volumes(name, host_base_path),
            )

    return True, f"成功同步 {count} 个实例"


def patch_and_update(url, target):
    client = get_client()
    if not client:
        return False, "Docker未就绪"

    try:
        headers = {
            "User-Agent": "Clash-meta",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        raw_yaml = yaml.safe_load(response.text) or {}

        containers = _sorted_clash_containers(client)
        if not containers:
            return False, "当前没有 Clash 实例，请先同步实例"

        indices = [int(item.name.split("_")[1]) for item in containers] if target == "all" else [int(target)]
        secret = _pool_secret()

        for i in indices:
            name = _instance_name(i)
            try:
                _ensure_config_file(BASE_PATH, name)
            except ValueError as exc:
                return False, str(exc)

            patched = copy.deepcopy(raw_yaml)
            patched.update(
                {
                    "mixed-port": INSTANCE_PROXY_PORT,
                    "allow-lan": True,
                    "external-controller": f"0.0.0.0:{INSTANCE_CONTROLLER_PORT}",
                }
            )
            if secret:
                patched["secret"] = secret

            with open(_config_file(BASE_PATH, name), "w", encoding="utf-8") as fh:
                yaml.safe_dump(patched, fh, allow_unicode=True, sort_keys=False)

            try:
                client.containers.get(name).restart()
            except docker.errors.NotFound:
                return False, f"实例 {name} 不存在，请先同步实例"
            except Exception as exc:
                return False, f"重启实例 {name} 失败: {exc}"

        return True, "订阅已更新并应用补丁"
    except Exception as e:
        return False, str(e)
