#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.integrations.mihomo_runtime_tools import (
    OVERLAYABLE_KEYS,
    build_host_test_config,
    dump_yaml_config,
    load_yaml_config,
)


def _parse_overlay_keys(raw_value: str):
    if not raw_value:
        return []
    keys = [item.strip() for item in raw_value.split(",") if item.strip()]
    return [key for key in keys if key in OVERLAYABLE_KEYS]


def main():
    parser = argparse.ArgumentParser(description="生成单实例 host-network Mihomo 对照测试配置")
    parser.add_argument("--source-config", required=True, help="真值源配置路径")
    parser.add_argument("--output-config", required=True, help="输出配置路径")
    parser.add_argument("--overlay-config", help="mac 导出的运行配置路径")
    parser.add_argument(
        "--overlay-keys",
        default="",
        help=(
            "逗号分隔的覆盖字段，允许值: "
            + ", ".join(OVERLAYABLE_KEYS)
        ),
    )
    parser.add_argument("--port", type=int, default=41041, help="HTTP 代理端口")
    parser.add_argument("--socks-port", type=int, default=41042, help="SOCKS5 代理端口")
    parser.add_argument("--controller-port", type=int, default=42041, help="控制器端口")
    parser.add_argument("--log-level", default="debug", help="日志级别")
    args = parser.parse_args()

    source_config = load_yaml_config(args.source_config)
    overlay_config = load_yaml_config(args.overlay_config) if args.overlay_config else None
    overlay_keys = _parse_overlay_keys(args.overlay_keys)

    prepared_config, applied_keys = build_host_test_config(
        source_config,
        overlay_config=overlay_config,
        overlay_keys=overlay_keys,
        port=args.port,
        socks_port=args.socks_port,
        controller_port=args.controller_port,
        log_level=args.log_level,
    )
    dump_yaml_config(args.output_config, prepared_config)

    print(
        json.dumps(
            {
                "output_config": args.output_config,
                "applied_overlay_keys": applied_keys,
                "port": args.port,
                "socks_port": args.socks_port,
                "controller_port": args.controller_port,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
