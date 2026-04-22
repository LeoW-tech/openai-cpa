import csv
import hashlib
import io
import json
import re
import socket
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from curl_cffi import requests

from utils import config as cfg
from utils import db_manager


def _cfg_bool(name: str, default: bool) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except (TypeError, ValueError):
        return default


def _analytics_enabled() -> bool:
    return _cfg_bool("ANALYTICS_ENABLED", True)


def _capture_events_enabled() -> bool:
    return _cfg_bool("ANALYTICS_CAPTURE_EVENTS", True)


def _capture_ip_geo_enabled() -> bool:
    return _cfg_bool("ANALYTICS_CAPTURE_IP_GEO", True)


def _snapshot_max_bytes() -> int:
    return max(256, _cfg_int("ANALYTICS_SNAPSHOT_MAX_BYTES", 4096))


def _export_max_rows() -> int:
    return max(1, _cfg_int("ANALYTICS_EXPORT_MAX_ROWS", 5000))


def _geo_cache_ttl_hours() -> int:
    return max(1, _cfg_int("ANALYTICS_GEO_CACHE_TTL_HOURS", 24 * 7))


def _public_ip_probe_timeout_sec() -> int:
    return max(1, _cfg_int("ANALYTICS_PUBLIC_IP_PROBE_TIMEOUT_SEC", 8))


def _geo_lookup_timeout_sec() -> int:
    return max(1, _cfg_int("ANALYTICS_GEO_LOOKUP_TIMEOUT_SEC", 8))


def _utc_now() -> datetime:
    return datetime.utcnow()


def _utc_now_str() -> str:
    return _utc_now().strftime("%Y-%m-%d %H:%M:%S")


def _trim_text(value: Any, max_bytes: Optional[int] = None) -> str:
    if value is None:
        return ""
    text = str(value)
    limit = max_bytes or _snapshot_max_bytes()
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    trimmed = raw[: limit - 3].decode("utf-8", errors="ignore")
    return f"{trimmed}..."


def _json_dumps(value: Any) -> str:
    if value is None:
        return ""
    try:
        return _trim_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return _trim_text(str(value))


def _coerce_bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _split_email(email: str) -> tuple[str, str]:
    text = str(email or "").strip().lower()
    if "@" not in text:
        return text, ""
    return text.split("@", 1)


def _derive_master_email(email: str) -> str:
    local_part, domain = _split_email(email)
    if not local_part or not domain:
        return ""
    base_local = local_part.split("+", 1)[0]
    return f"{base_local}@{domain}"


def _host_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _normalize_filters(filters: Optional[dict]) -> dict:
    return dict(filters or {})


_CALLING_CODE_META: list[tuple[str, dict[str, str]]] = [
    ("+852", {"iso": "HK", "country_name": "Hong Kong"}),
    ("+380", {"iso": "UA", "country_name": "Ukraine"}),
    ("+82", {"iso": "KR", "country_name": "South Korea"}),
    ("+81", {"iso": "JP", "country_name": "Japan"}),
    ("+65", {"iso": "SG", "country_name": "Singapore"}),
    ("+61", {"iso": "AU", "country_name": "Australia"}),
    ("+54", {"iso": "AR", "country_name": "Argentina"}),
    ("+49", {"iso": "DE", "country_name": "Germany"}),
    ("+44", {"iso": "GB", "country_name": "United Kingdom"}),
    ("+33", {"iso": "FR", "country_name": "France"}),
    ("+1", {"iso": "US", "country_name": "United States"}),
]

_HERO_COUNTRY_META: dict[int, dict[str, str]] = {
    52: {"calling_code": "+66", "iso": "TH", "country_name": "Thailand"},
    50: {"calling_code": "+1", "iso": "US", "country_name": "United States"},
    16: {"calling_code": "+44", "iso": "GB", "country_name": "United Kingdom"},
}


def normalize_phone_fields(
        phone_number: str,
        *,
        country_id: Any = None,
        country_name_hint: str = "",
) -> dict[str, str]:
    raw = str(phone_number or "").strip()
    if not raw:
        return {
            "phone_number_full": "",
            "phone_number_e164": "",
            "phone_country_calling_code": "",
            "phone_country_iso": "",
            "phone_country_name": str(country_name_hint or "").strip(),
            "phone_national_number": "",
        }

    digits = re.sub(r"\D", "", raw)
    e164 = f"+{digits}" if digits else ""
    calling_code = ""
    iso = ""
    country_name = str(country_name_hint or "").strip()
    national_number = digits

    for code, meta in _CALLING_CODE_META:
        if e164.startswith(code):
            calling_code = code
            iso = meta["iso"]
            country_name = meta["country_name"]
            national_number = digits[len(code) - 1:]
            break

    if (not calling_code or not iso) and country_id not in (None, ""):
        try:
            fallback = _HERO_COUNTRY_META.get(int(country_id))
        except (TypeError, ValueError):
            fallback = None
        if fallback:
            calling_code = calling_code or fallback["calling_code"]
            iso = iso or fallback["iso"]
            country_name = country_name or fallback["country_name"]
            if digits and calling_code:
                code_digits = calling_code.lstrip("+")
                if digits.startswith(code_digits):
                    national_number = digits[len(code_digits):]

    return {
        "phone_number_full": raw,
        "phone_number_e164": e164,
        "phone_country_calling_code": calling_code,
        "phone_country_iso": iso,
        "phone_country_name": country_name,
        "phone_national_number": national_number,
    }


def _token_fingerprint(token_data: Any) -> str:
    raw = token_data if isinstance(token_data, str) else _json_dumps(token_data)
    return hashlib.sha1(str(raw or "").encode("utf-8")).hexdigest()


