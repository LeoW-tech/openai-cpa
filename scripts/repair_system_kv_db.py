import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    password TEXT,
    token_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS system_kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS local_mailboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    password TEXT,
    client_id TEXT,
    refresh_token TEXT,
    status INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fission_count INTEGER DEFAULT 0,
    retry_master INTEGER DEFAULT 0
);
"""


def _sidecar_paths(source_db: Path) -> list[Path]:
    return [source_db.with_name(f"{source_db.name}-wal"), source_db.with_name(f"{source_db.name}-shm")]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _ensure_not_in_use(source_db: Path) -> None:
    check_paths = [str(source_db)] + [str(p) for p in _sidecar_paths(source_db) if p.exists()]
    result = subprocess.run(
        ["lsof", *check_paths],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        raise RuntimeError("目标数据库仍被占用，请先停止容器或进程后再修复。")


def _backup_files(source_db: Path) -> list[Path]:
    backups: list[Path] = []
    stamp = _timestamp()
    for path in [source_db, *_sidecar_paths(source_db)]:
        if not path.exists():
            continue
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        shutil.copy2(path, backup)
        backups.append(backup)
    return backups


def _copy_table_rows(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, table_name: str) -> int:
    cursor = source_conn.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    columns = [description[0] for description in cursor.description or []]
    if not rows:
        return 0
    placeholders = ", ".join(["?"] * len(columns))
    target_conn.executemany(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        rows,
    )
    return len(rows)


def repair_system_kv_db(source_db: Path, *, output_db: Path | None = None, skip_lock_check: bool = False) -> Path:
    source_db = source_db.resolve()
    if not source_db.exists():
        raise FileNotFoundError(f"数据库不存在: {source_db}")
    if not skip_lock_check:
        _ensure_not_in_use(source_db)
    backups = _backup_files(source_db)
    for backup in backups:
        print(f"已创建备份: {backup}")

    if output_db is None:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="system-kv-repair-", suffix=".db", dir=str(source_db.parent))
        os.close(tmp_fd)
        target_db = Path(tmp_path)
        replace_source = True
    else:
        target_db = output_db.resolve()
        replace_source = False

    if target_db.exists():
        target_db.unlink()

    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)
    try:
        target_conn.executescript(SCHEMA_SQL)
        accounts_count = _copy_table_rows(source_conn, target_conn, "accounts")
        local_mailboxes_count = _copy_table_rows(source_conn, target_conn, "local_mailboxes")
        target_conn.commit()
        integrity = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"重建后的数据库校验失败: {integrity}")
    finally:
        source_conn.close()
        target_conn.close()

    print(f"成功迁移 accounts: {accounts_count}")
    print(f"成功迁移 local_mailboxes: {local_mailboxes_count}")
    print("system_kv 已重建为空")
    print("复用池历史状态已丢弃，将由后续成功号码重新积累")

    if replace_source:
        os.replace(target_db, source_db)
        for sidecar in _sidecar_paths(source_db):
            if sidecar.exists():
                sidecar.unlink()
        return source_db
    return target_db


def main() -> int:
    parser = argparse.ArgumentParser(description="保守修复 system_kv 损坏的 SQLite 数据库")
    parser.add_argument("--source-db", default="data/data.db", help="待修复的 SQLite 数据库路径")
    parser.add_argument("--output-db", default="", help="可选输出路径；不传则原子替换源数据库")
    parser.add_argument("--skip-lock-check", action="store_true", help="跳过数据库占用检查")
    args = parser.parse_args()

    try:
        output_db = Path(args.output_db) if args.output_db else None
        repaired_path = repair_system_kv_db(
            Path(args.source_db),
            output_db=output_db,
            skip_lock_check=bool(args.skip_lock_check),
        )
        print(f"修复完成: {repaired_path}")
        return 0
    except Exception as e:
        print(f"修复失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
