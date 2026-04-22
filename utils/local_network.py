import ipaddress
import urllib.parse
from typing import Any, Dict, List, Optional


DEFAULT_RELAY_PORTS = {
    "sub2api_mode": 38080,
    "cpa_mode": 38317,
}


def _normalize_hostname(hostname: str) -> str:
    return str(hostname or "").strip().lower()


def is_private_ipv4_host(hostname: str) -> bool:
    host = _normalize_hostname(hostname)
    if not host:
        return False
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(parsed.version == 4 and parsed.is_private and not parsed.is_loopback)


def should_use_host_relay(raw_url: str) -> bool:
    parsed = urllib.parse.urlparse(str(raw_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = _normalize_hostname(parsed.hostname or "")
    if not host or host in {"localhost", "host.docker.internal"}:
        return False
    return is_private_ipv4_host(host)


def rewrite_url_for_host_relay(raw_url: str, relay_port: int, relay_host: str = "host.docker.internal") -> str:
    parsed = urllib.parse.urlparse(str(raw_url or "").strip())
    if relay_port <= 0 or not parsed.scheme or not parsed.netloc:
        return str(raw_url or "")
    if not should_use_host_relay(raw_url):
        return str(raw_url or "")
    netloc = relay_host
    if relay_port:
        netloc = f"{relay_host}:{int(relay_port)}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def build_host_relay_specs(config_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    config_obj = config_data or {}
    specs: List[Dict[str, Any]] = []
    for section_name, relay_default in DEFAULT_RELAY_PORTS.items():
        section = config_obj.get(section_name) or {}
        raw_url = str(section.get("api_url") or "").strip()
        if not should_use_host_relay(raw_url):
            continue
        relay_port_value = section.get("host_relay_port", relay_default)
        relay_port = int(relay_port_value or 0)
        if relay_port <= 0:
            continue
        parsed = urllib.parse.urlparse(raw_url)
        default_port = 443 if parsed.scheme == "https" else 80
        target_port = int(parsed.port or default_port)
        specs.append(
            {
                "name": section_name.replace("_mode", ""),
                "target_host": str(parsed.hostname or "").strip(),
                "target_port": target_port,
                "listen_host": "0.0.0.0",
                "listen_port": relay_port,
                "source_url": raw_url,
            }
        )
    return specs
