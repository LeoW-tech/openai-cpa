import os
from pathlib import Path


PUBLIC_HOST_ENV = "OPENAI_CPA_PUBLIC_HOST"
PUBLIC_PORT_ENV = "OPENAI_CPA_PUBLIC_PORT"
HOST_PROJECT_PATH_ENV = "HOST_PROJECT_PATH"


def get_public_console_url(default_host: str = "127.0.0.1", default_port: int = 18000) -> str:
    host = str(os.getenv(PUBLIC_HOST_ENV, default_host) or "").strip() or default_host
    raw_port = str(os.getenv(PUBLIC_PORT_ENV, "") or "").strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = int(default_port)
    if port <= 0:
        port = int(default_port)
    return f"http://{host}:{port}"


def get_local_storage_paths(repo_root: str | Path) -> tuple[str, str]:
    root = Path(str(os.getenv(HOST_PROJECT_PATH_ENV, "") or "").strip() or repo_root).resolve()
    data_dir = root / "data"
    db_path = data_dir / "data.db"
    return str(data_dir), str(db_path)
