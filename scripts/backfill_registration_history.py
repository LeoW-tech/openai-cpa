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
    parser = argparse.ArgumentParser(description="把现有 accounts 成功账号回填到注册历史分析表")
    parser.add_argument("--limit", type=int, default=None, help="最多回填多少条账号")
    args = parser.parse_args()

    db_manager.init_db()
    inserted = registration_history.backfill_accounts_history(limit=args.limit)
    print(f"registration history backfill inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
