#!/usr/bin/env python3

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils import db_manager
from utils import registration_history


def main() -> int:
    parser = argparse.ArgumentParser(description="补偿 accounts 中缺失 registration_attempts 的成功记录")
    parser.add_argument("--limit", type=int, default=None, help="最多补偿多少条缺口成功记录")
    args = parser.parse_args()

    db_manager.init_db()
    inserted = registration_history.compensate_missing_success_attempts(limit=args.limit)
    print(f"registration history compensation inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
