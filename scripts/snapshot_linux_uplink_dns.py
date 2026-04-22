#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_OUTPUT = Path("/srv/openai-cpa/data/mihomo-pool/runtime-dns-servers.yaml")


def sanitize_dns_servers(values):
    result = []
    seen = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or ":" in value and value.count(":") > 1:
            continue
        if value in {"127.0.0.53", "127.0.0.1", "0.0.0.0"}:
            continue
        parts = value.split(".")
        if len(parts) != 4:
            continue
        if not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def parse_resolvectl_dns_servers(output: str):
    candidates = []
    for line in str(output or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() not in {"Current DNS Server", "DNS Servers"}:
            continue
        candidates.extend(value.strip().split())
    return sanitize_dns_servers(candidates)


def parse_resolv_conf(path: Path):
    candidates = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("nameserver "):
            continue
        candidates.append(stripped.split(None, 1)[1].strip())
    return sanitize_dns_servers(candidates)


def discover_dns_servers():
    try:
        result = subprocess.run(
            ["resolvectl", "status"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        parsed = parse_resolvectl_dns_servers(result.stdout)
        if parsed:
            return parsed, "resolvectl"
    except Exception:
        pass

    fallback_path = Path("/run/systemd/resolve/resolv.conf")
    if fallback_path.is_file():
        parsed = parse_resolv_conf(fallback_path)
        if parsed:
            return parsed, str(fallback_path)

    resolv_path = Path("/etc/resolv.conf")
    if resolv_path.is_file():
        parsed = parse_resolv_conf(resolv_path)
        if parsed:
            return parsed, str(resolv_path)

    return [], "none"


def main():
    parser = argparse.ArgumentParser(description="将 Linux 宿主机 uplink DNS 快照写入 data/mihomo-pool/runtime-dns-servers.yaml")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出文件路径")
    args = parser.parse_args()

    dns_servers, source = discover_dns_servers()
    payload = {
        "source": source,
        "dns_servers": dns_servers,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output_path), **payload}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
