#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.proxy_manager import format_docker_url


TARGETS = [
    "https://openai.com",
    "https://github.com",
    "https://example.com",
]


def extract_route_state(controller_url: str):
    try:
        response = requests.get(f"{controller_url}/proxies", timeout=5)
        response.raise_for_status()
    except Exception as exc:
        return {
            "api_ok": False,
            "api_error": str(exc),
        }

    proxies = response.json().get("proxies", {})
    group = proxies.get("Proxy", {})
    proxy_now = str(group.get("now") or "").strip()
    auto_now = str((proxies.get("Auto") or {}).get("now") or "").strip()
    exit_name = auto_now if proxy_now == "Auto" and auto_now else proxy_now
    exit_proxy = proxies.get(exit_name, {}) if exit_name else {}
    history = exit_proxy.get("history") or []
    last_delay = history[-1].get("delay") if history else None

    return {
        "api_ok": True,
        "proxy_now": proxy_now,
        "auto_now": auto_now,
        "exit_name": exit_name,
        "exit_alive": exit_proxy.get("alive"),
        "exit_delay": last_delay,
    }


def classify_probe_exception(exc: Exception):
    detail = str(exc or "")
    lowered = detail.lower()
    if any(token in lowered for token in ("unexpected eof", "ssleoferror", "unexpected eof while reading")):
        return "ssl_eof", detail
    if any(token in lowered for token in ("timed out", "readtimeout", "connecttimeout")):
        return "timeout", detail
    return "request_error", detail


def probe_target(proxy_url: str, target_url: str):
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        response = requests.get(target_url, proxies=proxies, timeout=8, allow_redirects=False)
        return {
            "target": target_url,
            "result": f"status_{response.status_code}",
            "status_code": response.status_code,
        }
    except Exception as exc:
        result, detail = classify_probe_exception(exc)
        return {
            "target": target_url,
            "result": result,
            "detail": detail,
        }


def build_text_report(rows):
    lines = []
    for row in rows:
        header = (
            f"{row['instance']} | api_ok={row['route_state'].get('api_ok')} | "
            f"Proxy.now={row['route_state'].get('proxy_now', '')} | "
            f"Auto.now={row['route_state'].get('auto_now', '')} | "
            f"exit={row['route_state'].get('exit_name', '')} | "
            f"alive={row['route_state'].get('exit_alive')} | "
            f"delay={row['route_state'].get('exit_delay')}"
        )
        lines.append(header)
        for probe in row["probes"]:
            status = probe.get("result")
            detail = probe.get("detail", "")
            suffix = f" | detail={detail}" if detail else ""
            lines.append(f"  - {probe['target']} => {status}{suffix}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="批量探测 Linux 20 个 Mihomo 实例的当前出口与真实 HTTPS 连通性")
    parser.add_argument("--start", type=int, default=1, help="起始实例编号，默认 1")
    parser.add_argument("--end", type=int, default=20, help="结束实例编号，默认 20")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    args = parser.parse_args()

    rows = []
    for index in range(int(args.start), int(args.end) + 1):
        proxy_url = format_docker_url(f"http://127.0.0.1:{41000 + index}")
        controller_url = format_docker_url(f"http://127.0.0.1:{42000 + index}")
        route_state = extract_route_state(controller_url)
        probes = [probe_target(proxy_url, target) for target in TARGETS]
        rows.append(
            {
                "instance": f"clash_{index}",
                "proxy_url": proxy_url,
                "controller_url": controller_url,
                "route_state": route_state,
                "probes": probes,
            }
        )

    if args.format == "json":
        print(json.dumps({"instances": rows}, ensure_ascii=False, indent=2))
        return

    print(build_text_report(rows))


if __name__ == "__main__":
    main()
