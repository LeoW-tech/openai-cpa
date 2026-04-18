import sqlite3
import json
import os
from datetime import datetime
from typing import Any

try:
    import pymysql
except ImportError:
    pymysql = None

from utils.config import DB_TYPE, MYSQL_CFG

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "data.db")


class SystemKvStorageError(RuntimeError):
    """system_kv 读写层面的不可恢复存储错误。"""


def _is_system_kv_storage_error(exc: Exception) -> bool:
    if isinstance(exc, SystemKvStorageError):
        return True
    message = str(exc or "").lower()
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    return any(
        marker in message
        for marker in (
            "database disk image is malformed",
            "malformed",
            "database corruption",
            "disk image is malformed",
            "corrupt",
        )
    )


def _raise_system_kv_storage_error(action: str, key: str, exc: Exception) -> None:
    raise SystemKvStorageError(f"system_kv {action}失败: key={key}, error={exc}") from exc


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")
class get_db_conn:
    """抹平 SQLite 和 MySQL 连接差异"""
    def __init__(self, as_dict=False):
        self.as_dict = as_dict

    def __enter__(self):
        if DB_TYPE == "mysql":
            if pymysql is None:
                raise RuntimeError("pymysql is required when DB_TYPE=mysql")
            self.conn = pymysql.connect(
                host=MYSQL_CFG.get('host', '127.0.0.1'),
                port=MYSQL_CFG.get('port', 3306),
                user=MYSQL_CFG.get('user', 'root'),
                password=MYSQL_CFG.get('password', ''),
                database=MYSQL_CFG.get('db_name', 'wenfxl_manager'),
                charset='utf8mb4'
            )
        else:
            self.conn = sqlite3.connect(DB_PATH, timeout=10)
            if self.as_dict:
                self.conn.row_factory = sqlite3.Row
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


def get_cursor(conn, as_dict=False):
    """获取适配的游标"""
    if DB_TYPE == "mysql" and as_dict:
        if pymysql is None:
            raise RuntimeError("pymysql is required when DB_TYPE=mysql")
        return conn.cursor(pymysql.cursors.DictCursor)
    return conn.cursor()


def execute_sql(cursor, sql: str, params=()):
    if DB_TYPE == "mysql":
        sql = sql.replace('?', '%s')
        sql = sql.replace('AUTOINCREMENT', 'AUTO_INCREMENT')

        sql = sql.replace('INSERT OR IGNORE', 'INSERT IGNORE')
        sql = sql.replace('INSERT OR REPLACE', 'REPLACE')

        sql = sql.replace('TEXT UNIQUE', 'VARCHAR(191) UNIQUE')
        sql = sql.replace('TEXT PRIMARY KEY', 'VARCHAR(191) PRIMARY KEY')

        # 3. 抹平特殊的 PRAGMA
        if 'PRAGMA' in sql:
            return None

    return cursor.execute(sql, params)

