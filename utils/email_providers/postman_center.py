import threading
import time
import re
from collections import OrderedDict
from utils import config as cfg


global_code_pool = {}
code_pool_lock = threading.Lock()


class BoundedSet:
    def __init__(self, max_size=10000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = threading.Lock()

    def add(self, key):
        with self.lock:
            self.cache[key] = True
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def __contains__(self, key):
        with self.lock:
            return key in self.cache


processed_msg_ids = BoundedSet(max_size=20000)

class PostmanFleet:
    def __init__(self):
        self.active_mailboxes = set()
        self.listener_registry = {}
        self.postman_signals = {}
        self.fleet_lock = threading.Lock()

    @staticmethod
    def _normalize_master_email(master_email):
        return str(master_email or "").strip().lower()

    @staticmethod
    def _thread_is_alive(thread):
        checker = getattr(thread, "is_alive", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return True
        return bool(getattr(thread, "started", True))

    def reset_for_next_round(self):
        with code_pool_lock:
            global_code_pool.clear()

    def clear_fleet(self):
        stop_events = []
        with self.fleet_lock:
            self.active_mailboxes.clear()
            stop_events = [entry["stop_event"] for entry in self.listener_registry.values()]
            self.listener_registry.clear()
            self.postman_signals.clear()
        for stop_event in stop_events:
            stop_event.set()
        with code_pool_lock:
            global_code_pool.clear()
        print(f"[{cfg.ts()}] [INFO] 🛑 邮局总管已下达停工令，所有邮递员准备下班。")

    def acquire_mailbox_listener(self, ms_service, master_mailbox):
        normalized_mailbox = dict(master_mailbox or {})
        master_email = self._normalize_master_email(
            normalized_mailbox.get("master_email") or normalized_mailbox.get("email")
        )
        if not master_email:
            return {"master_email": "", "ref_count": 0, "created": False}

        normalized_mailbox["master_email"] = master_email
        from utils.email_providers.mail_service import mask_email

        with self.fleet_lock:
            entry = self.listener_registry.get(master_email)
            if entry and self._thread_is_alive(entry.get("thread")):
                entry["ref_count"] += 1
                entry["last_acquired_at"] = time.time()
                entry["mailbox"].update(normalized_mailbox)
                entry["ms_service"] = ms_service
                return {"master_email": master_email, "ref_count": entry["ref_count"], "created": False}

            if entry:
                self.listener_registry.pop(master_email, None)
                self.postman_signals.pop(master_email, None)

            stop_event = threading.Event()
            entry = {
                "stop_event": stop_event,
                "ref_count": 1,
                "mailbox": normalized_mailbox,
                "ms_service": ms_service,
                "thread": None,
                "last_acquired_at": time.time(),
            }
            thread = threading.Thread(
                target=self._exclusive_postman_worker,
                args=(master_email, entry, stop_event),
                daemon=True
            )
            entry["thread"] = thread
            self.listener_registry[master_email] = entry
            self.postman_signals[master_email] = stop_event

        thread.start()

        print(f"[{cfg.ts()}] [INFO] 📮 派发新邮递员！开始专属监听: {mask_email(master_email)}")
        return {"master_email": master_email, "ref_count": 1, "created": True}

    def ensure_mailbox_listener(self, ms_service, master_mailbox):
        return self.acquire_mailbox_listener(ms_service, master_mailbox)

    def add_mailbox_listener(self, ms_service, master_mailbox):
        self.acquire_mailbox_listener(ms_service, master_mailbox)

    def release_mailbox_listener(self, master_email):
        normalized_email = self._normalize_master_email(master_email)
        if not normalized_email:
            return {"master_email": "", "ref_count": 0, "stopped": False}

        stop_event = None
        remaining_refs = 0
        with self.fleet_lock:
            entry = self.listener_registry.get(normalized_email)
            if not entry:
                return {"master_email": normalized_email, "ref_count": 0, "stopped": False}

            entry["ref_count"] = max(0, int(entry.get("ref_count") or 0) - 1)
            remaining_refs = entry["ref_count"]
            if remaining_refs == 0:
                stop_event = entry["stop_event"]
                self.listener_registry.pop(normalized_email, None)
                self.postman_signals.pop(normalized_email, None)

        if stop_event:
            stop_event.set()
        return {
            "master_email": normalized_email,
            "ref_count": remaining_refs,
            "stopped": bool(stop_event),
        }

    def stop_mailbox_listener(self, master_email):
        normalized_email = self._normalize_master_email(master_email)
        if not normalized_email:
            return

        stop_event = None
        with self.fleet_lock:
            self.listener_registry.pop(normalized_email, None)
            stop_event = self.postman_signals.pop(normalized_email, None)
        if stop_event:
            stop_event.set()

    def _exclusive_postman_worker(self, master_email, entry, stop_event):
        master_email = self._normalize_master_email(master_email)
        while not getattr(cfg, 'GLOBAL_STOP', False) and not stop_event.is_set():
            try:
                master_mailbox = entry["mailbox"]
                ms_service = entry["ms_service"]
                messages = ms_service.fetch_openai_messages(master_mailbox)
                if master_mailbox.get("_polling_stopped") == "abuse_mode":
                    break

                for m in messages:
                    msg_id = m.get('id')

                    if not msg_id or msg_id in processed_msg_ids:
                        continue

                    processed_msg_ids.add(msg_id)

                    recs = [r.get('emailAddress', {}).get('address', '').lower() for r in m.get('toRecipients', [])]
                    body = m.get('body', {}).get('content', '')
                    body_preview = m.get('bodyPreview', '')
                    subject = str(m.get('subject', ''))
                    sender = str(m.get('from', {}).get('emailAddress', {}).get('address', '')).lower()
                    if "openai" not in sender and "openai" not in subject.lower():
                        continue

                    from utils.email_providers.mail_service import _extract_otp_code_from_email_parts
                    code = _extract_otp_code_from_email_parts(
                        subject=subject,
                        body_preview=body_preview,
                        body_html=body,
                    )

                    if code:
                        with code_pool_lock:
                            for alias in recs:
                                global_code_pool[alias] = code
            except Exception as e:
                from utils.email_providers.mail_service import mask_email
                print(f"[{cfg.ts()}] [WARNING] 邮递员 ({mask_email(master_email)}) 遭遇阻碍: {e}")
                time.sleep(5)

            for _ in range(8):
                if getattr(cfg, 'GLOBAL_STOP', False) or stop_event.is_set():
                    break
                time.sleep(0.5)
        with self.fleet_lock:
            current_entry = self.listener_registry.get(master_email)
            if current_entry and current_entry.get("stop_event") is stop_event:
                self.listener_registry.pop(master_email, None)
                self.postman_signals.pop(master_email, None)
        from utils.email_providers.mail_service import mask_email
        print(f"[{cfg.ts()}] [INFO] 🛑 ({mask_email(master_email)}) 的专属邮递员已下班，屏幕前的你下班了吗？。")


global_postman_fleet = PostmanFleet()

def wait_for_code(target_email, timeout=60):
    target_email = target_email.lower().strip()
    with code_pool_lock:
        global_code_pool.pop(target_email, None)

    start_time = time.time()
    while time.time() - start_time < timeout:
        with code_pool_lock:
            if target_email in global_code_pool:
                code = global_code_pool.pop(target_email)
                from utils.email_providers.mail_service import mask_email
                print(f"[{cfg.ts()}] [SUCCESS] 🎉 ({mask_email(target_email)}) 极速领到验证码: {code}")
                return code

        time.sleep(1)

    return ""
