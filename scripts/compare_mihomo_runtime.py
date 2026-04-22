#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.integrations.mihomo_runtime_tools import (
    diff_focus_sections,
    load_yaml_config,
    summarize_config,
)


def main():
    parser = argparse.ArgumentParser(description="对比 mac 与 Linux 的 Mihomo 运行态配置差异")
    parser.add_argument("--linux-config", required=True, help="Linux 侧运行态配置文件路径")
    parser.add_argument("--mac-config", required=True, help="mac 侧导出的实际运行配置路径")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式，默认 text",
    )
    args = parser.parse_args()

    linux_config = load_yaml_config(args.linux_config)
    mac_config = load_yaml_config(args.mac_config)
    diff = diff_focus_sections(linux_config, mac_config)

    payload = {
        "linux_summary": summarize_config(linux_config),
        "mac_summary": summarize_config(mac_config),
        "diff": diff,
    }

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("== Linux Summary ==")
    print(json.dumps(payload["linux_summary"], ensure_ascii=False, indent=2))
    print("\n== mac Summary ==")
    print(json.dumps(payload["mac_summary"], ensure_ascii=False, indent=2))
    print("\n== Focus Diff ==")
    print(json.dumps(diff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
