"""Chạy bot: python -m tsrealm.main --features world_boss,nhi_kieu,npc40,pb_don,pb_doi"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal

from .adb import Adb
from .engine import Bot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = ["world_boss", "nhi_kieu", "npc40", "pb_don", "pb_doi"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="TS Realm bot")
    ap.add_argument("--features", default=",".join(ALL), help="danh sách, cách nhau dấu phẩy")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--serial", default=None, help="adb serial, ví dụ emulator-5554")
    ap.add_argument("--loop", action="store_true", help="chạy lặp lại mãi")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)
    dev = Adb(a.serial if a.serial is not None else cfg.get("adb_serial", ""), cfg.get("adb_path", "adb"))
    bot = Bot(ROOT, cfg, dev)
    signal.signal(signal.SIGINT, lambda *_: bot.stop_event.set())
    feats = [x.strip() for x in a.features.split(",") if x.strip()]
    while True:
        for f in feats:
            if bot.stop_event.is_set():
                return
            bot.run_feature(f)
        if not a.loop:
            break


if __name__ == "__main__":
    main()
