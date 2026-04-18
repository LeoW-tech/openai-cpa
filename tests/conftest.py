import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
root_str = str(ROOT_DIR)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

# 预加载真实 db_manager，避免个别测试用 setdefault 注入精简 stub 后污染整场测试会话。
import utils.db_manager  # noqa: F401
