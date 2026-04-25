import json
from typing import Any, Optional

from utils import db_manager
from utils import registration_history


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_account_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _load_token_payload(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return dict(raw_value)
    try:
        payload = json.loads(str(raw_value or "{}"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _fetch_cloud_accounts_strict(client: Any, page_size: int = 100) -> list[dict[str, Any]]:
    if not hasattr(client, "get_accounts"):
        ok, data = client.get_all_accounts(page_size=page_size)
        if not ok:
            raise RuntimeError(str(data))
        return [item for item in (data or []) if isinstance(item, dict)]

    page = 1
    all_items: list[dict[str, Any]] = []
    total = None
    while True:
        ok, data = client.get_accounts(page=page, page_size=page_size)
        if not ok:
            raise RuntimeError(str(data))
        inner = data.get("data", {}) if isinstance(data, dict) else {}
        items = inner.get("items", []) if isinstance(inner, dict) else []
        if not items:
            break
        all_items.extend(item for item in items if isinstance(item, dict))
        total = int(inner.get("total") or 0)
        if total and len(all_items) >= total:
            break
        page += 1
    return all_items


def _build_cloud_identity_index(items: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    account_ids: set[str] = set()
    for item in items:
        name = _normalize_email(item.get("name"))
        if name:
            names.add(name)
        credentials = item.get("credentials") or {}
        account_id = _normalize_account_id(credentials.get("chatgpt_account_id"))
        if account_id:
            account_ids.add(account_id)
    return names, account_ids


def _fetch_local_success_rows() -> list[dict[str, Any]]:
    sql = """
        SELECT
            ra.id AS attempt_id,
            ra.run_id,
            COALESCE(NULLIF(ra.linked_account_email, ''), ra.email_full) AS email,
            ra.started_at,
            ra.finished_at,
            ra.proxy_name,
            ra.sub2api_push_ok,
            a.created_at AS account_created_at,
            a.token_data
        FROM registration_attempts ra
        INNER JOIN accounts a
            ON a.email = COALESCE(NULLIF(ra.linked_account_email, ''), ra.email_full)
        WHERE ra.source_mode = 'sub2api'
          AND ra.success_flag = 1
        ORDER BY ra.id DESC
    """
    with db_manager.get_db_conn(as_dict=True) as conn:
        cursor = db_manager.get_cursor(conn, as_dict=True)
        db_manager.execute_sql(cursor, sql)
        rows = cursor.fetchall()
    normalized_rows: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    for row in rows:
        item = dict(row)
        email = _normalize_email(item.get("email"))
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        token_payload = _load_token_payload(item.get("token_data"))
        item["email"] = email
        item["token_payload"] = token_payload
        item["chatgpt_account_id"] = _normalize_account_id(token_payload.get("account_id"))
        normalized_rows.append(item)
    return normalized_rows


def _build_missing_rows(
        *,
        local_rows: list[dict[str, Any]],
        cloud_names: set[str],
        cloud_account_ids: set[str],
        emails: Optional[list[str]] = None,
        limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    email_filter = {_normalize_email(item) for item in (emails or []) if _normalize_email(item)}
    missing_rows: list[dict[str, Any]] = []
    for row in local_rows:
        email = _normalize_email(row.get("email"))
        account_id = _normalize_account_id(row.get("chatgpt_account_id"))
        if email_filter and email not in email_filter:
            continue
        if account_id and account_id in cloud_account_ids:
            continue
        if email and email in cloud_names:
            continue
        missing_rows.append(
            {
                "attempt_id": int(row.get("attempt_id") or 0),
                "run_id": int(row.get("run_id") or 0),
                "email": email,
                "chatgpt_account_id": account_id,
                "proxy_name": str(row.get("proxy_name") or "").strip(),
                "started_at": str(row.get("started_at") or ""),
                "finished_at": str(row.get("finished_at") or ""),
                "account_created_at": str(row.get("account_created_at") or ""),
                "sub2api_push_ok": int(row.get("sub2api_push_ok") or 0),
                "token_payload": dict(row.get("token_payload") or {}),
                "possible_reason": "missing_in_sub2api_inventory",
            }
        )
        if limit and len(missing_rows) >= int(limit):
            break
    return missing_rows


def _record_reconcile_push_result(attempt_id: int, *, ok: bool, message: str) -> None:
    if int(attempt_id or 0) <= 0:
        return
    registration_history.patch_attempt(
        int(attempt_id),
        sub2api_push_ok=ok,
        failure_message="" if ok else str(message or "").strip(),
    )
    registration_history.record_attempt_event(
        int(attempt_id),
        event_type="sub2api_push_succeeded" if ok else "sub2api_push_failed",
        phase="sub2api_push",
        ok_flag=ok,
        message=str(message or ""),
        snapshot={"repair_mode": True},
    )


def list_missing_sub2api_accounts(
        client: Any,
        *,
        emails: Optional[list[str]] = None,
        limit: Optional[int] = None,
) -> dict[str, Any]:
    local_rows = _fetch_local_success_rows()
    cloud_items = _fetch_cloud_accounts_strict(client)
    cloud_names, cloud_account_ids = _build_cloud_identity_index(cloud_items)
    missing_rows = _build_missing_rows(
        local_rows=local_rows,
        cloud_names=cloud_names,
        cloud_account_ids=cloud_account_ids,
        emails=emails,
        limit=limit,
    )
    return {
        "local_success_total": len(local_rows),
        "cloud_total": len(cloud_items),
        "missing_total": len(missing_rows),
        "rows": missing_rows,
    }


def repair_missing_sub2api_accounts(
        client: Any,
        *,
        emails: Optional[list[str]] = None,
        limit: Optional[int] = None,
        max_attempts: int = 2,
) -> dict[str, Any]:
    audit = list_missing_sub2api_accounts(client, emails=emails, limit=limit)
    results: list[dict[str, Any]] = []
    repaired_total = 0
    failed_total = 0
    for row in audit["rows"]:
        attempt_id = int(row.get("attempt_id") or 0)
        token_payload = dict(row.get("token_payload") or {})
        email = _normalize_email(row.get("email"))
        message = ""
        registration_history.record_attempt_event(
            attempt_id,
            event_type="sub2api_push_started",
            phase="sub2api_push",
            ok_flag=True,
            message=f"repair attempt 1/{max(1, int(max_attempts or 1))}",
            snapshot={"repair_mode": True},
        )
        ok = False
        for _ in range(max(1, int(max_attempts or 1))):
            ok, message = client.add_account(token_payload)
            if ok:
                break
        _record_reconcile_push_result(attempt_id, ok=ok, message=str(message or ""))
        results.append(
            {
                "email": email,
                "chatgpt_account_id": _normalize_account_id(row.get("chatgpt_account_id")),
                "attempt_id": attempt_id,
                "status": "repaired" if ok else "failed",
                "message": str(message or ""),
            }
        )
        if ok:
            repaired_total += 1
        else:
            failed_total += 1
    return {
        "local_success_total": audit["local_success_total"],
        "cloud_total": audit["cloud_total"],
        "missing_total": audit["missing_total"],
        "repaired_total": repaired_total,
        "failed_total": failed_total,
        "results": results,
    }
