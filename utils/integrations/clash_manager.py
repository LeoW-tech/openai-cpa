import copy
import os

import docker
import requests
import yaml

BASE_PATH = os.path.join(os.getcwd(), "data", "mihomo-pool")
os.makedirs(BASE_PATH, exist_ok=True)

HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", os.getcwd())
HOST_BASE_PATH = os.path.join(HOST_PROJECT_PATH, "data", "mihomo-pool")
MANAGED_SUBSCRIPTION_FILE_REL = os.path.join("data", "mihomo-pool", "subscription-source.yaml")

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


def _pool_group_name():
    return str(_load_runtime_config().get("clash_proxy_pool", {}).get("group_name", "")).strip()


def _pool_sub_file_path():
    raw_value = _load_runtime_config().get("clash_proxy_pool", {}).get("sub_file_path", "")
    value = str(raw_value or "").strip()
    return value or MANAGED_SUBSCRIPTION_FILE_REL


def _instance_name(index):
    return f"clash_{index}"


def _instance_dir(base_path, name):
    return os.path.join(base_path, name)


def _config_file(base_path, name):
    return os.path.join(_instance_dir(base_path, name), "config.yaml")


def _default_config():
    return _apply_runtime_patch(
        {
            "allow-lan": True,
            "mixed-port": INSTANCE_PROXY_PORT,
            "external-controller": f"0.0.0.0:{INSTANCE_CONTROLLER_PORT}",
        }
    )


def _apply_runtime_patch(config):
    patched = copy.deepcopy(config or {})
    patched.update(
        {
            "allow-lan": True,
            "mixed-port": INSTANCE_PROXY_PORT,
            "external-controller": f"0.0.0.0:{INSTANCE_CONTROLLER_PORT}",
        }
    )

    secret = _pool_secret()
    if secret:
        patched["secret"] = secret
    else:
        patched.pop("secret", None)

    return patched


def _load_yaml_file(path):
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return None


