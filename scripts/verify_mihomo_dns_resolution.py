#!/usr/bin/env python3
import argparse
import ipaddress
import json
import re
import shlex
import sys
import time
from pathlib import Path

import docker
import yaml


DEFAULT_DATA_DIR = Path("/srv/openai-cpa/data/mihomo-pool")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def sanitize_dns_servers(values):
    result = []
    seen = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value.startswith(("https://", "http://", "tls://", "quic://")):
            continue
        host = value.split("#", 1)[0].strip()
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
            continue
        normalized = str(parsed)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_runtime_dns_servers(config):
    candidates = []
    candidates.extend(config.get("default-nameserver") or [])
    candidates.extend(config.get("proxy-server-nameserver") or [])
    dns = config.get("dns") or {}
    if isinstance(dns, dict):
        candidates.extend(dns.get("nameserver") or [])
        candidates.extend(dns.get("fallback") or [])
    return sanitize_dns_servers(candidates)


def extract_servers(config):
    servers = []
    seen = set()
    for proxy in config.get("proxies") or []:
        server = str((proxy or {}).get("server") or "").strip()
        if not server:
            continue
        try:
            ipaddress.ip_address(server)
            continue
        except ValueError:
            pass
        if server in seen:
            continue
        seen.add(server)
        servers.append(server)
    return servers


def decode_output(raw_output):
    if isinstance(raw_output, (bytes, bytearray)):
        return raw_output.decode("utf-8", errors="replace")
    return str(raw_output or "")


def run_exec(container, command):
    started_at = time.perf_counter()
    result = container.exec_run(["/bin/sh", "-lc", command])
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    output = decode_output(getattr(result, "output", b""))
    exit_code = getattr(result, "exit_code", 1)
    return exit_code, output, elapsed_ms


def resolve_host(container, host, dns_servers):
    quoted_host = shlex.quote(host)

    commands = [
        ("getent", f"command -v getent >/dev/null 2>&1 && getent hosts {quoted_host}"),
    ]
    for dns_server in dns_servers:
        quoted_dns = shlex.quote(dns_server)
        commands.append(
            (
                f"nslookup@{dns_server}",
                f"command -v nslookup >/dev/null 2>&1 && nslookup {quoted_host} {quoted_dns}",
            )
        )
        commands.append(
            (
                f"busybox-nslookup@{dns_server}",
                f"command -v busybox >/dev/null 2>&1 && busybox nslookup {quoted_host} {quoted_dns}",
            )
        )

    for executor, command in commands:
        exit_code, output, elapsed_ms = run_exec(container, command)
        if exit_code != 0:
            continue
        resolved_ips = IPV4_PATTERN.findall(output)
        return {
            "host": host,
            "ok": True,
            "executor": executor,
            "elapsed_ms": elapsed_ms,
            "resolved_ips": resolved_ips,
            "output": output.strip(),
        }

    return {
        "host": host,
        "ok": False,
        "executor": "unavailable",
        "elapsed_ms": None,
        "resolved_ips": [],
        "output": "容器内缺少 getent/nslookup/busybox，无法直接验证解析",
    }


def build_text_report(instance, dns_servers, results):
    lines = [
        f"实例: {instance}",
        f"使用的 DNS: {', '.join(dns_servers) if dns_servers else '未从配置中提取到 IPv4 DNS'}",
    ]
    for item in results:
        status = "OK" if item["ok"] else "FAIL"
        ips = ", ".join(item["resolved_ips"]) if item["resolved_ips"] else "-"
        elapsed = f"{item['elapsed_ms']}ms" if item["elapsed_ms"] is not None else "-"
        lines.append(
            f"[{status}] {item['host']} | executor={item['executor']} | elapsed={elapsed} | ips={ips}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="在 Mihomo 实例容器内抽样验证节点域名解析")
    parser.add_argument("--instance", default="clash_1", help="实例容器名，默认 clash_1")
    parser.add_argument("--config", help="实例配置路径，默认 /srv/openai-cpa/data/mihomo-pool/<instance>/config.yaml")
    parser.add_argument("--sample-size", type=int, default=10, help="抽样节点数，默认 10")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_DATA_DIR / args.instance / "config.yaml"
    config = load_yaml(config_path)
    dns_servers = extract_runtime_dns_servers(config)
    all_servers = extract_servers(config)
    sample_hosts = all_servers[: max(1, int(args.sample_size))]

    client = docker.from_env()
    container = client.containers.get(args.instance)
    results = [resolve_host(container, host, dns_servers) for host in sample_hosts]

    payload = {
        "instance": args.instance,
        "config_path": str(config_path),
        "dns_servers": dns_servers,
        "sample_size": len(sample_hosts),
        "results": results,
    }

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(build_text_report(args.instance, dns_servers, results))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
