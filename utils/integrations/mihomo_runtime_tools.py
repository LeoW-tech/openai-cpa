import copy
from pathlib import Path

import yaml


FOCUS_KEYS = [
    "port",
    "socks-port",
    "mixed-port",
    "redir-port",
    "tproxy-port",
    "dns",
    "proxy-server-nameserver",
    "default-nameserver",
    "tun",
    "sniffer",
    "hosts",
    "profile",
    "proxy-groups",
    "rules",
    "interface-name",
    "routing-mark",
]

OVERLAYABLE_KEYS = [
    "dns",
    "proxy-server-nameserver",
    "default-nameserver",
    "tun",
    "sniffer",
    "hosts",
    "profile",
    "interface-name",
    "routing-mark",
]


def load_yaml_config(path: str):
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def dump_yaml_config(path: str, config: dict) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, allow_unicode=True, sort_keys=False)


def _normalize_scalar(value):
    if isinstance(value, dict):
        return {key: _normalize_scalar(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_scalar(item) for item in value]
    return value


def _proxy_group_summary(groups):
    rows = []
    for group in groups or []:
        proxies = group.get("proxies") or []
        use = group.get("use") or []
        rows.append(
            {
                "name": group.get("name"),
                "type": group.get("type"),
                "proxy_count": len(proxies) if isinstance(proxies, list) else 0,
                "use_count": len(use) if isinstance(use, list) else 0,
                "url": group.get("url"),
                "interval": group.get("interval"),
            }
        )
    return rows


def summarize_config(config: dict):
    hosts = config.get("hosts") or {}
    rules = config.get("rules") or []
    return {
        "top_level_keys": list(config.keys()),
        "ports": {
            "port": config.get("port"),
            "socks-port": config.get("socks-port"),
            "mixed-port": config.get("mixed-port"),
            "redir-port": config.get("redir-port"),
            "tproxy-port": config.get("tproxy-port"),
        },
        "proxy_group_names": [group.get("name") for group in config.get("proxy-groups", [])],
        "proxy_groups": _proxy_group_summary(config.get("proxy-groups", [])),
        "rule_count": len(rules),
        "rule_head": rules[:20],
        "hosts_count": len(hosts) if isinstance(hosts, dict) else 0,
        "focus_keys_present": [key for key in FOCUS_KEYS if key in config],
    }


def build_focus_view(config: dict):
    view = {}
    for key in FOCUS_KEYS:
        if key in config:
            view[key] = _normalize_scalar(config[key])
    return view


def diff_focus_sections(linux_config: dict, mac_config: dict):
    linux_view = build_focus_view(linux_config)
    mac_view = build_focus_view(mac_config)

    only_in_mac = {}
    only_in_linux = {}
    different = {}

    all_keys = sorted(set(linux_view) | set(mac_view))
    for key in all_keys:
        if key not in linux_view:
            only_in_mac[key] = mac_view[key]
            continue
        if key not in mac_view:
            only_in_linux[key] = linux_view[key]
            continue
        if linux_view[key] != mac_view[key]:
            different[key] = {"linux": linux_view[key], "mac": mac_view[key]}

    return {
        "only_in_mac": only_in_mac,
        "only_in_linux": only_in_linux,
        "different": different,
    }


def build_host_test_config(
    source_config: dict,
    overlay_config: dict | None = None,
    overlay_keys: list[str] | None = None,
    *,
    port: int = 41041,
    socks_port: int = 41042,
    controller_port: int = 42041,
    log_level: str = "debug",
):
    config = copy.deepcopy(source_config or {})

    for key in ["external-controller", "allow-lan", "mixed-port"]:
        config.pop(key, None)

    config["allow-lan"] = True
    config["port"] = int(port)
    config["socks-port"] = int(socks_port)
    config["external-controller"] = f"127.0.0.1:{int(controller_port)}"
    config["log-level"] = str(log_level).strip() or "debug"

    applied_keys = []
    if overlay_config and overlay_keys:
        for key in overlay_keys:
            if key in overlay_config:
                config[key] = copy.deepcopy(overlay_config[key])
                applied_keys.append(key)

    return config, applied_keys