def _write_yaml_file(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _resolve_host_path(path):
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.join(HOST_PROJECT_PATH, raw_path)


def _load_yaml_file_strict(path):
    resolved_path = _resolve_host_path(path)
    if not resolved_path:
        raise ValueError("未提供本地订阅文件路径")
    if not os.path.isfile(resolved_path):
        raise FileNotFoundError(f"本地订阅文件不存在: {resolved_path}")

    try:
        with open(resolved_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"本地订阅文件 YAML 解析失败: {resolved_path}") from exc
    except OSError as exc:
        raise ValueError(f"本地订阅文件读取失败: {resolved_path}") from exc

    return loaded or {}


def _is_subscription_config(config):
    if not isinstance(config, dict):
        return False
    groups = config.get("proxy-groups") or []
    return isinstance(groups, list) and len(groups) > 0


def _config_has_target_group(config, group_keyword):
    keyword = str(group_keyword or "").strip()
    if not keyword or not isinstance(config, dict):
        return False

    for group in config.get("proxy-groups") or []:
        group_name = str(group.get("name") or "").strip()
        if keyword in group_name:
            return True

    return False


def _extract_groups(config):
    if not isinstance(config, dict):
        return []

    groups = []
    for group in config.get("proxy-groups") or []:
        proxies = group.get("proxies") or []
        groups.append(
            {
                "name": group.get("name", "N/A"),
                "count": len(proxies) if isinstance(proxies, list) else 0,
                "type": group.get("type", "N/A"),
            }
        )
    return groups


def _instance_sort_key(name):
    try:
        return int(str(name).split("_")[1])
    except Exception:
        return 999999


def _discover_subscription_template(base_path):
    if not os.path.isdir(base_path):
        return None

    candidate_names = sorted(
        [name for name in os.listdir(base_path) if name.startswith("clash_")],
        key=_instance_sort_key,
    )

    for name in candidate_names:
        config = _load_yaml_file(_config_file(base_path, name))
        if _is_subscription_config(config):
            return config

    return None


def _load_managed_subscription_template():
    managed_path = _resolve_host_path(_pool_sub_file_path())
    if not managed_path or not os.path.isfile(managed_path):
        return None

    config = _load_yaml_file_strict(managed_path)
    if not _is_subscription_config(config):
        raise ValueError(f"本地订阅文件缺少 proxy-groups: {managed_path}")
    return config


def _load_subscription_source(*, sub_file_path="", sub_url=""):
    normalized_file_path = str(sub_file_path or "").strip()
    normalized_sub_url = str(sub_url or "").strip()

    if normalized_file_path:
        config = _load_yaml_file_strict(normalized_file_path)
        if not _is_subscription_config(config):
            raise ValueError(
                f"本地订阅文件缺少 proxy-groups: {_resolve_host_path(normalized_file_path)}"
            )
        return config

    if normalized_sub_url:
        headers = {
            "User-Agent": "Clash-meta",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        response = requests.get(normalized_sub_url, headers=headers, timeout=30)
        response.raise_for_status()
        raw_yaml = yaml.safe_load(response.text) or {}
        if not _is_subscription_config(raw_yaml):
            raise ValueError("远程订阅内容缺少 proxy-groups")
        return raw_yaml

    raise ValueError("未提供订阅源")


def _collect_config_health(base_path, instance_names):
    group_keyword = _pool_group_name()
    ordered_names = sorted(list(instance_names), key=_instance_sort_key)
    groups = []
    instance_status = {}
    missing_config = []
    missing_group = []
    with_group = []

    for name in ordered_names:
        cfg_path = _config_file(base_path, name)
        config = _load_yaml_file(cfg_path)
        config_exists = config is not None
        has_subscription_config = _is_subscription_config(config)
        has_target_group = _config_has_target_group(config, group_keyword) if group_keyword else None

        if not groups and has_subscription_config:
            groups = _extract_groups(config)

        if not config_exists:
            missing_config.append(name)
        elif group_keyword and not has_target_group:
            missing_group.append(name)
        elif group_keyword and has_target_group:
            with_group.append(name)

        instance_status[name] = {
            "config_exists": config_exists,
            "has_subscription_config": has_subscription_config,
            "has_target_group": has_target_group,
            "config_path": cfg_path,
        }

    health = {
        "expected_group_name": group_keyword,
        "instances_missing_config": missing_config,
        "instances_missing_group": missing_group,
        "instances_with_target_group": with_group,
        "instances_with_target_group_count": len(with_group),
        "total_instances": len(ordered_names),
    }
    return instance_status, groups, health


def _build_deploy_warning_message(count, health):
    warnings = []

    if health["instances_missing_config"]:
        warnings.append(
            "以下实例缺少配置文件: " + ", ".join(health["instances_missing_config"])
        )

    expected_group = health.get("expected_group_name")
    if expected_group and health["instances_missing_group"]:
        warnings.append(
            f"以下实例尚未包含策略组 '{expected_group}': "
            + ", ".join(health["instances_missing_group"])
            + "，请执行订阅更新"
        )

    message = f"成功同步 {count} 个实例"
    if warnings:
        message += "；警告：" + "；".join(warnings)
    return message


def _ensure_config_file(base_path, name, template_config=None):
    inst_dir = _instance_dir(base_path, name)
    cfg_file = _config_file(base_path, name)
    os.makedirs(inst_dir, exist_ok=True)

    if os.path.isdir(cfg_file):
        raise ValueError(f"{cfg_file} 是目录，无法作为 Mihomo 配置文件使用")

    current_config = _load_yaml_file(cfg_file) if os.path.exists(cfg_file) else None
    should_seed_from_template = template_config is not None and not _is_subscription_config(current_config)

    if should_seed_from_template:
        _write_yaml_file(cfg_file, _apply_runtime_patch(template_config))
    elif current_config is None:
        _write_yaml_file(cfg_file, _default_config())

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

    containers = _sorted_clash_containers(client)
    instance_names = [c.name for c in containers]
    config_status, groups, health = _collect_config_health(BASE_PATH, instance_names)

    instances = []
    for c in containers:
        p_map = c.attrs.get("HostConfig", {}).get("PortBindings", {})
        ports = [f"{b[0]['HostPort']}->{p.split('/')[0]}" for p, b in p_map.items() if b]
        status = config_status.get(c.name, {})
        instances.append(
            {
                "name": c.name,
                "status": c.status,
                "ports": ", ".join(ports),
                "config_exists": status.get("config_exists", False),
                "has_subscription_config": status.get("has_subscription_config", False),
                "has_target_group": status.get("has_target_group"),
            }
        )

    return {"instances": instances, "groups": groups, "health": health}


def deploy_clash_pool(count):
    client = get_client()
    if not client:
        return False, "Docker未就绪"

    host_base_path = _host_base_path(client)
    try:
        template_config = _load_managed_subscription_template()
    except (FileNotFoundError, ValueError) as exc:
        return False, str(exc)

    if template_config is None:
        template_config = _discover_subscription_template(BASE_PATH)

    for container in _sorted_clash_containers(client):
        try:
            if int(container.name.split("_")[1]) > count:
                container.remove(force=True)
        except Exception:
            pass

    for i in range(1, count + 1):
        name = _instance_name(i)
        try:
            _ensure_config_file(BASE_PATH, name, template_config=template_config)
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

    _, _, health = _collect_config_health(
        BASE_PATH,
        [_instance_name(i) for i in range(1, count + 1)],
    )
    return True, _build_deploy_warning_message(count, health)


def patch_and_update(sub_file_path="", sub_url="", target="all"):
    client = get_client()
    if not client:
        return False, "Docker未就绪"

    try:
        raw_yaml = _load_subscription_source(sub_file_path=sub_file_path, sub_url=sub_url)

        containers = _sorted_clash_containers(client)
        if not containers:
            return False, "当前没有 Clash 实例，请先同步实例"

        indices = [int(item.name.split("_")[1]) for item in containers] if target == "all" else [int(target)]

        for i in indices:
            name = _instance_name(i)
            try:
                _ensure_config_file(BASE_PATH, name)
            except ValueError as exc:
                return False, str(exc)

            _write_yaml_file(_config_file(BASE_PATH, name), _apply_runtime_patch(raw_yaml))

            try:
                client.containers.get(name).restart()
            except docker.errors.NotFound:
                return False, f"实例 {name} 不存在，请先同步实例"
            except Exception as exc:
                return False, f"重启实例 {name} 失败: {exc}"

        return True, "订阅已更新并应用补丁"
    except Exception as e:
        return False, str(e)