def _build_where_clause(filters: Optional[dict]) -> tuple[str, list[Any]]:
    normalized = _normalize_filters(filters)
    clauses: list[str] = []
    params: list[Any] = []

    mapping = {
        "source_mode": "source_mode = ?",
        "final_status": "final_status = ?",
        "proxy_name": "proxy_name = ?",
        "geo_country_name": "geo_country_name = ?",
        "geo_region_name": "geo_region_name = ?",
        "email_domain": "email_domain = ?",
        "flow_type": "flow_type = ?",
        "task_id": "task_id = ?",
        "worker_id": "worker_id = ?",
        "phone_country_iso": "phone_country_iso = ?",
        "phone_country_calling_code": "phone_country_calling_code = ?",
        "phone_number_e164": "phone_number_e164 = ?",
        "phone_bind_provider": "phone_bind_provider = ?",
        "phone_bind_stage": "phone_bind_stage = ?",
    }
    for key, sql in mapping.items():
        value = normalized.get(key)
        if value not in (None, "", []):
            clauses.append(sql)
            params.append(value)

    bool_mapping = {
        "success_flag": "success_flag = ?",
        "phone_gate_hit_flag": "phone_gate_hit_flag = ?",
        "phone_otp_entered_flag": "phone_otp_entered_flag = ?",
        "phone_otp_success_flag": "phone_otp_success_flag = ?",
        "phone_bind_attempted_flag": "phone_bind_attempted_flag = ?",
        "phone_bind_success_flag": "phone_bind_success_flag = ?",
        "phone_bind_failed_flag": "phone_bind_failed_flag = ?",
    }
    for key, sql in bool_mapping.items():
        value = normalized.get(key)
        if value not in (None, ""):
            clauses.append(sql)
            params.append(_coerce_bool_int(value))

    started_from = normalized.get("started_from")
    if started_from:
        clauses.append("started_at >= ?")
        params.append(str(started_from))
    started_to = normalized.get("started_to")
    if started_to:
        clauses.append("started_at <= ?")
        params.append(str(started_to))

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _parse_dt(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _safe_execute(sql: str, params: Iterable[Any] = (), *, as_dict: bool = False) -> list[Any]:
    with db_manager.get_db_conn(as_dict=as_dict) as conn:
        cursor = db_manager.get_cursor(conn, as_dict=as_dict)
        db_manager.execute_sql(cursor, sql, tuple(params))
        return cursor.fetchall()


def _safe_execute_one(sql: str, params: Iterable[Any] = (), *, as_dict: bool = False) -> Any:
    with db_manager.get_db_conn(as_dict=as_dict) as conn:
        cursor = db_manager.get_cursor(conn, as_dict=as_dict)
        db_manager.execute_sql(cursor, sql, tuple(params))
        return cursor.fetchone()


def _pending_patch_store(run_ctx: Optional[dict]) -> dict[str, Any]:
    if not isinstance(run_ctx, dict):
        return {}
    pending = run_ctx.get("analytics_pending_patch")
    if not isinstance(pending, dict):
        pending = {}
        run_ctx["analytics_pending_patch"] = pending
    return pending


def _pending_events_store(run_ctx: Optional[dict]) -> list[dict[str, Any]]:
    if not isinstance(run_ctx, dict):
        return []
    pending = run_ctx.get("analytics_pending_events")
    if not isinstance(pending, list):
        pending = []
        run_ctx["analytics_pending_events"] = pending
    return pending


def buffer_pending_patch(run_ctx: Optional[dict], **fields: Any) -> None:
    pending = _pending_patch_store(run_ctx)
    if not pending:
        if not isinstance(run_ctx, dict):
            return
        pending = run_ctx["analytics_pending_patch"] = {}
    for key, value in fields.items():
        pending[key] = value


def buffer_pending_event(run_ctx: Optional[dict], **event: Any) -> None:
    pending = _pending_events_store(run_ctx)
    if isinstance(run_ctx, dict):
        pending.append(dict(event))


def record_history_failure(
        *,
        stage: str,
        source_mode: str = "",
        run_id: int = 0,
        email: str = "",
        proxy_name: str = "",
        error_message: str = "",
        payload: Optional[dict] = None,
        recovered_flag: bool = False,
) -> int:
    if not _analytics_enabled():
        return 0
    try:
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            db_manager.execute_sql(
                cursor,
                """
                INSERT INTO registration_history_failures (
                    occurred_at, stage, source_mode, run_id, email, proxy_name,
                    error_message, payload_json, recovered_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now_str(),
                    str(stage or "").strip(),
                    str(source_mode or "").strip(),
                    int(run_id or 0),
                    str(email or "").strip().lower(),
                    str(proxy_name or "").strip(),
                    _trim_text(error_message),
                    _json_dumps(payload or {}),
                    _coerce_bool_int(recovered_flag),
                ),
            )
            return int(getattr(cursor, "lastrowid", 0) or 0)
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史失败审计写入失败: {exc}")
        return 0


def _replay_pending_history(run_ctx: Optional[dict], attempt_id: int) -> None:
    if not isinstance(run_ctx, dict) or not attempt_id:
        return
    pending_patch = dict(run_ctx.get("analytics_pending_patch") or {})
    pending_events = list(run_ctx.get("analytics_pending_events") or [])
    if pending_patch:
        patch_attempt(attempt_id, **pending_patch)
    for item in pending_events:
        if not isinstance(item, dict):
            continue
        record_attempt_event(
            attempt_id,
            event_type=str(item.get("event_type") or item.get("type") or "buffered_event"),
            phase=str(item.get("phase") or ""),
            elapsed_ms=item.get("elapsed_ms"),
            ok_flag=item.get("ok_flag"),
            http_status=item.get("http_status"),
            reason_code=str(item.get("reason_code") or ""),
            message=str(item.get("message") or ""),
            url_key=str(item.get("url_key") or ""),
            snapshot=item.get("snapshot"),
        )
    run_ctx["analytics_pending_patch"] = {}
    run_ctx["analytics_pending_events"] = []


def start_run(
        *,
        run_id: int = 0,
        started_at: str = "",
        source_mode: str,
        target_count: int = 0,
        trigger_source: str = "",
        worker_id: str = "",
        config_snapshot: Optional[dict] = None,
        notes: Optional[dict] = None,
        host_name: str = "",
) -> int:
    if not _analytics_enabled():
        return 0
    try:
        resolved_started_at = str(started_at or _utc_now_str()).strip()
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            if int(run_id or 0) > 0:
                existing = _safe_execute_one(
                    "SELECT id FROM registration_runs WHERE id = ?",
                    (int(run_id),),
                )
                if existing:
                    db_manager.execute_sql(
                        cursor,
                        """
                        UPDATE registration_runs
                        SET source_mode = ?, started_at = ?, target_count = ?, config_snapshot_json = ?,
                            trigger_source = ?, host_name = ?, worker_id = ?
                        WHERE id = ?
                        """,
                        (
                            str(source_mode or "").strip(),
                            resolved_started_at,
                            int(target_count or 0),
                            _json_dumps(config_snapshot or {}),
                            str(trigger_source or "").strip(),
                            str(host_name or _host_name()).strip(),
                            str(worker_id or "").strip(),
                            int(run_id),
                        ),
                    )
                else:
                    db_manager.execute_sql(
                        cursor,
                        """
                        INSERT INTO registration_runs (
                            id, source_mode, started_at, target_count, config_snapshot_json,
                            trigger_source, host_name, worker_id, notes_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(run_id),
                            str(source_mode or "").strip(),
                            resolved_started_at,
                            int(target_count or 0),
                            _json_dumps(config_snapshot or {}),
                            str(trigger_source or "").strip(),
                            str(host_name or _host_name()).strip(),
                            str(worker_id or "").strip(),
                            _json_dumps(notes or {}),
                        ),
                    )
                return int(run_id)
            db_manager.execute_sql(
                cursor,
                """
                INSERT INTO registration_runs (
                    source_mode, started_at, target_count, config_snapshot_json,
                    trigger_source, host_name, worker_id, notes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source_mode or "").strip(),
                    resolved_started_at,
                    int(target_count or 0),
                    _json_dumps(config_snapshot or {}),
                    str(trigger_source or "").strip(),
                    str(host_name or _host_name()).strip(),
                    str(worker_id or "").strip(),
                    _json_dumps(notes or {}),
                ),
            )
            return int(getattr(cursor, "lastrowid", 0) or 0)
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史分析 start_run 失败: {exc}")
        return 0


def finish_run(run_id: int, notes: Optional[dict] = None) -> bool:
    if not _analytics_enabled() or not run_id:
        return False
    try:
        current_notes = ""
        existing = _safe_execute_one(
            "SELECT notes_json FROM registration_runs WHERE id = ?",
            (run_id,),
        )
        if notes:
            if existing and existing[0]:
                try:
                    payload = json.loads(existing[0])
                except Exception:
                    payload = {}
                payload.update(notes)
                current_notes = _json_dumps(payload)
            else:
                current_notes = _json_dumps(notes)
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            if not existing:
                db_manager.execute_sql(
                    cursor,
                    """
                    INSERT OR IGNORE INTO registration_runs (
                        id, source_mode, started_at, target_count, config_snapshot_json,
                        trigger_source, host_name, worker_id, notes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(run_id),
                        "unknown",
                        _utc_now_str(),
                        0,
                        _json_dumps({}),
                        "",
                        str(_host_name()).strip(),
                        "",
                        current_notes,
                    ),
                )
            db_manager.execute_sql(
                cursor,
                "UPDATE registration_runs SET ended_at = ?, notes_json = ? WHERE id = ?",
                (_utc_now_str(), current_notes, int(run_id)),
            )
        return True
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史分析 finish_run 失败: {exc}")
        return False


def _next_attempt_event_seq(attempt_id: int) -> int:
    row = _safe_execute_one(
        "SELECT COALESCE(MAX(seq_no), 0) FROM registration_attempt_events WHERE attempt_id = ?",
        (attempt_id,),
    )
    return int((row[0] if row else 0) or 0) + 1


def start_attempt(
        *,
        run_id: int = 0,
        task_id: str = "",
        worker_id: str = "",
        source_mode: str = "",
        source_node_name: str = "",
        external_attempt_id: str = "",
        token_fingerprint: str = "",
        attempt_no: int = 1,
        flow_type: str = "register",
        email: str = "",
        master_email: str = "",
        email_provider_type: str = "",
        email_provider_detail: str = "",
        proxy_url: str = "",
        proxy_name: str = "",
        linked_account_email: str = "",
        linked_account_created_at: str = "",
        labels_json: Optional[dict] = None,
        metrics_json: Optional[dict] = None,
        result_snapshot_json: Optional[dict] = None,
        auto_capture_network: bool = True,
) -> int:
    if not _analytics_enabled():
        return 0
    email_full = str(email or "").strip().lower()
    local_part, domain = _split_email(email_full)
    master = str(master_email or "").strip().lower() or _derive_master_email(email_full)
    try:
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            db_manager.execute_sql(
                cursor,
                """
                INSERT INTO registration_attempts (
                    run_id, task_id, worker_id, source_mode, source_node_name, external_attempt_id, token_fingerprint,
                    attempt_no, flow_type,
                    legacy_backfill, linked_account_email, linked_account_created_at,
                    email_full, email_local_part, email_domain, master_email,
                    email_provider_type, email_provider_detail, proxy_url, proxy_name,
                    started_at, final_status, labels_json, metrics_json, result_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id or 0),
                    str(task_id or "").strip(),
                    str(worker_id or "").strip(),
                    str(source_mode or "").strip(),
                    str(source_node_name or "").strip(),
                    str(external_attempt_id or "").strip(),
                    str(token_fingerprint or "").strip(),
                    int(attempt_no or 1),
                    str(flow_type or "register").strip(),
                    0,
                    str(linked_account_email or "").strip().lower(),
                    str(linked_account_created_at or "").strip(),
                    email_full,
                    local_part,
                    domain,
                    master,
                    str(email_provider_type or "").strip(),
                    str(email_provider_detail or "").strip(),
                    str(proxy_url or "").strip(),
                    str(proxy_name or "").strip(),
                    _utc_now_str(),
                    "unknown",
                    _json_dumps(labels_json or {}),
                    _json_dumps(metrics_json or {}),
                    _json_dumps(result_snapshot_json or {}),
                ),
            )
            attempt_id = int(getattr(cursor, "lastrowid", 0) or 0)
        record_attempt_event(
            attempt_id,
            event_type="attempt_started",
            phase=str(flow_type or "register").strip(),
            ok_flag=True,
            message="attempt created",
        )
        if proxy_name:
            record_attempt_event(
                attempt_id,
                event_type="proxy_bound",
                phase="network",
                ok_flag=True,
                message=str(proxy_name),
            )
        if auto_capture_network and proxy_url:
            capture_attempt_network(attempt_id, proxy_url=proxy_url)
        return attempt_id
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史分析 start_attempt 失败: {exc}")
        record_history_failure(
            stage="start_attempt",
            source_mode=source_mode,
            run_id=run_id,
            email=email_full,
            proxy_name=proxy_name,
            error_message=str(exc),
            payload={"flow_type": flow_type, "task_id": task_id},
        )
        return 0


def ensure_attempt(
        run_ctx: Optional[dict],
        *,
        run_id: int = 0,
        source_mode: str = "",
        flow_type: str = "register",
        email: str = "",
        master_email: str = "",
        email_provider_type: str = "",
        email_provider_detail: str = "",
        proxy_url: str = "",
        proxy_name: str = "",
        task_id: str = "",
        worker_id: str = "",
        auto_capture_network: bool = False,
) -> int:
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    try:
        current_attempt_id = int(run_ctx.get("analytics_attempt_id") or 0)
    except (TypeError, ValueError):
        current_attempt_id = 0
    if current_attempt_id:
        return current_attempt_id

    pending_patch = dict(run_ctx.get("analytics_pending_patch") or {})
    resolved_email = (
        str(email or "").strip().lower()
        or str(pending_patch.get("linked_account_email") or "").strip().lower()
        or str(pending_patch.get("email_full") or "").strip().lower()
    )
    resolved_proxy_name = str(proxy_name or pending_patch.get("proxy_name") or "").strip()

    attempt_id = start_attempt(
        run_id=run_id,
        task_id=str(task_id or "").strip(),
        worker_id=str(worker_id or "").strip(),
        source_mode=str(source_mode or "").strip(),
        attempt_no=int(run_ctx.get("analytics_attempt_no") or 1),
        flow_type=str(flow_type or "register").strip(),
        email=resolved_email,
        master_email=str(master_email or "").strip().lower(),
        email_provider_type=str(email_provider_type or "").strip(),
        email_provider_detail=str(email_provider_detail or "").strip(),
        proxy_url=str(proxy_url or "").strip(),
        proxy_name=resolved_proxy_name,
        auto_capture_network=auto_capture_network,
    )
    if not attempt_id:
        record_history_failure(
            stage="start_attempt",
            source_mode=source_mode,
            run_id=run_id,
            email=resolved_email,
            proxy_name=resolved_proxy_name,
            error_message="ensure_attempt failed to create attempt",
            payload={
                "flow_type": flow_type,
                "email_provider_type": email_provider_type,
                "email_provider_detail": email_provider_detail,
                "has_pending_patch": bool(pending_patch),
                "pending_events": len(run_ctx.get("analytics_pending_events") or []),
            },
        )
        return 0

    run_ctx["analytics_attempt_id"] = attempt_id
    _replay_pending_history(run_ctx, attempt_id)
    return attempt_id


def patch_attempt(attempt_id: int, **fields: Any) -> bool:
    if not _analytics_enabled() or not attempt_id or not fields:
        return False
    prepared: dict[str, Any] = {}
    for key, value in fields.items():
        if key in {"labels_json", "metrics_json", "result_snapshot_json"} and not isinstance(value, str):
            prepared[key] = _json_dumps(value or {})
        elif key.endswith("_flag") or key in {
            "legacy_backfill", "local_save_ok", "cpa_upload_ok", "sub2api_push_ok",
            "phone_reuse_used_flag", "success_flag", "retry_403_flag",
            "signup_blocked_flag", "pwd_blocked_flag", "phone_gate_hit_flag",
            "phone_otp_entered_flag", "phone_otp_success_flag",
            "phone_bind_attempted_flag", "phone_bind_success_flag", "phone_bind_failed_flag",
            "account_registered_flag",
        }:
            prepared[key] = _coerce_bool_int(value)
        elif key == "failure_message":
            prepared[key] = _trim_text(value)
        else:
            prepared[key] = value

    columns = ", ".join(f"{key} = ?" for key in prepared.keys())
    params = list(prepared.values()) + [int(attempt_id)]
    try:
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            db_manager.execute_sql(
                cursor,
                f"UPDATE registration_attempts SET {columns} WHERE id = ?",
                tuple(params),
            )
        return True
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史分析 patch_attempt 失败: {exc}")
        record_history_failure(
            stage="patch_attempt",
            email=str(prepared.get("linked_account_email") or prepared.get("email_full") or ""),
            proxy_name=str(prepared.get("proxy_name") or ""),
            error_message=str(exc),
            payload={"attempt_id": attempt_id, "fields": list(prepared.keys())},
        )
        return False


def record_attempt_event(
        attempt_id: int,
        *,
        event_type: str,
        phase: str = "",
        elapsed_ms: Optional[int] = None,
        ok_flag: Optional[bool] = None,
        http_status: Optional[int] = None,
        reason_code: str = "",
        message: str = "",
        url_key: str = "",
        snapshot: Any = None,
) -> bool:
    if not _analytics_enabled() or not _capture_events_enabled() or not attempt_id:
        return False
    try:
        seq_no = _next_attempt_event_seq(attempt_id)
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            db_manager.execute_sql(
                cursor,
                """
                INSERT INTO registration_attempt_events (
                    attempt_id, seq_no, event_type, phase, occurred_at, elapsed_ms,
                    ok_flag, http_status, reason_code, message, url_key, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(attempt_id),
                    seq_no,
                    str(event_type or "").strip(),
                    str(phase or "").strip(),
                    _utc_now_str(),
                    int(elapsed_ms) if elapsed_ms is not None else None,
                    _coerce_bool_int(ok_flag) if ok_flag is not None else None,
                    int(http_status) if http_status is not None else None,
                    str(reason_code or "").strip(),
                    _trim_text(message),
                    _trim_text(url_key, 512),
                    _json_dumps(snapshot or {}),
                ),
            )
        return True
    except Exception as exc:
        print(f"[{cfg.ts()}] [WARNING] 历史分析 record_attempt_event 失败: {exc}")
        return False


def finish_attempt(
        attempt_id: int,
        *,
        final_status: str,
        success_flag: bool = False,
        total_duration_ms: Optional[int] = None,
        finished_at: str = "",
        failure_stage: str = "",
        failure_code: str = "",
        failure_message: str = "",
        last_continue_url: str = "",
        last_http_status: Optional[int] = None,
        linked_account_email: str = "",
        linked_account_created_at: str = "",
        proxy_name: str = "",
        labels_json: Optional[dict] = None,
        metrics_json: Optional[dict] = None,
        result_snapshot_json: Optional[dict] = None,
        local_save_ok: Optional[bool] = None,
        cpa_upload_ok: Optional[bool] = None,
        sub2api_push_ok: Optional[bool] = None,
        retry_403_flag: Optional[bool] = None,
        signup_blocked_flag: Optional[bool] = None,
        pwd_blocked_flag: Optional[bool] = None,
        phone_gate_hit_flag: Optional[bool] = None,
        phone_otp_entered_flag: Optional[bool] = None,
        phone_otp_success_flag: Optional[bool] = None,
        phone_bind_attempted_flag: Optional[bool] = None,
        phone_bind_success_flag: Optional[bool] = None,
        phone_bind_failed_flag: Optional[bool] = None,
) -> bool:
    payload: dict[str, Any] = {
        "finished_at": str(finished_at or _utc_now_str()),
        "final_status": str(final_status or "unknown").strip(),
        "success_flag": success_flag,
    }
    if total_duration_ms is not None:
        payload["total_duration_ms"] = int(total_duration_ms)
    if failure_stage:
        payload["failure_stage"] = str(failure_stage)
    if failure_code:
        payload["failure_code"] = str(failure_code)
    if failure_message:
        payload["failure_message"] = failure_message
    if last_continue_url:
        payload["last_continue_url"] = _trim_text(last_continue_url, 1024)
    if last_http_status is not None:
        payload["last_http_status"] = int(last_http_status)
    if linked_account_email:
        payload["linked_account_email"] = str(linked_account_email).strip().lower()
    if linked_account_created_at:
        payload["linked_account_created_at"] = str(linked_account_created_at).strip()
    if proxy_name:
        payload["proxy_name"] = str(proxy_name).strip()
    if labels_json is not None:
        payload["labels_json"] = labels_json
    if metrics_json is not None:
        payload["metrics_json"] = metrics_json
    if result_snapshot_json is not None:
        payload["result_snapshot_json"] = result_snapshot_json
    optional_flags = {
        "local_save_ok": local_save_ok,
        "cpa_upload_ok": cpa_upload_ok,
        "sub2api_push_ok": sub2api_push_ok,
        "retry_403_flag": retry_403_flag,
        "signup_blocked_flag": signup_blocked_flag,
        "pwd_blocked_flag": pwd_blocked_flag,
        "phone_gate_hit_flag": phone_gate_hit_flag,
        "phone_otp_entered_flag": phone_otp_entered_flag,
        "phone_otp_success_flag": phone_otp_success_flag,
        "phone_bind_attempted_flag": phone_bind_attempted_flag,
        "phone_bind_success_flag": phone_bind_success_flag,
        "phone_bind_failed_flag": phone_bind_failed_flag,
    }
    for key, value in optional_flags.items():
        if value is not None:
            payload[key] = value
    ok = patch_attempt(attempt_id, **payload)
    if not ok:
        record_history_failure(
            stage="finish_attempt",
            email=str(payload.get("linked_account_email") or ""),
            proxy_name=str(payload.get("proxy_name") or ""),
            error_message="patch_attempt returned false during finish_attempt",
            payload={"attempt_id": attempt_id, "final_status": payload.get("final_status")},
        )
    record_attempt_event(
        attempt_id,
        event_type="attempt_finished",
        phase="result",
        ok_flag=success_flag,
        http_status=last_http_status,
        message=str(final_status or "unknown"),
        snapshot={
            "failure_stage": failure_stage,
            "failure_code": failure_code,
        },
    )
    return ok


def _trace_ip_country(proxy_url: str = "") -> dict[str, Any]:
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    timeout = _public_ip_probe_timeout_sec()
    try:
        resp = requests.get(
            "https://cloudflare.com/cdn-cgi/trace",
            proxies=proxies,
            timeout=timeout,
            impersonate="chrome110",
        )
        text = str(getattr(resp, "text", "") or "")
        payload: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            payload[key.strip()] = value.strip()
        return {
            "ip": payload.get("ip", ""),
            "country_code": payload.get("loc", ""),
            "source": "cloudflare-trace",
            "status": "ok" if payload.get("ip") else "empty",
            "raw_json": payload,
        }
    except Exception as exc:
        return {
            "ip": "",
            "country_code": "",
            "source": "cloudflare-trace",
            "status": f"failed:{exc}",
            "raw_json": {},
        }


def _read_geo_cache(ip: str) -> dict[str, Any]:
    row = _safe_execute_one(
        """
        SELECT ip, expires_at, country_code, country_name, region_name, city_name,
               isp, asn, source, raw_json, status
        FROM ip_geo_cache
        WHERE ip = ?
        """,
        (ip,),
    )
    if not row:
        return {}
    expires_at = row[1] or ""
    if expires_at:
        try:
            expire_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            if expire_dt < _utc_now():
                return {}
        except Exception:
            return {}
    return {
        "ip": row[0],
        "country_code": row[2],
        "country_name": row[3],
        "region_name": row[4],
        "city_name": row[5],
        "isp": row[6],
        "asn": row[7],
        "source": row[8],
        "raw_json": row[9],
        "status": row[10],
    }


def _write_geo_cache(ip: str, payload: dict[str, Any]) -> None:
    expires_at = (_utc_now() + timedelta(hours=_geo_cache_ttl_hours())).strftime("%Y-%m-%d %H:%M:%S")
    with db_manager.get_db_conn() as conn:
        cursor = db_manager.get_cursor(conn)
        db_manager.execute_sql(
            cursor,
            """
            INSERT OR REPLACE INTO ip_geo_cache (
                ip, resolved_at, expires_at, country_code, country_name, region_name,
                city_name, isp, asn, source, raw_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ip,
                _utc_now_str(),
                expires_at,
                str(payload.get("country_code") or "").strip(),
                str(payload.get("country_name") or "").strip(),
                str(payload.get("region_name") or "").strip(),
                str(payload.get("city_name") or "").strip(),
                str(payload.get("isp") or "").strip(),
                str(payload.get("asn") or "").strip(),
                str(payload.get("source") or "").strip(),
                _json_dumps(payload.get("raw_json") or {}),
                str(payload.get("status") or "").strip(),
            ),
        )


def lookup_geo_for_ip(ip: str, *, country_code_hint: str = "") -> dict[str, Any]:
    if not ip or not _capture_ip_geo_enabled():
        return {}
    cached = _read_geo_cache(ip)
    if cached:
        return cached
    timeout = _geo_lookup_timeout_sec()
    try:
        resp = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,isp,as,query,message",
            timeout=timeout,
            impersonate="chrome110",
        )
        payload = resp.json() if hasattr(resp, "json") else {}
        status = str(payload.get("status") or "").strip().lower()
        result = {
            "ip": ip,
            "country_code": str(payload.get("countryCode") or country_code_hint or "").strip(),
            "country_name": str(payload.get("country") or "").strip(),
            "region_name": str(payload.get("regionName") or "").strip(),
            "city_name": str(payload.get("city") or "").strip(),
            "isp": str(payload.get("isp") or "").strip(),
            "asn": str(payload.get("as") or "").strip(),
            "source": "ip-api",
            "raw_json": payload,
            "status": "ok" if status == "success" else str(payload.get("message") or status or "failed"),
        }
    except Exception as exc:
        result = {
            "ip": ip,
            "country_code": str(country_code_hint or "").strip(),
            "country_name": "",
            "region_name": "",
            "city_name": "",
            "isp": "",
            "asn": "",
            "source": "ip-api",
            "raw_json": {},
            "status": f"failed:{exc}",
        }
    _write_geo_cache(ip, result)
    return result


def capture_attempt_network(attempt_id: int, *, proxy_url: str = "") -> bool:
    if not _analytics_enabled() or not _capture_ip_geo_enabled() or not attempt_id:
        return False
    trace = _trace_ip_country(proxy_url=proxy_url)
    exit_ip = str(trace.get("ip") or "").strip()
    country_code = str(trace.get("country_code") or "").strip()
    if exit_ip:
        patch_attempt(
            attempt_id,
            exit_ip=exit_ip,
            geo_country_code=country_code,
        )
        record_attempt_event(
            attempt_id,
            event_type="exit_ip_resolved",
            phase="network",
            ok_flag=True,
            message=exit_ip,
            snapshot={"country_code": country_code, "source": trace.get("source")},
        )
        geo = lookup_geo_for_ip(exit_ip, country_code_hint=country_code)
        patch_attempt(
            attempt_id,
            geo_country_code=geo.get("country_code") or country_code,
            geo_country_name=geo.get("country_name") or "",
            geo_region_name=geo.get("region_name") or "",
            geo_city_name=geo.get("city_name") or "",
            geo_isp=geo.get("isp") or "",
            geo_asn=geo.get("asn") or "",
            geo_source=geo.get("source") or "",
            geo_status=geo.get("status") or "",
        )
        record_attempt_event(
            attempt_id,
            event_type="geo_resolved",
            phase="network",
            ok_flag=str(geo.get("status") or "").startswith("ok"),
            message=str(geo.get("country_name") or country_code or ""),
            snapshot=geo,
        )
        return True
    patch_attempt(
        attempt_id,
        geo_country_code=country_code,
        geo_status=str(trace.get("status") or "failed"),
        geo_source=str(trace.get("source") or ""),
    )
    return False


def _fetch_attempt_rows(filters: Optional[dict], *, limit: Optional[int] = None, offset: int = 0) -> list[dict[str, Any]]:
    where_sql, params = _build_where_clause(filters)
    sql = f"SELECT * FROM registration_attempts{where_sql} ORDER BY started_at DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    rows = _safe_execute(sql, params, as_dict=True)
    return [dict(row) for row in rows]


def _row_duration(row: dict[str, Any]) -> int:
    try:
        return int(row.get("total_duration_ms") or 0)
    except (TypeError, ValueError):
        return 0


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * ratio))
    return ordered[index]


def _fetch_account_success_rows(filters: Optional[dict]) -> list[dict[str, Any]]:
    normalized = _normalize_filters(filters)
    clauses: list[str] = []
    params: list[Any] = []
    if normalized.get("started_from"):
        clauses.append("created_at >= ?")
        params.append(str(normalized["started_from"]))
    if normalized.get("started_to"):
        clauses.append("created_at <= ?")
        params.append(str(normalized["started_to"]))
    if normalized.get("email_domain"):
        clauses.append("lower(substr(email, instr(email, '@') + 1)) = ?")
        params.append(str(normalized["email_domain"]).lower())
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _safe_execute(
        f"SELECT id, email, token_data, created_at FROM accounts{where_sql} ORDER BY created_at DESC, id DESC",
        params,
        as_dict=True,
    )
    results: list[dict[str, Any]] = []
    proxy_filter = str(normalized.get("proxy_name") or "").strip()
    for row in rows:
        item = dict(row)
        token_payload = {}
        try:
            token_payload = json.loads(item.get("token_data") or "{}")
        except Exception:
            token_payload = {}
        proxy_name = str(token_payload.get("sub2api_proxy_name") or "").strip()
        item["proxy_name"] = proxy_name
        item["email"] = str(item.get("email") or "").strip().lower()
        item["created_at"] = str(item.get("created_at") or "").strip()
        if proxy_filter and proxy_name != proxy_filter:
            continue
        results.append(item)
    return results


def _find_matching_success_attempt(account_row: dict[str, Any], filters: Optional[dict]) -> dict[str, Any]:
    normalized = _normalize_filters(filters)
    clauses = [
        "success_flag = 1",
        "lower(coalesce(linked_account_email, email_full, '')) = ?",
        "coalesce(linked_account_created_at, '') = ?",
    ]
    params: list[Any] = [
        str(account_row.get("email") or "").strip().lower(),
        str(account_row.get("created_at") or "").strip(),
    ]
    if normalized.get("source_mode"):
        clauses.append("source_mode = ?")
        params.append(str(normalized["source_mode"]).strip())
    row = _safe_execute_one(
        f"SELECT * FROM registration_attempts WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT 1",
        params,
        as_dict=True,
    )
    return dict(row) if row else {}


def _possible_coverage_reason(account_row: dict[str, Any], filters: Optional[dict]) -> str:
    normalized = _normalize_filters(filters)
    same_email_clauses = [
        "success_flag = 1",
        "lower(coalesce(linked_account_email, email_full, '')) = ?",
    ]
    same_email_params: list[Any] = [str(account_row.get("email") or "").strip().lower()]
    if normalized.get("source_mode"):
        same_email_clauses.append("source_mode = ?")
        same_email_params.append(str(normalized["source_mode"]).strip())
    row = _safe_execute_one(
        f"SELECT id FROM registration_attempts WHERE {' AND '.join(same_email_clauses)} ORDER BY id DESC LIMIT 1",
        same_email_params,
    )
    if row:
        return "email_matched_but_timestamp_mismatch"
    return "no_matching_attempt"


def list_coverage_audit(filters: Optional[dict]) -> dict[str, Any]:
    accounts = _fetch_account_success_rows(filters)
    rows: list[dict[str, Any]] = []
    missing_total = 0
    for account in accounts:
        matched = _find_matching_success_attempt(account, filters)
        match_status = "matched" if matched else "missing"
        if match_status == "missing":
            missing_total += 1
        rows.append(
            {
                "account_id": int(account.get("id") or 0),
                "email": str(account.get("email") or "").strip().lower(),
                "created_at": str(account.get("created_at") or "").strip(),
                "proxy_name": str(account.get("proxy_name") or "").strip(),
                "match_status": match_status,
                "attempt_id": int(matched.get("id") or 0) if matched else 0,
                "possible_reason": "" if matched else _possible_coverage_reason(account, filters),
            }
        )
    return {
        "accounts_total": len(accounts),
        "missing_total": missing_total,
        "rows": rows,
    }


def _count_history_failures(filters: Optional[dict]) -> int:
    normalized = _normalize_filters(filters)
    clauses: list[str] = []
    params: list[Any] = []
    if normalized.get("started_from"):
        clauses.append("occurred_at >= ?")
        params.append(str(normalized["started_from"]))
    if normalized.get("started_to"):
        clauses.append("occurred_at <= ?")
        params.append(str(normalized["started_to"]))
    if normalized.get("source_mode"):
        clauses.append("source_mode = ?")
        params.append(str(normalized["source_mode"]).strip())
    if normalized.get("proxy_name"):
        clauses.append("proxy_name = ?")
        params.append(str(normalized["proxy_name"]).strip())
    if normalized.get("email_domain"):
        clauses.append("lower(substr(email, instr(email, '@') + 1)) = ?")
        params.append(str(normalized["email_domain"]).lower())
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    row = _safe_execute_one(
        f"SELECT COUNT(*) FROM registration_history_failures{where_sql}",
        params,
    )
    return int((row[0] if row else 0) or 0)


def get_overview(filters: Optional[dict]) -> dict[str, Any]:
    rows = _fetch_attempt_rows(filters)
    attempts = len(rows)
    successes = sum(int(row.get("success_flag") or 0) for row in rows)
    failures = attempts - successes
    phone_gate_hits = sum(int(row.get("phone_gate_hit_flag") or 0) for row in rows)
    phone_otp_entered = sum(int(row.get("phone_otp_entered_flag") or 0) for row in rows)
    phone_otp_success = sum(int(row.get("phone_otp_success_flag") or 0) for row in rows)
    phone_bind_attempted = sum(int(row.get("phone_bind_attempted_flag") or 0) for row in rows)
    phone_bind_success = sum(int(row.get("phone_bind_success_flag") or 0) for row in rows)
    phone_bind_failed = sum(int(row.get("phone_bind_failed_flag") or 0) for row in rows)
    cluster_import_successes = sum(
        1 for row in rows
        if str(row.get("source_mode") or "") == "cluster_import" and int(row.get("success_flag") or 0) == 1
    )
    durations = [_row_duration(row) for row in rows if _row_duration(row) > 0]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0
    coverage = list_coverage_audit(filters)
    history_coverage_gap = int(coverage.get("missing_total") or 0)
    history_write_failures = _count_history_failures(filters)
    return {
        "attempts": attempts,
        "successes": successes,
        "failures": failures,
        "success_rate": round((successes / attempts) * 100, 2) if attempts else 0.0,
        "avg_duration_ms": avg_duration,
        "p50_duration_ms": _percentile(durations, 0.5),
        "p90_duration_ms": _percentile(durations, 0.9),
        "phone_gate_hits": phone_gate_hits,
        "phone_otp_entered": phone_otp_entered,
        "phone_otp_success": phone_otp_success,
        "phone_bind_attempted": phone_bind_attempted,
        "phone_bind_success": phone_bind_success,
        "phone_bind_failed": phone_bind_failed,
        "cluster_import_successes": cluster_import_successes,
        "history_coverage_gap": history_coverage_gap,
        "history_write_failures": history_write_failures,
    }


def get_distribution(filters: Optional[dict]) -> dict[str, Any]:
    normalized = _normalize_filters(filters)
    group_by = str(normalized.get("group_by") or "geo_country_name").strip()
    rows = _fetch_attempt_rows(filters)
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if group_by == "hour_of_day":
            value = str(row.get("started_at") or "")[11:13] or "unknown"
        elif group_by == "day":
            value = str(row.get("started_at") or "")[:10] or "unknown"
        else:
            value = str(row.get(group_by) or "unknown")
        bucket = buckets.setdefault(
            value,
            {
                "group_value": value,
                "attempts": 0,
                "successes": 0,
                "phone_gate_hits": 0,
                "phone_otp_entered": 0,
                "phone_otp_success": 0,
                "phone_bind_attempted": 0,
                "phone_bind_success": 0,
                "phone_bind_failed": 0,
                "duration_sum_ms": 0,
                "duration_count": 0,
            },
        )
        bucket["attempts"] += 1
        bucket["successes"] += int(row.get("success_flag") or 0)
        bucket["phone_gate_hits"] += int(row.get("phone_gate_hit_flag") or 0)
        bucket["phone_otp_entered"] += int(row.get("phone_otp_entered_flag") or 0)
        bucket["phone_otp_success"] += int(row.get("phone_otp_success_flag") or 0)
        bucket["phone_bind_attempted"] += int(row.get("phone_bind_attempted_flag") or 0)
        bucket["phone_bind_success"] += int(row.get("phone_bind_success_flag") or 0)
        bucket["phone_bind_failed"] += int(row.get("phone_bind_failed_flag") or 0)
        duration = _row_duration(row)
        if duration > 0:
            bucket["duration_sum_ms"] += duration
            bucket["duration_count"] += 1

    results = []
    for value, bucket in buckets.items():
        attempts = bucket["attempts"]
        avg_duration = (
            round(bucket["duration_sum_ms"] / bucket["duration_count"], 2)
            if bucket["duration_count"] else 0
        )
        results.append(
            {
                "group_value": value,
                "attempts": attempts,
                "successes": bucket["successes"],
                "success_rate": round((bucket["successes"] / attempts) * 100, 2) if attempts else 0.0,
                "phone_gate_hits": bucket["phone_gate_hits"],
                "phone_otp_entered": bucket["phone_otp_entered"],
                "phone_otp_success": bucket["phone_otp_success"],
                "phone_bind_attempted": bucket["phone_bind_attempted"],
                "phone_bind_success": bucket["phone_bind_success"],
                "phone_bind_failed": bucket["phone_bind_failed"],
                "avg_duration_ms": avg_duration,
            }
        )
    results.sort(key=lambda item: (-item["attempts"], item["group_value"]))
    return {"group_by": group_by, "rows": results}


def list_attempts(filters: Optional[dict], *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    page_num = max(1, int(page or 1))
    per_page = max(1, min(int(page_size or 50), _export_max_rows()))
    where_sql, params = _build_where_clause(filters)
    count_row = _safe_execute_one(f"SELECT COUNT(*) FROM registration_attempts{where_sql}", params)
    total = int((count_row[0] if count_row else 0) or 0)
    rows = _fetch_attempt_rows(filters, limit=per_page, offset=(page_num - 1) * per_page)
    return {
        "page": page_num,
        "page_size": per_page,
        "total": total,
        "rows": rows,
    }


def list_attempt_events(attempt_id: int) -> list[dict[str, Any]]:
    rows = _safe_execute(
        """
        SELECT attempt_id, seq_no, event_type, phase, occurred_at, elapsed_ms,
               ok_flag, http_status, reason_code, message, url_key, snapshot_json
        FROM registration_attempt_events
        WHERE attempt_id = ?
        ORDER BY seq_no ASC
        """,
        (attempt_id,),
        as_dict=True,
    )
    return [dict(row) for row in rows]


def export_attempts(filters: Optional[dict], *, export_format: str = "json") -> str:
    rows = _fetch_attempt_rows(filters, limit=_export_max_rows(), offset=0)
    if str(export_format or "json").lower() == "csv":
        buffer = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else [
            "id", "email_full", "email_domain", "proxy_name", "exit_ip",
            "geo_country_name", "final_status", "success_flag",
            "phone_otp_entered_flag", "total_duration_ms",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()
    return json.dumps(rows, ensure_ascii=False, indent=2)


def backfill_accounts_history(limit: Optional[int] = None) -> int:
    if not _analytics_enabled():
        return 0
    sql = "SELECT email, token_data, created_at FROM accounts ORDER BY id ASC"
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = _safe_execute(sql, params)
    inserted = 0
    for email, token_data_raw, created_at in rows:
        normalized_email = str(email or "").strip().lower()
        existing = _safe_execute_one(
            """
            SELECT id FROM registration_attempts
            WHERE legacy_backfill = 1 AND linked_account_email = ?
            """,
            (normalized_email,),
        )
        if existing:
            continue
        token_data = {}
        try:
            token_data = json.loads(token_data_raw or "{}")
        except Exception:
            token_data = {}
        local_part, domain = _split_email(normalized_email)
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
            db_manager.execute_sql(
                cursor,
                """
                INSERT INTO registration_attempts (
                    run_id, task_id, worker_id, source_mode, attempt_no, flow_type,
                    legacy_backfill, linked_account_email, linked_account_created_at,
                    email_full, email_local_part, email_domain, master_email,
                    proxy_name, started_at, finished_at, final_status, success_flag,
                    labels_json, result_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    0,
                    "",
                    "",
                    "legacy_backfill",
                    1,
                    "register",
                    1,
                    normalized_email,
                    str(created_at or ""),
                    normalized_email,
                    local_part,
                    domain,
                    _derive_master_email(normalized_email),
                    str(token_data.get("sub2api_proxy_name") or "").strip(),
                    str(created_at or _utc_now_str()),
                    str(created_at or _utc_now_str()),
                    "success",
                    1,
                    _json_dumps({"legacy_backfill": True}),
                    _json_dumps({"token_type": str(token_data.get("type") or "")}),
                ),
            )
            attempt_id = int(getattr(cursor, "lastrowid", 0) or 0)
        record_attempt_event(
            attempt_id,
            event_type="attempt_finished",
            phase="backfill",
            ok_flag=True,
            message="legacy account backfilled",
        )
        inserted += 1
    return inserted


def compensate_missing_success_attempts(limit: Optional[int] = None) -> int:
    if not _analytics_enabled():
        return 0
    audit = list_coverage_audit({})
    inserted = 0
    for row in audit["rows"]:
        if row.get("match_status") != "missing":
            continue
        account_row = _safe_execute_one(
            "SELECT email, token_data, created_at FROM accounts WHERE id = ?",
            (int(row.get("account_id") or 0),),
            as_dict=True,
        )
        if not account_row:
            continue
        token_payload = {}
        try:
            token_payload = json.loads(account_row["token_data"] or "{}")
        except Exception:
            token_payload = {}
        email = str(account_row["email"] or "").strip().lower()
        created_at = str(account_row["created_at"] or "").strip() or _utc_now_str()
        attempt_id = start_attempt(
            source_mode="success_compensation",
            flow_type="register",
            email=email,
            proxy_name=str(token_payload.get("sub2api_proxy_name") or "").strip(),
            linked_account_email=email,
            linked_account_created_at=created_at,
            auto_capture_network=False,
            result_snapshot_json={"token_type": str(token_payload.get("type") or "")},
        )
        if not attempt_id:
            record_history_failure(
                stage="success_compensation",
                source_mode="success_compensation",
                email=email,
                proxy_name=str(token_payload.get("sub2api_proxy_name") or "").strip(),
                error_message="failed to create compensation attempt",
                payload={"created_at": created_at},
            )
            continue
        finish_attempt(
            attempt_id,
            final_status="success",
            success_flag=True,
            finished_at=created_at,
            linked_account_email=email,
            linked_account_created_at=created_at,
            proxy_name=str(token_payload.get("sub2api_proxy_name") or "").strip(),
        )
        inserted += 1
        if limit is not None and inserted >= int(limit):
            break
    return inserted


def record_cluster_account_result(account: dict[str, Any], *, node_name: str, run_id: int = 0) -> int:
    payload = dict(account or {})
    token_data_raw = payload.get("token_data") or ""
    try:
        token_data = json.loads(token_data_raw or "{}")
    except Exception:
        token_data = {}
    email = str(payload.get("email") or token_data.get("email") or "").strip().lower()
    created_at = str(
        payload.get("created_at")
        or payload.get("finished_at")
        or payload.get("started_at")
        or _utc_now_str()
    ).strip()
    external_attempt_id = str(payload.get("attempt_id") or payload.get("external_attempt_id") or "").strip()
    token_fingerprint = _token_fingerprint(token_data_raw)

    if external_attempt_id:
        existing = _safe_execute_one(
            """
            SELECT id FROM registration_attempts
            WHERE source_mode = ? AND source_node_name = ? AND external_attempt_id = ?
            """,
            ("cluster_import", str(node_name or "").strip(), external_attempt_id),
        )
    else:
        existing = _safe_execute_one(
            """
            SELECT id FROM registration_attempts
            WHERE source_mode = ? AND source_node_name = ? AND linked_account_email = ?
              AND linked_account_created_at = ? AND token_fingerprint = ?
            """,
            ("cluster_import", str(node_name or "").strip(), email, created_at, token_fingerprint),
        )

    if existing:
        return int(existing[0] or 0)

    if int(run_id or 0) > 0:
        start_run(
            run_id=int(run_id),
            started_at=created_at,
            source_mode="cluster_import",
            trigger_source=str(node_name or "").strip(),
            config_snapshot={"source_node_name": str(node_name or "").strip()},
        )

    attempt_id = start_attempt(
        run_id=run_id,
        task_id=str(payload.get("task_id") or "").strip(),
        worker_id=str(payload.get("worker_id") or "").strip(),
        source_mode="cluster_import",
        source_node_name=str(node_name or "").strip(),
        external_attempt_id=external_attempt_id,
        token_fingerprint=token_fingerprint,
        attempt_no=int(payload.get("attempt_no") or 1),
        flow_type=str(payload.get("flow_type") or "register").strip(),
        email=email,
        proxy_name=str(payload.get("proxy_name") or token_data.get("sub2api_proxy_name") or "").strip(),
        linked_account_email=email,
        linked_account_created_at=created_at,
        auto_capture_network=False,
        result_snapshot_json={"token_type": str(token_data.get("type") or "")},
    )
    if not attempt_id:
        return 0

    phone_number_full = str(payload.get("phone_number_full") or "").strip()
    phone_meta = normalize_phone_fields(
        phone_number_full or str(payload.get("phone_number_e164") or "").strip(),
        country_name_hint=str(payload.get("phone_country_name") or "").strip(),
    )

    patch_attempt(
        attempt_id,
        started_at=str(payload.get("started_at") or created_at),
        finished_at=created_at,
        exit_ip=str(payload.get("exit_ip") or "").strip(),
        geo_country_name=str(payload.get("geo_country_name") or "").strip(),
        source_node_name=str(node_name or "").strip(),
        external_attempt_id=external_attempt_id,
        token_fingerprint=token_fingerprint,
        phone_number_full=phone_number_full or phone_meta["phone_number_full"],
        phone_number_e164=str(payload.get("phone_number_e164") or "").strip() or phone_meta["phone_number_e164"],
        phone_country_calling_code=str(payload.get("phone_country_calling_code") or "").strip() or phone_meta["phone_country_calling_code"],
        phone_country_iso=str(payload.get("phone_country_iso") or "").strip() or phone_meta["phone_country_iso"],
        phone_country_name=str(payload.get("phone_country_name") or "").strip() or phone_meta["phone_country_name"],
        phone_national_number=str(payload.get("phone_national_number") or "").strip() or phone_meta["phone_national_number"],
        phone_activation_id=str(payload.get("phone_activation_id") or "").strip(),
        phone_bind_provider=str(payload.get("phone_bind_provider") or "").strip(),
        phone_bind_attempted_flag=payload.get("phone_bind_attempted_flag"),
        phone_bind_success_flag=payload.get("phone_bind_success_flag"),
        phone_bind_failed_flag=payload.get("phone_bind_failed_flag"),
        phone_bind_failure_reason=str(payload.get("phone_bind_failure_reason") or "").strip(),
        phone_bind_stage=str(payload.get("phone_bind_stage") or "").strip(),
    )
    for item in payload.get("events") or []:
        if not isinstance(item, dict):
            continue
        record_attempt_event(
            attempt_id,
            event_type=str(item.get("event_type") or item.get("type") or "cluster_event"),
            phase=str(item.get("phase") or "cluster_import"),
            elapsed_ms=item.get("elapsed_ms"),
            ok_flag=item.get("ok_flag"),
            http_status=item.get("http_status"),
            reason_code=str(item.get("reason_code") or ""),
            message=str(item.get("message") or ""),
            url_key=str(item.get("url_key") or ""),
            snapshot=item.get("snapshot"),
        )
    finish_attempt(
        attempt_id,
        final_status="success",
        success_flag=True,
        finished_at=created_at,
        linked_account_email=email,
        linked_account_created_at=created_at,
        proxy_name=str(payload.get("proxy_name") or token_data.get("sub2api_proxy_name") or "").strip(),
        phone_bind_attempted_flag=payload.get("phone_bind_attempted_flag"),
        phone_bind_success_flag=payload.get("phone_bind_success_flag"),
        phone_bind_failed_flag=payload.get("phone_bind_failed_flag"),
    )
    return attempt_id


def record_extension_result(req: Any, run_id: int = 0) -> int:
    email = str(getattr(req, "email", "") or "").strip().lower()
    task_id = str(getattr(req, "task_id", "") or "").strip()
    source_mode = "extension"
    flow_type = str(getattr(req, "flow_type", "") or "extension").strip()
    started_at = str(getattr(req, "started_at", "") or "").strip()
    finished_at = str(getattr(req, "finished_at", "") or "").strip()
    total_duration_ms = None
    started_dt = _parse_dt(started_at)
    finished_dt = _parse_dt(finished_at)
    if started_dt and finished_dt:
        total_duration_ms = max(0, int(round((finished_dt - started_dt).total_seconds() * 1000)))
    attempt_id = start_attempt(
        run_id=run_id,
        task_id=task_id,
        worker_id=str(getattr(req, "worker_id", "") or "").strip(),
        source_mode=source_mode,
        attempt_no=1,
        flow_type=flow_type,
        email=email,
        proxy_name=str(getattr(req, "proxy_name", "") or "").strip(),
        auto_capture_network=False,
    )
    if not attempt_id:
        return 0

    exit_ip = str(getattr(req, "exit_ip", "") or "").strip()
    geo_country_name = str(getattr(req, "geo_country_name", "") or "").strip()
    phone_gate_hit = getattr(req, "phone_gate_hit", False)
    phone_otp_entered = getattr(req, "phone_otp_entered", False)
    phone_otp_success = getattr(req, "phone_otp_success", False)
    phone_number_full = str(getattr(req, "phone_number_full", "") or "").strip()
    phone_meta = normalize_phone_fields(
        phone_number_full or str(getattr(req, "phone_number_e164", "") or "").strip(),
        country_name_hint=str(getattr(req, "phone_country_name", "") or "").strip(),
    )
    failure_stage = str(getattr(req, "failure_stage", "") or "").strip()
    error_type = str(getattr(req, "error_type", "") or "").strip()
    error_msg = str(getattr(req, "error_msg", "") or "").strip()
    http_status = getattr(req, "http_status", None)
    patch_attempt(
        attempt_id,
        started_at=started_at or _utc_now_str(),
        exit_ip=exit_ip,
        geo_country_name=geo_country_name,
        phone_number_full=phone_number_full or phone_meta["phone_number_full"],
        phone_number_e164=str(getattr(req, "phone_number_e164", "") or "").strip() or phone_meta["phone_number_e164"],
        phone_country_calling_code=str(getattr(req, "phone_country_calling_code", "") or "").strip() or phone_meta["phone_country_calling_code"],
        phone_country_iso=str(getattr(req, "phone_country_iso", "") or "").strip() or phone_meta["phone_country_iso"],
        phone_country_name=str(getattr(req, "phone_country_name", "") or "").strip() or phone_meta["phone_country_name"],
        phone_national_number=str(getattr(req, "phone_national_number", "") or "").strip() or phone_meta["phone_national_number"],
        phone_activation_id=str(getattr(req, "phone_activation_id", "") or "").strip(),
        phone_bind_provider=str(getattr(req, "phone_bind_provider", "") or "").strip(),
    )
    if exit_ip and not geo_country_name:
        try:
            geo = lookup_geo_for_ip(exit_ip)
            patch_attempt(
                attempt_id,
                geo_country_code=geo.get("country_code") or "",
                geo_country_name=geo.get("country_name") or "",
                geo_region_name=geo.get("region_name") or "",
                geo_city_name=geo.get("city_name") or "",
                geo_isp=geo.get("isp") or "",
                geo_asn=geo.get("asn") or "",
                geo_source=geo.get("source") or "",
                geo_status=geo.get("status") or "",
            )
        except Exception as exc:
            print(f"[{cfg.ts()}] [WARNING] extension geo lookup failed: {exc}")
    events = getattr(req, "events", None) or []
    for item in events:
        if not isinstance(item, dict):
            continue
        record_attempt_event(
            attempt_id,
            event_type=str(item.get("event_type") or item.get("type") or "extension_event"),
            phase=str(item.get("phase") or flow_type),
            elapsed_ms=item.get("elapsed_ms"),
            ok_flag=item.get("ok_flag"),
            http_status=item.get("http_status"),
            reason_code=str(item.get("reason_code") or ""),
            message=str(item.get("message") or ""),
            url_key=str(item.get("url_key") or ""),
            snapshot=item.get("snapshot"),
        )
    status = str(getattr(req, "status", "") or "").strip().lower()
    final_status = "success" if status == "success" else "failed"
    finish_attempt(
        attempt_id,
        final_status=final_status,
        success_flag=(final_status == "success"),
        total_duration_ms=total_duration_ms,
        finished_at=finished_at,
        failure_stage=failure_stage or error_type,
        failure_code=error_type,
        failure_message=error_msg,
        last_http_status=int(http_status) if http_status not in (None, "") else None,
        phone_gate_hit_flag=phone_gate_hit,
        phone_otp_entered_flag=phone_otp_entered,
        phone_otp_success_flag=phone_otp_success,
        phone_bind_attempted_flag=getattr(req, "phone_bind_attempted_flag", False),
        phone_bind_success_flag=getattr(req, "phone_bind_success_flag", False),
        phone_bind_failed_flag=getattr(req, "phone_bind_failed_flag", False),
        metrics_json={},
        result_snapshot_json={
            "finished_at": finished_at,
            "status": status,
        },
    )
    patch_attempt(
        attempt_id,
        phone_bind_failure_reason=str(getattr(req, "phone_bind_failure_reason", "") or "").strip(),
        phone_bind_stage=str(getattr(req, "phone_bind_stage", "") or "").strip(),
    )
    return attempt_id
