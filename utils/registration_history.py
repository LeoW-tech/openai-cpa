import csv
import io
import json
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


def start_run(
        *,
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
        with db_manager.get_db_conn() as conn:
            cursor = db_manager.get_cursor(conn)
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
                    _utc_now_str(),
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
        if notes:
            existing = _safe_execute_one(
                "SELECT notes_json FROM registration_runs WHERE id = ?",
                (run_id,),
            )
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
                    run_id, task_id, worker_id, source_mode, attempt_no, flow_type,
                    legacy_backfill, linked_account_email, linked_account_created_at,
                    email_full, email_local_part, email_domain, master_email,
                    email_provider_type, email_provider_detail, proxy_url, proxy_name,
                    started_at, final_status, labels_json, metrics_json, result_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id or 0),
                    str(task_id or "").strip(),
                    str(worker_id or "").strip(),
                    str(source_mode or "").strip(),
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
        return 0


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
    }
    for key, value in optional_flags.items():
        if value is not None:
            payload[key] = value
    ok = patch_attempt(attempt_id, **payload)
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


def get_overview(filters: Optional[dict]) -> dict[str, Any]:
    rows = _fetch_attempt_rows(filters)
    attempts = len(rows)
    successes = sum(int(row.get("success_flag") or 0) for row in rows)
    failures = attempts - successes
    phone_gate_hits = sum(int(row.get("phone_gate_hit_flag") or 0) for row in rows)
    phone_otp_entered = sum(int(row.get("phone_otp_entered_flag") or 0) for row in rows)
    phone_otp_success = sum(int(row.get("phone_otp_success_flag") or 0) for row in rows)
    durations = [_row_duration(row) for row in rows if _row_duration(row) > 0]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0
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
                "duration_sum_ms": 0,
                "duration_count": 0,
            },
        )
        bucket["attempts"] += 1
        bucket["successes"] += int(row.get("success_flag") or 0)
        bucket["phone_gate_hits"] += int(row.get("phone_gate_hit_flag") or 0)
        bucket["phone_otp_entered"] += int(row.get("phone_otp_entered_flag") or 0)
        bucket["phone_otp_success"] += int(row.get("phone_otp_success_flag") or 0)
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
    failure_stage = str(getattr(req, "failure_stage", "") or "").strip()
    error_type = str(getattr(req, "error_type", "") or "").strip()
    error_msg = str(getattr(req, "error_msg", "") or "").strip()
    http_status = getattr(req, "http_status", None)
    patch_attempt(
        attempt_id,
        started_at=started_at or _utc_now_str(),
        exit_ip=exit_ip,
        geo_country_name=geo_country_name,
    )
    if exit_ip and not geo_country_name:
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
        result_snapshot_json={
            "finished_at": finished_at,
            "status": status,
        },
    )
    return attempt_id
