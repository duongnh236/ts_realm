"""Nạp gói ``train_bot`` của ts_bot để chạy trên máy tính (không cần Android/Chaquopy)."""
from __future__ import annotations

import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_settings(path: str = None) -> dict:
    path = path or os.path.join(ROOT, "settings.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _expand(p: str) -> str:
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def prepare(settings: dict):
    """Đặt đường dẫn ts_bot, thư mục runtime và dữ liệu game. Trả về module ``train_bot``."""
    py = _expand(settings.get("ts_bot_python", "~/Documents/ts_bot/app/src/main/python"))
    data = _expand(settings.get("ts_bot_data", "~/Documents/ts_bot/app/src/main/assets/train_bot_data"))
    runtime = _expand(settings.get("runtime_dir", "runtime"))
    if not os.path.isdir(os.path.join(py, "train_bot")):
        raise SystemExit("Không thấy train_bot trong %s — sửa ts_bot_python trong settings.json" % py)
    if not os.path.isdir(data):
        raise SystemExit("Không thấy dữ liệu game %s — sửa ts_bot_data trong settings.json" % data)
    # config.py đọc dữ liệu ở <app_dir>/bot_bundle/current/data/<file>
    bundle = os.path.join(runtime, "bot_bundle", "current")
    os.makedirs(bundle, exist_ok=True)
    link = os.path.join(bundle, "data")
    if not os.path.exists(link):
        os.symlink(data, link)
    if py not in sys.path:
        sys.path.insert(0, py)
    import train_bot  # gói rỗng, chưa nạp config

    # _appdir.py của ts_bot gọi Chaquopy -> thay bằng thư mục runtime của ts_realm
    stub = types.ModuleType("train_bot._appdir")
    stub.app_dir = lambda: runtime
    sys.modules["train_bot._appdir"] = stub
    train_bot._appdir = stub
    return train_bot
