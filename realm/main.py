"""python -m realm.main --account acc1 --features world_boss,npc40,nhi_kieu,pb_don,pb_doi"""
from __future__ import annotations

import argparse
import getpass
import logging
import signal
import threading
import time

from . import bootstrap
from .login_guard import LoginGuard

log = logging.getLogger("bot")


def connect(train_bot, cfg_mod, settings, account):
    from train_bot import client as client_mod
    from train_bot.client import GameClient
    from . import realm_login
    server = settings.get("server", "ts_realm")
    if realm_login.is_realm_server(server):
        # TS Realm: không có HTTP login, tài khoản/mật khẩu đi thẳng trong gói TCP 001-000.
        realm_login.install(client_mod)
        login = realm_login.realm_login
        sv = realm_login.REALM_SERVERS[server]
        ip, sid = sv["ip"], sv["id"]
    else:
        from train_bot.login import login
        ip_fn = getattr(cfg_mod, "server_ip", None) or getattr(cfg_mod, "_server_ip")
        id_fn = getattr(cfg_mod, "server_id", None) or getattr(cfg_mod, "_server_id")
        ip, sid = ip_fn(server), id_fn(server)
    if not ip:
        raise SystemExit("server '%s' không có trong servers.json của ts_bot" % server)
    guard = LoginGuard(bootstrap._expand(settings.get("runtime_dir", "runtime")))
    password = account.get("password") or getpass.getpass("Mật khẩu %s: " % account["username"])
    cred = guard.login(login, account["username"], password)
    # TS Realm: có lúc server nhận đăng nhập (trả 001-002) rồi im sau 003-001, không gửi dữ liệu
    # vào map. Game thật cũng bị y hệt (log 26/11: cùng một gói login, lần kẹt lần vào được).
    # Kẹt thì đóng kết nối, chờ rồi thử lại thay vì để client tự relogin liên tục.
    attempts = int(settings.get("login_attempts", 4))
    wait_s = int(settings.get("login_wait_s", 30))
    retry_s = int(settings.get("login_retry_s", 90))
    realm = realm_login.is_realm_server(server)
    last = "đăng nhập xong nhưng chưa vào được game"
    cancel = account.get("cancel")
    cancelled = lambda: cancel is not None and cancel.is_set()
    for attempt in range(1, attempts + 1):
        if cancelled():
            raise SystemExit("đã huỷ đăng nhập")
        c = GameClient(cred["user_id"], cred["access_token"], host=ip, server_id=sid)
        c._label = account.get("label") or account["username"]
        c._username = account["username"]
        c.party_idx = None
        c.connect()
        for _ in range(wait_s):
            if cancelled():
                _drop(c)
                raise SystemExit("đã huỷ đăng nhập")
            # Phải có cả bảng nhiệm vụ S:024 (tới ngay sau S:003-000 khi server nạp xong). Có lần
            # server gửi tới 005-011 rồi im hẳn (log 26/11 13:49): có entity + map nhưng nhân vật
            # chưa vào thật, mọi lệnh sau đó đều không được trả lời.
            if (c.self_entity is not None and c.current_map is not None
                    and (not realm or getattr(c, "mission_steps_loaded", True))):
                guard.remember(account["username"], server, cred.get("user_id"),
                               getattr(c, "char_name", None), account.get("label"))
                return c
            if int(getattr(c, "disconnect_cause", 0) or 0):
                _drop(c)
                raise SystemExit("server ngắt kết nối khi đăng nhập, mã %s" % c.disconnect_cause)
            time.sleep(1)
        _drop(c)
        if attempt < attempts:
            log.warning("[%s] server chưa cho vào map sau %ds (lần %d/%d) -> chờ %ds rồi thử lại",
                        c._label, wait_s, attempt, attempts, retry_s)
            if cancel is not None:
                if cancel.wait(retry_s):
                    raise SystemExit("đã huỷ đăng nhập")
            else:
                time.sleep(retry_s)
    raise SystemExit("%s (đã thử %d lần)" % (last, attempts))


def _drop(c):
    """Đóng hẳn client đăng nhập hỏng, không để nó tự relogin."""
    try:
        c.running = False
        c._deliberate_close = True
        c.close()
    except Exception:
        try:
            c.sock.close()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="TS Realm")
    ap.add_argument("--settings", default=None)
    ap.add_argument("--account", default=None, help="tên trong settings.json -> accounts")
    ap.add_argument("--features", default="world_boss,nhi_kieu,npc40,pb_don,pb_doi")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    settings = bootstrap.load_settings(a.settings)
    settings["_runtime_dir"] = bootstrap._expand(settings.get("runtime_dir", "runtime"))
    train_bot = bootstrap.prepare(settings)
    from train_bot import combat, config
    from .combat_rules import install
    install(combat, settings.get("rules"))
    accounts = settings.get("accounts") or {}
    name = a.account or next(iter(accounts), None)
    if not name or name not in accounts:
        raise SystemExit("chưa khai báo account trong settings.json")
    c = connect(train_bot, config, settings, accounts[name])
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    from .features import Runner
    try:
        Runner(c, config, settings, stop).run([x.strip() for x in a.features.split(",") if x.strip()])
    finally:
        try:
            c.running = False
            c.sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
