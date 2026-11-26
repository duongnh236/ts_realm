"""Hồ sơ đăng nhập + chặn thử lại khi sai mật khẩu (theo TS Manager bản PC).

* ``login_profiles.json``: tài khoản đã đăng nhập được (tên, server, user_id, tên nhân vật,
  lần cuối). KHÔNG lưu mật khẩu.
* ``login_block.json``: server báo sai tên/mật khẩu thì ghi lại dấu vân tay của cặp
  tên + mật khẩu đó. Lần sau gặp đúng cặp đó thì không gửi lên server nữa (tránh bị khóa acc).
  Đổi mật khẩu = dấu khác = hết chặn ngay. Đăng nhập thành công thì xóa dấu.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

log = logging.getLogger("bot")

# Mã lỗi server khi sai tên / mật khẩu (APK: -53 = "sai tên/mật khẩu").
BAD_CREDENTIAL_CODES = {-53, "-53"}


class BadCredentials(SystemExit):
    pass


def _fingerprint(username: str, password: str) -> str:
    return hashlib.sha256(("ts_realm|%s|%s" % (username.lower(), password)).encode("utf-8")).hexdigest()


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class LoginGuard:
    def __init__(self, runtime_dir: str):
        self.block_path = os.path.join(runtime_dir, "login_block.json")
        self.profile_path = os.path.join(runtime_dir, "login_profiles.json")

    # ---- chặn sai mật khẩu ----
    def is_blocked(self, username, password):
        rec = _load(self.block_path).get(username.lower())
        return bool(rec) and rec.get("fp") == _fingerprint(username, password)

    def mark_bad(self, username, password, code=None):
        data = _load(self.block_path)
        data[username.lower()] = {"fp": _fingerprint(username, password), "code": code,
                                  "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save(self.block_path, data)

    def clear(self, username):
        data = _load(self.block_path)
        if data.pop(username.lower(), None) is not None:
            _save(self.block_path, data)

    # ---- hồ sơ ----
    def remember(self, username, server, user_id=None, character=None, label=None):
        data = _load(self.profile_path)
        rec = data.get(username.lower(), {})
        rec.update({"username": username, "server": server, "last_login": time.strftime("%Y-%m-%d %H:%M:%S")})
        if user_id is not None:
            rec["user_id"] = user_id
        if character:
            rec["character"] = character
        if label:
            rec["label"] = label
        data[username.lower()] = rec
        _save(self.profile_path, data)

    def profiles(self):
        return _load(self.profile_path)

    # ---- bọc hàm login của ts_bot ----
    def login(self, login_fn, username, password):
        if self.is_blocked(username, password):
            raise BadCredentials(
                "%s: lần trước server báo SAI tên/mật khẩu với đúng mật khẩu này — bot không thử lại "
                "(tránh khóa acc). Sửa mật khẩu trong settings.json rồi chạy lại." % username)
        try:
            cred = login_fn(username, password)
        except Exception as exc:
            code = getattr(exc, "error_code", None)
            if code in BAD_CREDENTIAL_CODES:
                self.mark_bad(username, password, code)
                raise BadCredentials("%s: sai tên hoặc mật khẩu (mã %s) — đã ghi nhớ, sẽ không thử lại "
                                     "cho tới khi đổi mật khẩu." % (username, code))
            raise
        self.clear(username)
        return cred
