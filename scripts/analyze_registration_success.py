#!/usr/bin/env python3

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Python 3.9+ is required for zoneinfo support") from exc


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


UTC = timezone.utc
WAIT_BUCKETS = [
    ("<30s", 0, 30),
    ("30-44s", 30, 45),
    ("45-59s", 45, 60),
    ("60-74s", 60, 75),
    ("75-89s", 75, 90),
    (">=90s", 90, None),
]
KEY_EVENT_TYPES = [
    "attempt_started",
    "proxy_bound",
    "exit_ip_resolved",
    "email_acquired",
    "phone_gate_hit",
    "account_create_completed",
    "account_registered_pending_token",
    "token_wait_scheduled",
    "oauth_callback_submitted",
    "token_received",
    "attempt_finished",
]
FUNNEL_STAGES = [
    ("total", "总尝试"),
    ("email_acquired", "拿到邮箱"),
    ("phone_gate_hit", "命中手机号门槛"),
    ("account_registered_pending_token", "已注册待最终 Token"),
    ("token_wait_scheduled", "已进入 Token 等待"),
    ("success", "最终成功"),
]


@dataclass
class ScriptConfig:
    db_path: Path
    output_dir: Path
    timezone_name: str
    min_sample: int
    unknown_policy: str
    history_scope: str


def parse_args(argv: Optional[list[str]] = None) -> ScriptConfig:
    parser = argparse.ArgumentParser(description="生成注册成功率历史分析报告与明细导出")
    parser.add_argument("--db-path", default="data/data.db", help="SQLite 数据库路径")
    parser.add_argument(
        "--output-dir",
        default="artifacts/registration-analysis/latest",
        help="导出目录",
    )
    parser.add_argument("--timezone", default="Asia/Shanghai", help="展示使用的时区")
    parser.add_argument("--min-sample", type=int, default=30, help="Top/Bottom 段最小样本量")
    parser.add_argument(
        "--unknown-policy",
        choices=["exclude", "include"],
        default="exclude",
        help="unknown 是否进入成功率分母",
    )
    parser.add_argument(
        "--history-scope",
        choices=["all"],
        default="all",
        help="历史范围，目前仅支持 all",
    )
    args = parser.parse_args(argv)
    return ScriptConfig(
        db_path=Path(args.db_path),
        output_dir=Path(args.output_dir),
        timezone_name=str(args.timezone),
        min_sample=max(1, int(args.min_sample)),
        unknown_policy=str(args.unknown_policy),
        history_scope=str(args.history_scope),
    )


def parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_utc_naive(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def convert_utc_naive_to_timezone(value: str, timezone_name: str) -> str:
    dt = parse_utc_naive(value)
    if not dt:
        return ""
    local_dt = dt.astimezone(ZoneInfo(timezone_name))
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def compute_closed_success_rate(
    *,
    total_count: int,
    success_count: int,
    unknown_count: int,
    unknown_policy: str,
) -> float:
    denominator = int(total_count)
    if unknown_policy == "exclude":
        denominator -= int(unknown_count)
    if denominator <= 0:
        return 0.0
    return float(success_count) / float(denominator)


def compute_unknown_rate(*, total_count: int, unknown_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return float(unknown_count) / float(total_count)


def classify_wait_bucket(wait_seconds: Optional[float]) -> str:
    if wait_seconds is None:
        return "no_wait"
    for label, lower, upper in WAIT_BUCKETS:
        if wait_seconds >= lower and (upper is None or wait_seconds < upper):
            return label
    return "no_wait"


def is_transition_period_attempt(
    *,
    started_at_utc: str,
    token_wait_duration_ms: Any,
    run_config: Optional[dict[str, Any]] = None,
    transition_date: str = "2026-04-18",
) -> bool:
    _ = run_config or {}
    if token_wait_duration_ms not in (None, ""):
        return False
    dt = parse_utc_naive(started_at_utc)
    if not dt:
        return False
    return dt.strftime("%Y-%m-%d") == transition_date


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * q
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[int(rank)])
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return float(lower_value + (upper_value - lower_value) * (rank - lower))


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def build_funnel_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = max(0, int(counts.get("total", 0)))
    previous = total
    for stage, stage_label in FUNNEL_STAGES:
        current = max(0, int(counts.get(stage, 0)))
        step_rate = float(current) / float(previous) if previous > 0 else 0.0
        total_rate = float(current) / float(total) if total > 0 else 0.0
        rows.append(
            {
                "stage": stage,
                "stage_label": stage_label,
                "count": current,
                "step_conversion_rate": step_rate,
                "total_conversion_rate": total_rate,
            }
        )
        previous = current
    return rows


def rank_segments(
    segments: list[dict[str, Any]],
    *,
    min_sample: int,
    unknown_policy: str,
    segment_key: str,
) -> dict[str, list[dict[str, Any]]]:
    qualified: list[dict[str, Any]] = []
    unqualified: list[dict[str, Any]] = []
    for row in segments:
        item = dict(row)
        item["eligible_for_ranking"] = int(item.get("total_count", 0)) >= int(min_sample)
        item["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(item.get("total_count")),
            success_count=safe_int(item.get("success_count")),
            unknown_count=safe_int(item.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        item["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(item.get("total_count")),
            unknown_count=safe_int(item.get("unknown_count")),
        )
        item[segment_key] = str(item.get(segment_key) or "").strip()
        if item["eligible_for_ranking"]:
            qualified.append(item)
        else:
            unqualified.append(item)
    qualified.sort(key=lambda x: (-x["closed_success_rate"], -safe_int(x.get("total_count")), x.get(segment_key, "")))
    unqualified.sort(key=lambda x: (-safe_int(x.get("total_count")), x.get(segment_key, "")))
    return {"qualified": qualified, "unqualified": unqualified}


def format_rate(value: float) -> str:
    return f"{value * 100:.2f}%"


def to_markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_无数据_\n"

    def normalize_cell(value: Any) -> str:
        text = str(value if value not in (None, "") else "(空)")
        return text.replace("|", "\\|")

    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(normalize_cell(row.get(key, "")) for key, _ in columns) + " |")
    return "\n".join([header, divider] + body) + "\n"


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_attempt_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sql = """
        SELECT
            a.*,
            r.config_snapshot_json AS run_config_snapshot_json,
            r.started_at AS run_started_at_utc,
            r.ended_at AS run_ended_at_utc,
            r.source_mode AS run_source_mode
        FROM registration_attempts a
        LEFT JOIN registration_runs r ON r.id = a.run_id
        ORDER BY a.id ASC
    """
    return [dict(row) for row in conn.execute(sql).fetchall()]


def fetch_event_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sql = """
        SELECT
            attempt_id,
            seq_no,
            event_type,
            phase,
            occurred_at,
            elapsed_ms,
            ok_flag,
            http_status,
            reason_code,
            message
        FROM registration_attempt_events
        ORDER BY attempt_id ASC, seq_no ASC, id ASC
    """
    return [dict(row) for row in conn.execute(sql).fetchall()]


def build_event_summary(event_rows: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    by_attempt: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        by_attempt[safe_int(row.get("attempt_id"))].append(row)

    event_summary: dict[int, dict[str, Any]] = {}
    event_paths: Counter[str] = Counter()
    for attempt_id, rows in by_attempt.items():
        counts = Counter()
        key_path: list[str] = []
        seen_in_path: set[str] = set()
        first_at = rows[0].get("occurred_at") if rows else ""
        last_at = rows[-1].get("occurred_at") if rows else ""
        for row in rows:
            event_type = str(row.get("event_type") or "").strip()
            if not event_type:
                continue
            counts[event_type] += 1
            if event_type in KEY_EVENT_TYPES and event_type not in seen_in_path:
                key_path.append(event_type)
                seen_in_path.add(event_type)
        path = " > ".join(key_path) if key_path else ""
        if path:
            event_paths[path] += 1
        event_summary[attempt_id] = {
            "event_count": len(rows),
            "first_event_at_utc": str(first_at or ""),
            "last_event_at_utc": str(last_at or ""),
            "event_path": path,
            "event_counts": dict(counts),
            "token_wait_scheduled_events": counts.get("token_wait_scheduled", 0),
            "account_registered_pending_token_events": counts.get("account_registered_pending_token", 0),
            "token_received_events": counts.get("token_received", 0),
            "attempt_finished_events": counts.get("attempt_finished", 0),
        }

    top_paths = [
        {"event_path": path, "count": count}
        for path, count in event_paths.most_common(20)
    ]
    return event_summary, top_paths


def enrich_attempts(
    attempts: list[dict[str, Any]],
    event_summary: dict[int, dict[str, Any]],
    *,
    timezone_name: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in attempts:
        item = dict(row)
        run_config = parse_json(item.get("run_config_snapshot_json"))
        started_at_utc = str(item.get("started_at") or "")
        finished_at_utc = str(item.get("finished_at") or "")
        started_at_local = convert_utc_naive_to_timezone(started_at_utc, timezone_name)
        finished_at_local = convert_utc_naive_to_timezone(finished_at_utc, timezone_name)
        total_count = 1
        success_flag = 1 if safe_int(item.get("success_flag")) == 1 else 0
        final_status = str(item.get("final_status") or "").strip() or "unknown"
        is_unknown = 1 if final_status == "unknown" else 0
        is_closed = 0 if is_unknown else 1
        wait_ms = safe_int(item.get("token_wait_duration_ms")) if item.get("token_wait_duration_ms") not in (None, "") else None
        wait_seconds = (wait_ms / 1000.0) if wait_ms is not None else None
        has_wait = 1 if wait_ms is not None else 0
        has_wait_config = int(run_config.get("login_delay_min") is not None and run_config.get("login_delay_max") is not None)
        account_registered = 1 if safe_int(item.get("account_registered_flag")) == 1 else 0

        if account_registered and has_wait:
            register_stage = "registered_waited"
        elif account_registered and not has_wait:
            register_stage = "registered_not_waited"
        elif is_unknown:
            register_stage = "not_registered_unknown"
        else:
            register_stage = "not_registered"

        item.update(
            {
                "total_count": total_count,
                "success_count": success_flag,
                "failed_count": 1 if final_status == "failed" else 0,
                "unknown_count": is_unknown,
                "closed_count": is_closed,
                "is_success": success_flag,
                "is_closed": is_closed,
                "is_unknown": is_unknown,
                "has_token_wait": has_wait,
                "wait_seconds": wait_seconds,
                "wait_bucket": classify_wait_bucket(wait_seconds),
                "register_stage": register_stage,
                "started_at_utc": started_at_utc,
                "finished_at_utc": finished_at_utc,
                "started_at_local": started_at_local,
                "finished_at_local": finished_at_local,
                "started_day_local": started_at_local[:10] if started_at_local else "",
                "started_hour_local": started_at_local[:13] if started_at_local else "",
                "run_config": run_config,
                "login_delay_min": safe_int(run_config.get("login_delay_min")) if run_config.get("login_delay_min") is not None else None,
                "login_delay_max": safe_int(run_config.get("login_delay_max")) if run_config.get("login_delay_max") is not None else None,
                "has_wait_config": has_wait_config,
                "account_registered_count": account_registered,
                "phone_gate_hit_count": 1 if safe_int(item.get("phone_gate_hit_flag")) == 1 else 0,
                "email_acquired_count": 1 if str(item.get("email_full") or "").strip() else 0,
                "token_wait_scheduled_count": has_wait,
                "legacy_backfill_count": 1 if safe_int(item.get("legacy_backfill")) == 1 else 0,
                "missing_exit_ip_count": 1 if not str(item.get("exit_ip") or "").strip() else 0,
                "missing_geo_count": 1 if not str(item.get("geo_country_name") or "").strip() else 0,
            }
        )
        item["transition_period_flag"] = 1 if is_transition_period_attempt(
            started_at_utc=started_at_utc,
            token_wait_duration_ms=item.get("token_wait_duration_ms"),
            run_config=run_config,
        ) else 0
        item["config_range_match"] = 1 if has_wait and has_wait_config and item["login_delay_min"] <= wait_seconds <= item["login_delay_max"] else 0
        item["config_range_miss"] = 1 if has_wait and has_wait_config and not item["config_range_match"] else 0

        attempt_id = safe_int(item.get("id"))
        summary = event_summary.get(attempt_id, {})
        item["event_count"] = safe_int(summary.get("event_count"))
        item["event_path"] = str(summary.get("event_path") or "")
        item["first_event_at_utc"] = str(summary.get("first_event_at_utc") or "")
        item["last_event_at_utc"] = str(summary.get("last_event_at_utc") or "")
        item["token_received_events"] = safe_int(summary.get("token_received_events"))
        item["attempt_finished_events"] = safe_int(summary.get("attempt_finished_events"))
        enriched.append(item)
    return enriched


def aggregate_records(
    records: list[dict[str, Any]],
    *,
    key_fields: list[str],
    value_fields: Optional[dict[str, str]] = None,
    unknown_policy: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    total_records = len(records)
    for row in records:
        key = tuple(row.get(field) for field in key_fields)
        if key not in grouped:
            base = {field: row.get(field) for field in key_fields}
            base.update(
                {
                    "total_count": 0,
                    "closed_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "unknown_count": 0,
                    "account_registered_count": 0,
                    "token_wait_scheduled_count": 0,
                    "phone_gate_hit_count": 0,
                    "email_acquired_count": 0,
                    "legacy_backfill_count": 0,
                    "missing_exit_ip_count": 0,
                    "missing_geo_count": 0,
                    "transition_period_count": 0,
                }
            )
            if value_fields:
                for field_name in value_fields:
                    base[field_name] = 0
            grouped[key] = base
        item = grouped[key]
        item["total_count"] += safe_int(row.get("total_count", 1))
        item["closed_count"] += safe_int(row.get("closed_count"))
        item["success_count"] += safe_int(row.get("success_count"))
        item["failed_count"] += safe_int(row.get("failed_count"))
        item["unknown_count"] += safe_int(row.get("unknown_count"))
        item["account_registered_count"] += safe_int(row.get("account_registered_count"))
        item["token_wait_scheduled_count"] += safe_int(row.get("token_wait_scheduled_count"))
        item["phone_gate_hit_count"] += safe_int(row.get("phone_gate_hit_count"))
        item["email_acquired_count"] += safe_int(row.get("email_acquired_count"))
        item["legacy_backfill_count"] += safe_int(row.get("legacy_backfill_count"))
        item["missing_exit_ip_count"] += safe_int(row.get("missing_exit_ip_count"))
        item["missing_geo_count"] += safe_int(row.get("missing_geo_count"))
        item["transition_period_count"] += safe_int(row.get("transition_period_flag"))
        if value_fields:
            for field_name, source_key in value_fields.items():
                item[field_name] += safe_int(row.get(source_key))

    rows = list(grouped.values())
    rows.sort(key=lambda item: (-safe_int(item.get("total_count")),) + tuple(str(item.get(field) or "") for field in key_fields))
    running_total = 0
    for row in rows:
        row["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(row.get("total_count")),
            success_count=safe_int(row.get("success_count")),
            unknown_count=safe_int(row.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        row["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(row.get("total_count")),
            unknown_count=safe_int(row.get("unknown_count")),
        )
        running_total += safe_int(row.get("total_count"))
        row["cumulative_share"] = float(running_total) / float(total_records) if total_records > 0 else 0.0
    return rows


def aggregate_wait_segments(records: list[dict[str, Any]], *, segment_name: str, segment_value_key: str, unknown_policy: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in records:
        segment_value = str(row.get(segment_value_key) or "").strip()
        if segment_name == "run_id":
            segment_value = str(safe_int(row.get(segment_value_key)))
        if segment_value_key == "started_hour_local":
            segment_value = str(row.get("started_hour_local") or "")
        if segment_value not in grouped:
            grouped[segment_value] = {
                "dimension": segment_name,
                "segment": segment_value,
                "total_count": 0,
                "closed_count": 0,
                "success_count": 0,
                "unknown_count": 0,
                "wait_values": [],
                "config_range_miss_count": 0,
            }
        item = grouped[segment_value]
        item["total_count"] += 1
        item["closed_count"] += safe_int(row.get("closed_count"))
        item["success_count"] += safe_int(row.get("success_count"))
        item["unknown_count"] += safe_int(row.get("unknown_count"))
        item["config_range_miss_count"] += safe_int(row.get("config_range_miss"))
        if row.get("wait_seconds") is not None:
            item["wait_values"].append(float(row["wait_seconds"]))

    results: list[dict[str, Any]] = []
    for item in grouped.values():
        waits = list(item.pop("wait_values"))
        item["avg_wait_seconds"] = round(sum(waits) / len(waits), 2) if waits else 0.0
        item["median_wait_seconds"] = round(median(waits), 2) if waits else 0.0
        item["p25_wait_seconds"] = round(percentile(waits, 0.25), 2) if waits else 0.0
        item["p75_wait_seconds"] = round(percentile(waits, 0.75), 2) if waits else 0.0
        item["min_wait_seconds"] = round(min(waits), 2) if waits else 0.0
        item["max_wait_seconds"] = round(max(waits), 2) if waits else 0.0
        item["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(item.get("total_count")),
            success_count=safe_int(item.get("success_count")),
            unknown_count=safe_int(item.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        item["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(item.get("total_count")),
            unknown_count=safe_int(item.get("unknown_count")),
        )
        results.append(item)
    results.sort(key=lambda row: (-safe_int(row.get("total_count")), row.get("dimension", ""), row.get("segment", "")))
    return results


def aggregate_wait_buckets(records: list[dict[str, Any]], *, unknown_policy: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in records:
        bucket = str(row.get("wait_bucket") or "no_wait")
        grouped.setdefault(
            bucket,
            {
                "wait_bucket": bucket,
                "total_count": 0,
                "closed_count": 0,
                "success_count": 0,
                "unknown_count": 0,
                "account_registered_count": 0,
            },
        )
        item = grouped[bucket]
        item["total_count"] += 1
        item["closed_count"] += safe_int(row.get("closed_count"))
        item["success_count"] += safe_int(row.get("success_count"))
        item["unknown_count"] += safe_int(row.get("unknown_count"))
        item["account_registered_count"] += safe_int(row.get("account_registered_count"))

    order = ["no_wait", "<30s", "30-44s", "45-59s", "60-74s", "75-89s", ">=90s"]
    rows = list(grouped.values())
    for row in rows:
        row["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(row.get("total_count")),
            success_count=safe_int(row.get("success_count")),
            unknown_count=safe_int(row.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        row["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(row.get("total_count")),
            unknown_count=safe_int(row.get("unknown_count")),
        )
    rows.sort(key=lambda row: order.index(row["wait_bucket"]) if row["wait_bucket"] in order else 999)
    return rows


def aggregate_failure_breakdown(records: list[dict[str, Any]], *, unknown_policy: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in records:
        stage = str(row.get("failure_stage") or "").strip()
        code = str(row.get("failure_code") or "").strip()
        http_status = str(row.get("last_http_status") or "").strip()
        key = (stage, code, http_status)
        if key not in grouped:
            grouped[key] = {
                "failure_stage": stage,
                "failure_code": code,
                "last_http_status": http_status,
                "total_count": 0,
                "closed_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "unknown_count": 0,
            }
        item = grouped[key]
        item["total_count"] += 1
        item["closed_count"] += safe_int(row.get("closed_count"))
        item["success_count"] += safe_int(row.get("success_count"))
        item["failed_count"] += safe_int(row.get("failed_count"))
        item["unknown_count"] += safe_int(row.get("unknown_count"))

    rows = list(grouped.values())
    rows.sort(key=lambda row: (-safe_int(row.get("total_count")), row.get("failure_stage", ""), row.get("failure_code", "")))
    for row in rows:
        row["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(row.get("total_count")),
            success_count=safe_int(row.get("success_count")),
            unknown_count=safe_int(row.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        row["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(row.get("total_count")),
            unknown_count=safe_int(row.get("unknown_count")),
        )
    return rows


def aggregate_runs(records: list[dict[str, Any]], *, unknown_policy: str) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for row in records:
        run_id = safe_int(row.get("run_id"))
        if run_id not in grouped:
            grouped[run_id] = {
                "run_id": run_id,
                "source_mode": str(row.get("source_mode") or row.get("run_source_mode") or "").strip(),
                "run_started_at_utc": str(row.get("run_started_at_utc") or ""),
                "run_ended_at_utc": str(row.get("run_ended_at_utc") or ""),
                "login_delay_min": row.get("login_delay_min"),
                "login_delay_max": row.get("login_delay_max"),
                "total_count": 0,
                "closed_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "unknown_count": 0,
                "account_registered_count": 0,
                "token_wait_scheduled_count": 0,
            }
        item = grouped[run_id]
        item["total_count"] += 1
        item["closed_count"] += safe_int(row.get("closed_count"))
        item["success_count"] += safe_int(row.get("success_count"))
        item["failed_count"] += safe_int(row.get("failed_count"))
        item["unknown_count"] += safe_int(row.get("unknown_count"))
        item["account_registered_count"] += safe_int(row.get("account_registered_count"))
        item["token_wait_scheduled_count"] += safe_int(row.get("token_wait_scheduled_count"))
    rows = list(grouped.values())
    rows.sort(key=lambda row: (-safe_int(row.get("total_count")), safe_int(row.get("run_id"))))
    for row in rows:
        row["closed_success_rate"] = compute_closed_success_rate(
            total_count=safe_int(row.get("total_count")),
            success_count=safe_int(row.get("success_count")),
            unknown_count=safe_int(row.get("unknown_count")),
            unknown_policy=unknown_policy,
        )
        row["unknown_rate"] = compute_unknown_rate(
            total_count=safe_int(row.get("total_count")),
            unknown_count=safe_int(row.get("unknown_count")),
        )
    return rows


def build_top_segments(
    dimension_rows: dict[str, list[dict[str, Any]]],
    *,
    min_sample: int,
    unknown_policy: str,
) -> list[dict[str, Any]]:
    top_segments: list[dict[str, Any]] = []
    for dimension, rows in dimension_rows.items():
        normalized = []
        for row in rows:
            item = dict(row)
            item["segment"] = str(
                item.get(dimension)
                or item.get("geo_isp_asn")
                or item.get("started_hour_local")
                or item.get("run_id")
                or ""
            ).strip()
            normalized.append(item)
        ranked = rank_segments(
            normalized,
            min_sample=min_sample,
            unknown_policy=unknown_policy,
            segment_key="segment",
        )
        qualified = [row for row in ranked["qualified"] if str(row.get("segment") or "").strip()]
        best = qualified[:5]
        worst = sorted(
            qualified,
            key=lambda x: (x["closed_success_rate"], -safe_int(x.get("total_count")), x["segment"]),
        )[:5]
        for direction, items in (("top", best), ("bottom", worst)):
            for index, item in enumerate(items, start=1):
                top_segments.append(
                    {
                        "dimension": dimension,
                        "direction": direction,
                        "rank": index,
                        "segment": item.get("segment", ""),
                        "total_count": safe_int(item.get("total_count")),
                        "success_count": safe_int(item.get("success_count")),
                        "unknown_count": safe_int(item.get("unknown_count")),
                        "closed_success_rate": item.get("closed_success_rate", 0.0),
                        "unknown_rate": item.get("unknown_rate", 0.0),
                    }
                )
    top_segments.sort(key=lambda row: (row["dimension"], row["direction"], row["rank"]))
    return top_segments


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: Optional[list[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        fieldnames = keys
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_segment_rows(rows: list[dict[str, Any]], *, label_key: str, top_n: int = 10) -> list[dict[str, Any]]:
    table_rows = []
    for row in rows[:top_n]:
        table_rows.append(
            {
                label_key: row.get(label_key, ""),
                "样本": safe_int(row.get("total_count")),
                "成功": safe_int(row.get("success_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
                "累计占比": format_rate(float(row.get("cumulative_share", 0.0))),
            }
        )
    return table_rows


def build_report(
    *,
    summary: dict[str, Any],
    overview_rows: list[dict[str, Any]],
    by_day: list[dict[str, Any]],
    by_hour: list[dict[str, Any]],
    by_run: list[dict[str, Any]],
    by_proxy: list[dict[str, Any]],
    by_exit_ip: list[dict[str, Any]],
    by_country: list[dict[str, Any]],
    by_region: list[dict[str, Any]],
    by_isp_asn: list[dict[str, Any]],
    wait_buckets: list[dict[str, Any]],
    wait_by_segment: list[dict[str, Any]],
    failure_breakdown: list[dict[str, Any]],
    funnel_rows: list[dict[str, Any]],
    top_segments: list[dict[str, Any]],
    event_paths: list[dict[str, Any]],
) -> str:
    overview = overview_rows[0] if overview_rows else {}
    by_day_display = []
    for row in by_day:
        by_day_display.append(
            {
                "日期": row.get("started_day_local", ""),
                "样本": safe_int(row.get("total_count")),
                "成功": safe_int(row.get("success_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
                "已注册": safe_int(row.get("account_registered_count")),
                "已等待": safe_int(row.get("token_wait_scheduled_count")),
                "过渡期样本": safe_int(row.get("transition_period_count")),
            }
        )
    by_hour_display = []
    for row in by_hour[:12]:
        by_hour_display.append(
            {
                "小时": row.get("started_hour_local", ""),
                "样本": safe_int(row.get("total_count")),
                "成功": safe_int(row.get("success_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
            }
        )
    by_run_display = []
    for row in by_run[:10]:
        by_run_display.append(
            {
                "Run": row.get("run_id", ""),
                "样本": safe_int(row.get("total_count")),
                "成功": safe_int(row.get("success_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
                "等待配置": f"{row.get('login_delay_min', '')}-{row.get('login_delay_max', '')}",
            }
        )
    wait_bucket_display = []
    for row in wait_buckets:
        wait_bucket_display.append(
            {
                "等待桶": row.get("wait_bucket", ""),
                "样本": safe_int(row.get("total_count")),
                "成功": safe_int(row.get("success_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
            }
        )
    funnel_display = []
    for row in funnel_rows:
        funnel_display.append(
            {
                "阶段": row.get("stage_label", ""),
                "数量": safe_int(row.get("count")),
                "环比转化": format_rate(float(row.get("step_conversion_rate", 0.0))),
                "总转化": format_rate(float(row.get("total_conversion_rate", 0.0))),
            }
        )
    failure_display = []
    for row in failure_breakdown[:10]:
        failure_display.append(
            {
                "failure_stage": row.get("failure_stage", ""),
                "failure_code": row.get("failure_code", ""),
                "HTTP": row.get("last_http_status", ""),
                "样本": safe_int(row.get("total_count")),
                "Unknown 占比": format_rate(float(row.get("unknown_rate", 0.0))),
            }
        )
    event_path_display = []
    for row in event_paths[:10]:
        event_path_display.append(
            {
                "路径": row.get("event_path", ""),
                "出现次数": safe_int(row.get("count")),
            }
        )
    top_segment_display = []
    for row in top_segments[:12]:
        top_segment_display.append(
            {
                "维度": row.get("dimension", ""),
                "方向": row.get("direction", ""),
                "分组": row.get("segment", ""),
                "样本": safe_int(row.get("total_count")),
                "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
            }
        )

    lines = [
        "# 注册成功率历史分析报告",
        "",
        "## 分析口径",
        "",
        f"- 分析窗口：全量历史，原始 UTC 记录跨度 `{summary['analysis_window']['min_started_at_utc']}` 到 `{summary['analysis_window']['max_started_at_utc']}`。",
        f"- 展示时区：`{summary['config']['timezone']}`，图表/分组按本地时区展示，CSV 保留原始 UTC 字段。",
        f"- 主成功率口径：`unknown_policy = {summary['config']['unknown_policy']}`，即 `final_status = unknown` 不进入主成功率分母，但单独展示 unknown 数量与占比。",
        f"- Token 等待主窗口：从 `{summary['analysis_window']['post_wait_window_start_utc']}` 开始；`2026-04-18` 被标记为过渡期，不和等待时长窗口混算。",
        "",
        "## 总览",
        "",
        f"- 总尝试数：{safe_int(overview.get('total_count'))}",
        f"- 已完结数：{safe_int(overview.get('closed_count'))}",
        f"- 成功数：{safe_int(overview.get('success_count'))}",
        f"- 失败数：{safe_int(overview.get('failed_count'))}",
        f"- Unknown 数：{safe_int(overview.get('unknown_count'))}",
        f"- Closed 成功率：{format_rate(float(overview.get('closed_success_rate', 0.0)))}",
        f"- Unknown 占比：{format_rate(float(overview.get('unknown_rate', 0.0)))}",
        f"- 已注册待最终 Token：{safe_int(overview.get('account_registered_count'))}",
        f"- 已进入 Token 等待：{safe_int(overview.get('token_wait_scheduled_count'))}",
        "",
        "## 成功率随时间分布",
        "",
        to_markdown_table(
            by_day_display,
            [
                ("日期", "日期"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
                ("已注册", "已注册"),
                ("已等待", "已等待"),
                ("过渡期样本", "过渡期样本"),
            ],
        ),
        "",
        "### 小时分布（前 12 个高样本小时）",
        "",
        to_markdown_table(
            sorted(by_hour_display, key=lambda row: -safe_int(row.get("样本")))[:12],
            [
                ("小时", "小时"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
            ],
        ),
        "",
        "### Run 分布（前 10 个高样本 Run）",
        "",
        to_markdown_table(
            by_run_display,
            [
                ("Run", "Run"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
                ("等待配置", "等待配置"),
            ],
        ),
        "",
        "## IP 与出口分布",
        "",
        "### Proxy Top 10",
        "",
        to_markdown_table(
            markdown_segment_rows(by_proxy, label_key="proxy_name"),
            [
                ("proxy_name", "Proxy"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
                ("累计占比", "累计占比"),
            ],
        ),
        "",
        "### Exit IP Top 10",
        "",
        to_markdown_table(
            markdown_segment_rows(by_exit_ip, label_key="exit_ip"),
            [
                ("exit_ip", "Exit IP"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
                ("累计占比", "累计占比"),
            ],
        ),
        "",
        "### Country Top 10",
        "",
        to_markdown_table(
            markdown_segment_rows(by_country, label_key="geo_country_name"),
            [
                ("geo_country_name", "国家"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
                ("累计占比", "累计占比"),
            ],
        ),
        "",
        "## Token 等待时间分布",
        "",
        to_markdown_table(
            wait_bucket_display,
            [
                ("等待桶", "等待桶"),
                ("样本", "样本"),
                ("成功", "成功"),
                ("Closed 成功率", "Closed 成功率"),
                ("Unknown 占比", "Unknown 占比"),
            ],
        ),
        "",
        "### Token 等待分组摘要（前 12 条）",
        "",
        to_markdown_table(
            [
                {
                    "维度": row.get("dimension", ""),
                    "分组": row.get("segment", ""),
                    "样本": safe_int(row.get("total_count")),
                    "平均等待(s)": row.get("avg_wait_seconds", 0.0),
                    "P50(s)": row.get("median_wait_seconds", 0.0),
                    "Closed 成功率": format_rate(float(row.get("closed_success_rate", 0.0))),
                    "越界数": safe_int(row.get("config_range_miss_count")),
                }
                for row in wait_by_segment[:12]
            ],
            [
                ("维度", "维度"),
                ("分组", "分组"),
                ("样本", "样本"),
                ("平均等待(s)", "平均等待(s)"),
                ("P50(s)", "P50(s)"),
                ("Closed 成功率", "Closed 成功率"),
                ("越界数", "越界数"),
            ],
        ),
        "",
        "## 注册漏斗与中间态",
        "",
        to_markdown_table(
            funnel_display,
            [
                ("阶段", "阶段"),
                ("数量", "数量"),
                ("环比转化", "环比转化"),
                ("总转化", "总转化"),
            ],
        ),
        "",
        f"- 已注册但未等待：{safe_int(summary['intermediate_states']['registered_not_waited'])}",
        f"- 已等待但未成功：{safe_int(summary['intermediate_states']['waited_not_success'])}",
        f"- 未完结 unknown：{safe_int(summary['intermediate_states']['unknown_attempts'])}",
        "",
        "## 失败与卡点归因",
        "",
        to_markdown_table(
            failure_display,
            [
                ("failure_stage", "failure_stage"),
                ("failure_code", "failure_code"),
                ("HTTP", "HTTP"),
                ("样本", "样本"),
                ("Unknown 占比", "Unknown 占比"),
            ],
        ),
        "",
        "### 高频事件路径",
        "",
        to_markdown_table(
            event_path_display,
            [
                ("路径", "路径"),
                ("出现次数", "出现次数"),
            ],
        ),
        "",
        "## 数据质量与覆盖审计",
        "",
        f"- legacy backfill 记录数：{safe_int(summary['data_quality']['legacy_backfill_count'])}",
        f"- 缺失 exit_ip 记录数：{safe_int(summary['data_quality']['missing_exit_ip_count'])}",
        f"- 缺失 geo 记录数：{safe_int(summary['data_quality']['missing_geo_count'])}",
        f"- 没有 finished_at 的记录数：{safe_int(summary['data_quality']['unfinished_count'])}",
        f"- 覆盖过渡期（2026-04-18）记录数：{safe_int(summary['data_quality']['transition_period_count'])}",
        "",
        "## Top / Bottom 段摘录",
        "",
        to_markdown_table(
            top_segment_display,
            [
                ("维度", "维度"),
                ("方向", "方向"),
                ("分组", "分组"),
                ("样本", "样本"),
                ("Closed 成功率", "Closed 成功率"),
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def infer_snapshot_date(timezone_name: str) -> str:
    now_local = datetime.now(ZoneInfo(timezone_name))
    return now_local.strftime("%Y-%m-%d")


def main(argv: Optional[list[str]] = None) -> int:
    config = parse_args(argv)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if not config.db_path.exists():
        raise SystemExit(f"数据库不存在: {config.db_path}")

    with connect_db(config.db_path) as conn:
        attempts = fetch_attempt_rows(conn)
        event_rows = fetch_event_rows(conn)

    event_summary, event_paths = build_event_summary(event_rows)
    enriched = enrich_attempts(attempts, event_summary, timezone_name=config.timezone_name)
    post_wait_attempts = [
        row for row in enriched
        if row.get("has_token_wait") == 1 and row.get("has_wait_config") == 1
    ]

    by_day = aggregate_records(
        enriched,
        key_fields=["started_day_local"],
        unknown_policy=config.unknown_policy,
    )
    by_day.sort(key=lambda row: row.get("started_day_local", ""))
    by_hour = aggregate_records(
        enriched,
        key_fields=["started_hour_local"],
        unknown_policy=config.unknown_policy,
    )
    by_hour.sort(key=lambda row: row.get("started_hour_local", ""))
    by_run = aggregate_runs(enriched, unknown_policy=config.unknown_policy)
    by_proxy = aggregate_records(
        enriched,
        key_fields=["proxy_name"],
        unknown_policy=config.unknown_policy,
    )
    by_exit_ip = aggregate_records(
        enriched,
        key_fields=["exit_ip"],
        unknown_policy=config.unknown_policy,
    )
    by_country = aggregate_records(
        enriched,
        key_fields=["geo_country_name"],
        unknown_policy=config.unknown_policy,
    )
    by_region = aggregate_records(
        enriched,
        key_fields=["geo_region_name"],
        unknown_policy=config.unknown_policy,
    )
    isp_asn_records = []
    for row in enriched:
        item = dict(row)
        isp = str(item.get("geo_isp") or "").strip()
        asn = str(item.get("geo_asn") or "").strip()
        item["geo_isp_asn"] = f"{isp} | {asn}".strip(" |")
        isp_asn_records.append(item)
    by_isp_asn = aggregate_records(
        isp_asn_records,
        key_fields=["geo_isp_asn"],
        unknown_policy=config.unknown_policy,
    )

    wait_buckets = aggregate_wait_buckets(post_wait_attempts, unknown_policy=config.unknown_policy)
    wait_by_segment = []
    for dimension, key in [
        ("run_id", "run_id"),
        ("proxy_name", "proxy_name"),
        ("exit_ip", "exit_ip"),
        ("geo_country_name", "geo_country_name"),
        ("started_hour_local", "started_hour_local"),
    ]:
        wait_by_segment.extend(
            aggregate_wait_segments(
                post_wait_attempts,
                segment_name=dimension,
                segment_value_key=key,
                unknown_policy=config.unknown_policy,
            )
        )
    wait_by_segment.sort(key=lambda row: (-safe_int(row.get("total_count")), row.get("dimension", ""), row.get("segment", "")))

    failure_breakdown = aggregate_failure_breakdown(enriched, unknown_policy=config.unknown_policy)

    funnel_counts = {
        "total": len(enriched),
        "email_acquired": sum(safe_int(row.get("email_acquired_count")) for row in enriched),
        "phone_gate_hit": sum(safe_int(row.get("phone_gate_hit_count")) for row in enriched),
        "account_registered_pending_token": sum(safe_int(row.get("account_registered_count")) for row in enriched),
        "token_wait_scheduled": sum(safe_int(row.get("token_wait_scheduled_count")) for row in enriched),
        "success": sum(safe_int(row.get("success_count")) for row in enriched),
    }
    funnel_rows = build_funnel_rows(funnel_counts)

    overview_rows = aggregate_records(
        enriched,
        key_fields=[],
        unknown_policy=config.unknown_policy,
    )

    dimension_rows = {
        "proxy_name": by_proxy,
        "exit_ip": by_exit_ip,
        "geo_country_name": by_country,
        "geo_region_name": by_region,
        "geo_isp_asn": by_isp_asn,
    }
    top_segments = build_top_segments(
        dimension_rows,
        min_sample=config.min_sample,
        unknown_policy=config.unknown_policy,
    )

    started_values = [row["started_at_utc"] for row in enriched if row.get("started_at_utc")]
    post_wait_values = [row["started_at_utc"] for row in post_wait_attempts if row.get("started_at_utc")]
    overview = overview_rows[0] if overview_rows else {}
    summary = {
        "config": {
            "db_path": str(config.db_path),
            "output_dir": str(config.output_dir),
            "timezone": config.timezone_name,
            "min_sample": config.min_sample,
            "unknown_policy": config.unknown_policy,
            "history_scope": config.history_scope,
        },
        "analysis_window": {
            "min_started_at_utc": min(started_values) if started_values else "",
            "max_started_at_utc": max(started_values) if started_values else "",
            "post_wait_window_start_utc": min(post_wait_values) if post_wait_values else "",
            "post_wait_window_end_utc": max(post_wait_values) if post_wait_values else "",
        },
        "overview": overview,
        "intermediate_states": {
            "registered_not_waited": sum(1 for row in enriched if row.get("register_stage") == "registered_not_waited"),
            "waited_not_success": sum(1 for row in enriched if row.get("has_token_wait") == 1 and row.get("is_success") != 1),
            "unknown_attempts": sum(safe_int(row.get("unknown_count")) for row in enriched),
        },
        "data_quality": {
            "legacy_backfill_count": sum(safe_int(row.get("legacy_backfill_count")) for row in enriched),
            "missing_exit_ip_count": sum(safe_int(row.get("missing_exit_ip_count")) for row in enriched),
            "missing_geo_count": sum(safe_int(row.get("missing_geo_count")) for row in enriched),
            "unfinished_count": sum(1 for row in enriched if not str(row.get("finished_at_utc") or "").strip()),
            "transition_period_count": sum(safe_int(row.get("transition_period_flag")) for row in enriched),
            "event_count": len(event_rows),
        },
        "validation": {
            "total_count": safe_int(overview.get("total_count")),
            "closed_plus_unknown_equals_total": safe_int(overview.get("closed_count")) + safe_int(overview.get("unknown_count")) == safe_int(overview.get("total_count")),
            "token_wait_subset_count": len(post_wait_attempts),
            "token_wait_db_count": sum(1 for row in enriched if row.get("token_wait_duration_ms") not in (None, "")),
            "group_success_sum_matches_total": sum(safe_int(row.get("success_count")) for row in by_day) == safe_int(overview.get("success_count")),
        },
        "top_event_paths": event_paths[:10],
    }
    summary["validation"]["token_wait_subset_count_matches_db"] = (
        summary["validation"]["token_wait_subset_count"] == summary["validation"]["token_wait_db_count"]
    )

    write_json(config.output_dir / "summary.json", summary)
    write_csv(config.output_dir / "overview.csv", overview_rows)
    write_csv(config.output_dir / "by_day.csv", by_day)
    write_csv(config.output_dir / "by_hour.csv", by_hour)
    write_csv(config.output_dir / "by_run.csv", by_run)
    write_csv(config.output_dir / "by_proxy.csv", by_proxy)
    write_csv(config.output_dir / "by_exit_ip.csv", by_exit_ip)
    write_csv(config.output_dir / "by_country.csv", by_country)
    write_csv(config.output_dir / "by_region.csv", by_region)
    write_csv(config.output_dir / "by_isp_asn.csv", by_isp_asn)
    write_csv(config.output_dir / "wait_buckets.csv", wait_buckets)
    write_csv(config.output_dir / "wait_by_segment.csv", wait_by_segment)
    write_csv(config.output_dir / "failure_breakdown.csv", failure_breakdown)
    write_csv(config.output_dir / "funnel.csv", funnel_rows)
    write_csv(config.output_dir / "top_segments.csv", top_segments)

    report = build_report(
        summary=summary,
        overview_rows=overview_rows,
        by_day=by_day,
        by_hour=by_hour,
        by_run=by_run,
        by_proxy=by_proxy,
        by_exit_ip=by_exit_ip,
        by_country=by_country,
        by_region=by_region,
        by_isp_asn=by_isp_asn,
        wait_buckets=wait_buckets,
        wait_by_segment=wait_by_segment,
        failure_breakdown=failure_breakdown,
        funnel_rows=funnel_rows,
        top_segments=top_segments,
        event_paths=event_paths,
    )
    (config.output_dir / "report.md").write_text(report, encoding="utf-8")

    docs_dir = BASE_DIR / "docs" / "analysis"
    docs_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = infer_snapshot_date(config.timezone_name)
    docs_report_path = docs_dir / f"{snapshot_date}-registration-success-analysis.md"
    docs_report_path.write_text(report, encoding="utf-8")

    print(f"分析完成，输出目录: {config.output_dir}")
    print(f"报告已写入: {config.output_dir / 'report.md'}")
    print(f"文档已写入: {docs_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