def init_db():
    """初始化数据库，自动适应双引擎建表"""
    with get_db_conn() as conn:
        c = get_cursor(conn)
        execute_sql(c, 'PRAGMA journal_mode=WAL;')
        execute_sql(c, 'PRAGMA synchronous=NORMAL;')

        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password TEXT,
                token_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS system_kv (
                `key` TEXT PRIMARY KEY, 
                value TEXT
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS local_mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password TEXT,
                client_id TEXT,
                refresh_token TEXT,
                status INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS registration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_mode TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                target_count INTEGER DEFAULT 0,
                config_snapshot_json TEXT,
                trigger_source TEXT,
                host_name TEXT,
                worker_id TEXT,
                notes_json TEXT
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS registration_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                task_id TEXT,
                worker_id TEXT,
                source_mode TEXT,
                source_node_name TEXT,
                external_attempt_id TEXT,
                token_fingerprint TEXT,
                attempt_no INTEGER DEFAULT 1,
                flow_type TEXT,
                legacy_backfill INTEGER DEFAULT 0,
                linked_account_email TEXT,
                linked_account_created_at TIMESTAMP,
                email_full TEXT,
                email_local_part TEXT,
                email_domain TEXT,
                master_email TEXT,
                email_provider_type TEXT,
                email_provider_detail TEXT,
                proxy_url TEXT,
                proxy_name TEXT,
                exit_ip TEXT,
                geo_country_code TEXT,
                geo_country_name TEXT,
                geo_region_name TEXT,
                geo_city_name TEXT,
                geo_isp TEXT,
                geo_asn TEXT,
                geo_source TEXT,
                geo_status TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                total_duration_ms INTEGER,
                email_otp_duration_ms INTEGER,
                phone_otp_duration_ms INTEGER,
                oauth_duration_ms INTEGER,
                account_create_duration_ms INTEGER,
                callback_duration_ms INTEGER,
                final_status TEXT,
                success_flag INTEGER DEFAULT 0,
                retry_403_flag INTEGER DEFAULT 0,
                signup_blocked_flag INTEGER DEFAULT 0,
                pwd_blocked_flag INTEGER DEFAULT 0,
                phone_gate_hit_flag INTEGER DEFAULT 0,
                phone_otp_entered_flag INTEGER DEFAULT 0,
                phone_otp_success_flag INTEGER DEFAULT 0,
                email_otp_send_count INTEGER DEFAULT 0,
                email_otp_resend_count INTEGER DEFAULT 0,
                email_otp_validate_count INTEGER DEFAULT 0,
                email_otp_401_retry_count INTEGER DEFAULT 0,
                phone_otp_send_count INTEGER DEFAULT 0,
                phone_otp_validate_count INTEGER DEFAULT 0,
                phone_otp_provider TEXT,
                phone_otp_country TEXT,
                phone_reuse_used_flag INTEGER DEFAULT 0,
                phone_number_full TEXT,
                phone_number_e164 TEXT,
                phone_country_calling_code TEXT,
                phone_country_iso TEXT,
                phone_country_name TEXT,
                phone_national_number TEXT,
                phone_activation_id TEXT,
                phone_bind_provider TEXT,
                phone_bind_attempted_flag INTEGER DEFAULT 0,
                phone_bind_success_flag INTEGER DEFAULT 0,
                phone_bind_failed_flag INTEGER DEFAULT 0,
                phone_bind_failure_reason TEXT,
                phone_bind_stage TEXT,
                local_save_ok INTEGER DEFAULT 0,
                cpa_upload_ok INTEGER DEFAULT 0,
                sub2api_push_ok INTEGER DEFAULT 0,
                failure_stage TEXT,
                failure_code TEXT,
                failure_message TEXT,
                last_continue_url TEXT,
                last_http_status INTEGER,
                labels_json TEXT,
                metrics_json TEXT,
                result_snapshot_json TEXT
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS registration_attempt_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER,
                seq_no INTEGER DEFAULT 0,
                event_type TEXT,
                phase TEXT,
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                elapsed_ms INTEGER,
                ok_flag INTEGER,
                http_status INTEGER,
                reason_code TEXT,
                message TEXT,
                url_key TEXT,
                snapshot_json TEXT
            )
        ''')
        execute_sql(c, '''
            CREATE TABLE IF NOT EXISTS ip_geo_cache (
                ip TEXT PRIMARY KEY,
                resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                country_code TEXT,
                country_name TEXT,
                region_name TEXT,
                city_name TEXT,
                isp TEXT,
                asn TEXT,
                source TEXT,
                raw_json TEXT,
                status TEXT
            )
        ''')
        try:
            execute_sql(c, 'ALTER TABLE local_mailboxes ADD COLUMN fission_count INTEGER DEFAULT 0;')
            execute_sql(c, 'ALTER TABLE local_mailboxes ADD COLUMN retry_master INTEGER DEFAULT 0;')
        except Exception:
            pass
        for alter_sql in (
            'ALTER TABLE registration_attempts ADD COLUMN source_node_name TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN external_attempt_id TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN token_fingerprint TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_number_full TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_number_e164 TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_country_calling_code TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_country_iso TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_country_name TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_national_number TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_activation_id TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_provider TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_attempted_flag INTEGER DEFAULT 0;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_success_flag INTEGER DEFAULT 0;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_failed_flag INTEGER DEFAULT 0;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_failure_reason TEXT;',
            'ALTER TABLE registration_attempts ADD COLUMN phone_bind_stage TEXT;',
        ):
            try:
                execute_sql(c, alter_sql)
            except Exception:
                pass
        for index_sql in (
            'CREATE INDEX IF NOT EXISTS idx_registration_runs_started_at ON registration_runs(started_at)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_started_at ON registration_attempts(started_at)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_final_status ON registration_attempts(final_status)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_success_flag ON registration_attempts(success_flag)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_phone_otp_entered ON registration_attempts(phone_otp_entered_flag)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_phone_bind_attempted ON registration_attempts(phone_bind_attempted_flag)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_phone_bind_success ON registration_attempts(phone_bind_success_flag)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_proxy_name ON registration_attempts(proxy_name)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_exit_ip ON registration_attempts(exit_ip)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_geo_country_name ON registration_attempts(geo_country_name)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_email_domain ON registration_attempts(email_domain)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_source_mode ON registration_attempts(source_mode)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_task_id ON registration_attempts(task_id)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_run_id ON registration_attempts(run_id)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_external_attempt_id ON registration_attempts(external_attempt_id)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempts_source_node_name ON registration_attempts(source_node_name)',
            'CREATE INDEX IF NOT EXISTS idx_registration_attempt_events_attempt_seq ON registration_attempt_events(attempt_id, seq_no)',
        ):
            try:
                execute_sql(c, index_sql)
            except Exception:
                pass
    print(f"[{ts()}] [系统] 数据库模块初始化完成 (引擎: {DB_TYPE.upper()})")


def save_account_to_db(email: str, password: str, token_json_str: str) -> bool:
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, '''
                INSERT OR REPLACE INTO accounts (email, password, token_data)
                VALUES (?, ?, ?)
            ''', (email, password, token_json_str))
            return True
    except Exception as e:
        print(f"[{ts()}] [ERROR] 数据库保存失败: {e}")
        return False


def get_all_accounts() -> list:
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT email, password, created_at FROM accounts ORDER BY id DESC")
            rows = c.fetchall()
            # MySQL 默认游标返回的也是元组，兼容原版切片逻辑
            return [{"email": r[0], "password": r[1], "created_at": r[2]} for r in rows]
    except Exception as e:
        print(f"[{ts()}] [ERROR] 获取账号列表失败: {e}")
        return []


def get_token_by_email(email: str) -> dict:
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT token_data FROM accounts WHERE email = ?", (email,))
            row = c.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return None
    except Exception as e:
        print(f"[{ts()}] [ERROR] 读取 Token 失败: {e}")
        return None


def get_tokens_by_emails(emails: list) -> list:
    if not emails: return []
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            placeholders = ','.join(['?'] * len(emails))
            execute_sql(c, f"SELECT token_data FROM accounts WHERE email IN ({placeholders})", tuple(emails))
            rows = c.fetchall()

            export_list = []
            for r in rows:
                if r[0]:
                    try:
                        export_list.append(json.loads(r[0]))
                    except:
                        pass
            return export_list
    except Exception as e:
        return []


def delete_accounts_by_emails(emails: list) -> bool:
    if not emails: return True
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            placeholders = ','.join(['?'] * len(emails))
            execute_sql(c, f"DELETE FROM accounts WHERE email IN ({placeholders})", tuple(emails))
            return True
    except Exception as e:
        print(f"[{ts()}] [ERROR] 数据库批量删除账号异常: {e}")
        return False


def get_accounts_page(page: int = 1, page_size: int = 50) -> dict:
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT COUNT(1) FROM accounts")
            total = c.fetchone()[0]

            offset = (page - 1) * page_size
            execute_sql(c, "SELECT email, password, created_at, token_data FROM accounts ORDER BY id DESC LIMIT ? OFFSET ?",
                        (page_size, offset))
            rows = c.fetchall()

            data = [
                {
                    "email": r[0],
                    "password": r[1],
                    "created_at": r[2],
                    "status": "有凭证" if '"access_token"' in str(r[3] or "") else (
                        "仅注册成功" if '"仅注册成功"' in str(r[3] or "") else "未知")
                }
                for r in rows
            ]
            return {"total": total, "data": data}
    except Exception as e:
        print(f"[{ts()}] [ERROR] 分页获取账号列表失败: {e}")
        return {"total": 0, "data": []}


def set_sys_kv(key: str, value: Any):
    try:
        val_str = json.dumps(value, ensure_ascii=False)
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "INSERT OR REPLACE INTO system_kv (`key`, value) VALUES (?, ?)", (key, val_str))
    except Exception as e:
        if _is_system_kv_storage_error(e):
            _raise_system_kv_storage_error("写入", key, e)
        print(f"[{ts()}] [ERROR] 系统配置保存失败: {e}")


def get_sys_kv(key: str, default=None):
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT value FROM system_kv WHERE `key` = ?", (key,))
            row = c.fetchone()
            if row:
                return json.loads(row[0])
    except Exception as e:
        if _is_system_kv_storage_error(e):
            _raise_system_kv_storage_error("读取", key, e)
        print(f"[{ts()}] [ERROR] 系统配置读取失败: {e}")
    return default


def get_system_kv_health() -> dict[str, Any]:
    """检查 system_kv 是否可读。"""
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT `key` FROM system_kv LIMIT 1")
            c.fetchall()
        return {"ok": True, "scope": "system_kv", "reason": ""}
    except Exception as e:
        reason = str(e)
        if _is_system_kv_storage_error(e):
            reason = f"system_kv 存储损坏: {e}"
        return {"ok": False, "scope": "system_kv", "reason": reason}


def get_all_accounts_with_token(limit: int = 10000) -> list:
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT email, password, token_data FROM accounts ORDER BY id DESC LIMIT ?", (limit,))
            rows = c.fetchall()
            return [{"email": r[0], "password": r[1], "token_data": r[2]} for r in rows]
    except Exception as e:
        print(f"[{ts()}] [ERROR] 提取完整账号数据失败: {e}")
        return []


def import_local_mailboxes(mailboxes_data: list) -> int:
    count = 0
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            for mb in mailboxes_data:
                try:
                    execute_sql(c, '''
                        INSERT OR IGNORE INTO local_mailboxes (email, password, client_id, refresh_token, status)
                        VALUES (?, ?, ?, ?, 0)
                    ''', (mb['email'], mb['password'], mb.get('client_id', ''), mb.get('refresh_token', '')))
                    if c.rowcount > 0:
                        count += 1
                except:
                    pass
    except Exception as e:
        print(f"[{ts()}] [ERROR] 导入邮箱库失败: {e}")
    return count


def get_local_mailboxes_page(page: int = 1, page_size: int = 50) -> dict:
    try:
        # as_dict=True 通知游标返回字典格式，适配原来的 sqlite3.Row
        with get_db_conn(as_dict=True) as conn:
            c = get_cursor(conn, as_dict=True)
            execute_sql(c, "SELECT COUNT(1) AS cnt FROM local_mailboxes")
            total_row = c.fetchone()
            total = total_row['cnt'] if DB_TYPE == "mysql" else total_row[0]

            offset = (page - 1) * page_size
            execute_sql(c, "SELECT * FROM local_mailboxes ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, offset))
            rows = c.fetchall()
            return {"total": total, "data": [dict(r) for r in rows]}
    except Exception as e:
        return {"total": 0, "data": []}


def delete_local_mailboxes(ids: list) -> bool:
    if not ids: return True
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            placeholders = ','.join(['?'] * len(ids))
            execute_sql(c, f"DELETE FROM local_mailboxes WHERE id IN ({placeholders})", tuple(ids))
            return True
    except Exception as e:
        return False

def get_and_lock_unused_local_mailbox() -> dict:
    """提取一个未使用的账号，并状态锁定为占用中"""
    try:
        with get_db_conn(as_dict=True) as conn:
            c = get_cursor(conn, as_dict=True)

            filter_sql = """
                SELECT * FROM local_mailboxes 
                WHERE status = 0 
                AND email NOT IN (SELECT email FROM accounts) 
                ORDER BY id ASC LIMIT 1
            """

            if DB_TYPE == "mysql":
                execute_sql(c, "START TRANSACTION")
                execute_sql(c, filter_sql + " FOR UPDATE")
            else:
                execute_sql(c, "BEGIN EXCLUSIVE")
                execute_sql(c, filter_sql)

            row = c.fetchone()
            if row:
                execute_sql(c, "UPDATE local_mailboxes SET status = 1 WHERE id = ?", (row['id'],))
                return dict(row)
            return None
    except Exception as e:
        print(f"[{ts()}] [ERROR] 提取本地邮箱失败: {e}")
        return None


def get_mailbox_for_pool_fission() -> dict:
    """带重试优先级的并发取号"""
    try:
        with get_db_conn(as_dict=True) as conn:
            c = get_cursor(conn, as_dict=True)
            if DB_TYPE == "mysql":
                execute_sql(c, "START TRANSACTION")
                execute_sql(c, "SELECT * FROM local_mailboxes WHERE status = 0 AND retry_master = 1 LIMIT 1 FOR UPDATE")
            else:
                execute_sql(c, "BEGIN EXCLUSIVE")
                execute_sql(c, "SELECT * FROM local_mailboxes WHERE status = 0 AND retry_master = 1 LIMIT 1")

            row = c.fetchone()

            if not row:
                if DB_TYPE == "mysql":
                    execute_sql(c,
                                "SELECT * FROM local_mailboxes WHERE status = 0 ORDER BY fission_count ASC LIMIT 1 FOR UPDATE")
                else:
                    execute_sql(c, "SELECT * FROM local_mailboxes WHERE status = 0 ORDER BY fission_count ASC LIMIT 1")
                row = c.fetchone()

            if row:
                execute_sql(c, "UPDATE local_mailboxes SET fission_count = fission_count + 1 WHERE id = ?",
                            (row['id'],))
                return dict(row)
            return None
    except Exception as e:
        print(f"[{ts()}] [DB_ERROR] 提取失败: {e}")
        return None


def update_local_mailbox_status(email: str, status: int):
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "UPDATE local_mailboxes SET status = ? WHERE email = ?", (status, email))
    except Exception:
        pass

def update_local_mailbox_refresh_token(email: str, new_rt: str):
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "UPDATE local_mailboxes SET refresh_token = ? WHERE email = ?", (new_rt, email))
    except Exception:
        pass


def update_pool_fission_result(email: str, is_blocked: bool, is_raw: bool):
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            if not is_blocked:
                execute_sql(c, "UPDATE local_mailboxes SET retry_master = 0 WHERE email = ?", (email,))
            else:
                if not is_raw:
                    execute_sql(c, "UPDATE local_mailboxes SET retry_master = 1 WHERE email = ?", (email,))
                else:
                    execute_sql(c, "UPDATE local_mailboxes SET status = 3, retry_master = 0 WHERE email = ?", (email,))
    except Exception as e:
        print(f"[{ts()}] [DB_ERROR] 结果更新失败: {e}")

def clear_retry_master_status(email: str):
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "UPDATE local_mailboxes SET retry_master = 0 WHERE email = ?", (email,))
    except Exception as e:
        print(f"[{ts()}] [DB_ERROR] 清除 {email} 的 retry_master 状态失败: {e}")

def get_all_accounts_raw() -> list:
    """获取账号库所有原始数据"""
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "SELECT email, password, token_data FROM accounts ORDER BY id DESC")
            rows = c.fetchall()
            return [{"email": r[0], "password": r[1], "token_data": json.loads(r[2]) if r[2] else {}} for r in rows]
    except: return []

def clear_all_accounts() -> bool:
    """一键清空账号库"""
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "DELETE FROM accounts")
            return True
    except: return False

def get_all_mailboxes_raw() -> list:
    """获取邮箱库所有原始数据"""
    try:
        with get_db_conn(as_dict=True) as conn:
            c = get_cursor(conn, as_dict=True)
            execute_sql(c, "SELECT * FROM local_mailboxes ORDER BY id DESC")
            return [dict(r) for r in c.fetchall()]
    except: return []

def clear_all_mailboxes() -> bool:
    """一键清空邮箱库"""
    try:
        with get_db_conn() as conn:
            c = get_cursor(conn)
            execute_sql(c, "DELETE FROM local_mailboxes")
            return True
    except: return False
