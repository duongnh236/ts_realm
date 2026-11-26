"""Cầu nối cho app Android (Chaquopy). Mỗi tab trên app = một ``Session`` = một tài khoản.

Java gọi các hàm cấp module, mọi giá trị trả về là chuỗi JSON để Java đọc dễ:
    init(runtime_dir)                 -> {"ok": true, "servers": [...]}
    login(tab, user, pw, server)      -> {"ok": true}  (chạy nền; xem status)
    run(tab, features_json, opts_json)-> {"ok": true}  features: ["world_boss","npc40","nhi_kieu",...]
    stop(tab) / logout(tab)
    status(tab)                       -> {"state": ..., "char": ..., "map": ..., "task": ...}
    logs(tab, since)                  -> {"next": n, "lines": [...]}
Chạy được cả trên máy tính (test) nếu đã ``bootstrap.prepare``.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time

log = logging.getLogger("bot")

_SETTINGS = {
    "server": "ts_realm",
    "rules": {},
    "team_dungeon_level": 50,
    "max_losses": {"npc40": 3, "nhi_kieu": 3},
    "world_boss": {"use_tickets": True, "damage_goal": 5000000, "ticket_ids": [46629, 46614]},
}
_SESSIONS = {}
_LOCK = threading.Lock()
_INIT = {"done": False}
MAX_LINES = 600
LOG_FILE_MAX = 5 * 1024 * 1024


class _RingHandler(logging.Handler):
    """Gom log về từng phiên: dòng có ``[label]`` hoặc phát ra từ thread của phiên đó."""

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            return
        tname = record.threadName or ""
        for s in list(_SESSIONS.values()):
            if s.owns(msg, tname):
                s.add_line(msg)


def _json(obj):
    return json.dumps(obj, ensure_ascii=False)


def init(runtime_dir, settings_json=None):
    """Gọi một lần khi app mở. Gắn luật đánh vào train_bot.combat."""
    if settings_json:
        try:
            _SETTINGS.update(json.loads(settings_json))
        except ValueError:
            pass
    _SETTINGS["runtime_dir"] = _SETTINGS["_runtime_dir"] = runtime_dir
    os.makedirs(runtime_dir, exist_ok=True)
    if not _INIT["done"]:
        from train_bot import combat
        from .combat_rules import install
        install(combat, _SETTINGS.get("rules"))
        h = _RingHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        logging.getLogger("bot").addHandler(h)
        logging.getLogger("bot").setLevel(logging.INFO)
        _INIT["done"] = True
    return _json({"ok": True, "servers": servers()})


def servers():
    from train_bot import config
    from .realm_login import REALM_SERVERS
    return list(REALM_SERVERS) + sorted((getattr(config, "SERVERS", None) or {}).keys())


class Session:
    def __init__(self, tab):
        self.tab = str(tab)
        self.thread_prefix = "realm-%s" % self.tab
        self.label = None
        self.client = None
        self.state = "offline"      # offline | logging_in | online | running | error
        self.error = ""
        self.task = ""
        self.stop_event = threading.Event()
        self.worker = None
        self.lines = collections.deque(maxlen=MAX_LINES)
        self.total = 0
        self._llock = threading.Lock()
        self.view = None
        self.wb_settings = {}

    def owns(self, msg, tname):
        """Dòng log thuộc phiên này: thread của phiên, hoặc có ``[user]`` / ``[tên nhân vật]``."""
        if tname.startswith(self.thread_prefix):
            return True
        names = {self.label, getattr(self.client, "_label", None), getattr(self.client, "char_name", None)}
        return any(n and ("[%s]" % n) in msg for n in names)

    def log_path(self):
        d = os.path.join(_SETTINGS.get("runtime_dir") or "runtime", "logs")
        return os.path.join(d, "tab_%s.log" % self.tab)

    def add_line(self, line):
        with self._llock:
            self.lines.append(line)
            self.total += 1
            # Nhật ký đầy đủ chỉ ghi ra file (nút "Xuất nhật ký"), không hiện trên màn hình nữa.
            try:
                path = self.log_path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if os.path.exists(path) and os.path.getsize(path) > LOG_FILE_MAX:
                    os.replace(path, path + ".1")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def say(self, msg):
        self.add_line(time.strftime("%H:%M:%S ") + msg)

    # ---- đăng nhập ----
    def login(self, username, password, server):
        if self.state in ("logging_in", "running"):
            return {"ok": False, "error": "đang bận"}
        self.label = username
        self.cancel = threading.Event()
        cancel = self.cancel
        self.state, self.error = "logging_in", ""
        self.say("Đang đăng nhập %s (%s)..." % (username, server))

        def work():
            try:
                import train_bot
                from train_bot import config
                from .main import connect
                settings = dict(_SETTINGS, server=server)
                c = connect(train_bot, config, settings,
                            {"username": username, "password": password, "label": username,
                             "cancel": cancel})
                if cancel.is_set():
                    from .main import _drop
                    _drop(c)
                    return
                self.client = c
                try:
                    from .battle_view import BattleView
                    self.view = BattleView(c)
                except Exception as exc:          # bảng trạng thái hỏng không được chặn đăng nhập
                    self.view = None
                    self.say("Không bật được bảng trạng thái trận: %s" % exc)
                self.state = "online"
                self.say("Đã vào game: %s" % (getattr(self.client, "char_name", None) or username))
            except BaseException as exc:      # SystemExit từ connect/LoginGuard
                self.client = None
                if cancel.is_set():
                    return
                self.state, self.error = "error", str(exc)
                self.say("Đăng nhập lỗi: %s" % exc)

        threading.Thread(target=work, daemon=True, name=self.thread_prefix + "-login").start()
        return {"ok": True}

    def logout(self):
        was_logging_in = self.state == "logging_in"
        cancel = getattr(self, "cancel", None)
        if cancel is not None:
            cancel.set()          # dừng vòng đăng nhập / thử lại đang chạy
        self.stop()
        c, self.client = self.client, None
        if c is not None:
            try:
                c.running = False
                c.close()
            except Exception:
                pass
        self.view = None
        self.state, self.task = "offline", ""
        self.say("Đã huỷ đăng nhập" if was_logging_in else "Đã đăng xuất")
        return {"ok": True}

    # ---- chạy hoạt động ----
    def run(self, features, opts):
        if self.client is None or not self.client.running:
            return {"ok": False, "error": "chưa đăng nhập"}
        if self.worker is not None and self.worker.is_alive():
            return {"ok": False, "error": "đang chạy %s" % self.task}
        settings = json.loads(json.dumps(_SETTINGS))
        for k in ("world_boss", "max_losses"):
            if isinstance(opts.get(k), dict):
                settings.setdefault(k, {}).update(opts[k])
        if isinstance(opts.get("loadouts"), dict):   # đội hình 40 NPC / Nhị Kiều chọn trong app
            settings["loadouts"] = dict(opts["loadouts"])
        if "team_dungeon_level" in opts:
            settings["team_dungeon_level"] = int(opts["team_dungeon_level"])
        self.wb_settings = dict(settings.get("world_boss") or {})
        self.stop_event = threading.Event()

        def work():
            from train_bot import config
            from .features import Runner
            self.state = "running"
            try:
                r = Runner(self.client, config, settings, self.stop_event)
                for name in features:
                    if self.stop_event.is_set():
                        break
                    self.task = name
                    r.run([name])
            except Exception as exc:
                self.say("Lỗi: %s" % exc)
            finally:
                self.task = ""
                self.state = "online" if (self.client is not None and self.client.running) else "offline"
                self.say("Xong lượt chạy")

        self.worker = threading.Thread(target=work, daemon=True, name=self.thread_prefix + "-run")
        self.worker.start()
        return {"ok": True}

    def stop(self):
        self.stop_event.set()
        c = self.client
        if c is not None:
            for fn in ("stop_npc40_loop", "stop_floor_crawl"):
                try:
                    getattr(c, fn)()
                except Exception:
                    pass
        if self.worker is not None and self.worker.is_alive():
            self.say("Đã bấm dừng — xong trận đang đánh thì dừng")
        return {"ok": True}

    def status(self):
        c = self.client
        if c is not None and not c.running and self.state in ("online", "running"):
            self.state = "offline"
            self.error = "mất kết nối"
        out = {"state": self.state, "error": self.error, "task": self.task, "user": self.label}
        if c is not None:
            out.update(char=getattr(c, "char_name", None), map=getattr(c, "current_map", None),
                       boss=[getattr(c, "world_boss_count", None), getattr(c, "world_boss_max", None)])
            out["wb"] = self._wb_summary(c)
            try:
                from .loadout import loadout
                out["loadout"] = loadout(c)
            except Exception:
                pass
            if self.view is not None:
                try:
                    out["battle"] = self.view.snapshot()
                except Exception:
                    pass
        return out

    def _wb_summary(self, c):
        """Dame boss hôm nay (bot tự cộng), mục tiêu, số vé đang có trong túi."""
        opts = dict(_SETTINGS.get("world_boss") or {})
        opts.update(self.wb_settings or {})
        ids = [int(x) for x in (opts.get("ticket_ids") or (46629, 46614))]
        tickets = {}
        for tid, cnt in list((getattr(c, "bag_slots", None) or {}).values()):
            if int(tid) in ids:
                tickets[int(tid)] = tickets.get(int(tid), 0) + int(cnt)
        today = None
        try:
            from .features import server_now
            from .world_boss import DamageLog
            runtime = _SETTINGS.get("_runtime_dir") or _SETTINGS.get("runtime_dir") or "runtime"
            dlog = DamageLog(os.path.join(runtime, "world_boss_damage.json"))
            from .world_boss import today_damage
            today = today_damage(c, dlog, getattr(c, "_username", None) or "acc",
                                 server_now(7).strftime("%Y-%m-%d"))
        except Exception:
            pass
        return {"today": today, "goal": int(opts.get("damage_goal") or 5000000),
                "tickets": sum(tickets.values()), "tickets_by_id": {str(k): v for k, v in tickets.items()}}

    def export_log(self):
        """Gom file nhật ký (cũ + mới) thành một file để app chép ra thư mục Download."""
        path = self.log_path()
        out = os.path.join(os.path.dirname(path), "export_tab_%s.log" % self.tab)
        try:
            with open(out, "w", encoding="utf-8") as w:
                for p in (path + ".1", path):
                    if os.path.exists(p):
                        with open(p, encoding="utf-8") as r:
                            w.write(r.read())
            return {"ok": True, "path": out, "name": "tsrealm_%s_%s.log" % (
                (self.label or "tab%s" % self.tab).split("@")[0], time.strftime("%Y%m%d_%H%M%S"))}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def logs(self, since):
        with self._llock:
            first = self.total - len(self.lines)
            start = max(int(since), first)
            lines = list(self.lines)[start - first:]
            return {"next": self.total, "lines": lines}


def _session(tab):
    with _LOCK:
        s = _SESSIONS.get(str(tab))
        if s is None:
            s = _SESSIONS[str(tab)] = Session(tab)
        return s


def login(tab, username, password, server):
    return _json(_session(tab).login(username, password, server))


def logout(tab):
    return _json(_session(tab).logout())


def close_tab(tab):
    s = _SESSIONS.pop(str(tab), None)
    if s is not None:
        s.logout()
    return _json({"ok": True})


def run(tab, features_json, opts_json="{}"):
    return _json(_session(tab).run(json.loads(features_json), json.loads(opts_json or "{}")))


def stop(tab):
    return _json(_session(tab).stop())


def status(tab):
    return _json(_session(tab).status())


def export_log(tab):
    return _json(_session(tab).export_log())


def logs(tab, since=0):
    return _json(_session(tab).logs(since))


def busy_count():
    return sum(1 for s in _SESSIONS.values() if s.state in ("online", "running", "logging_in"))
