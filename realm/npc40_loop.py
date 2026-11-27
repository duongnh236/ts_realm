"""Vòng lặp 40 NPC của ts_realm (dựa trên ``train_bot.npc40.run_loop``, không sửa ts_bot).

Khác ts_bot:
  * Giờ kết thúc lấy theo ``windows.npc40`` của settings (mặc định 23:00), không phải 22:00 cứng.
  * Thua thì hồi đầy máu/mana rồi đánh tiếp như TS Manager. ``max_consec_losses`` = 0 (mặc định)
    là không dừng vì thua; đặt số > 0 thì thua chừng ấy trận LIÊN TIẾP mới dừng (ts_bot là 2).
  * Sau mỗi trận đọc tầng đã qua từ Thắng Lệnh trong túi (``npc40_progress``) để log tiến độ;
    qua đủ 40 tầng thì dừng.
Giữ nguyên ts_bot:
  * Đi tới NPC / mở trận / vào trận tiếp: thử lại tối đa ``MAX_RETRY`` (3) lần.
  * Không thấy hỏi "đánh tiếp?" sau ~180s: cả đội chết hết -> thua; còn sống -> mở lại NPC (3 lần).
  * Sau mỗi trận: đóng hộp thoại, hồi đầy HP/SP rồi mới mở trận kế tiếp.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("bot")

MAX_RETRY = 3
AFTER_END = 1.0      # giây chờ sau khi hết trận (nhận thưởng) rồi mới mở NPC lại


def _battles(client):
    """Số trận đã kết thúc (ts_bot tăng ``exp_stats_battles`` lúc ghi 'THONG KE TRAN')."""
    return int(getattr(client, "exp_stats_battles", 0) or 0)


def _wait_end(client, npc40, prompt_seq, battles, stop_event, sleep_fn, poll_interval):
    """Chờ hết trận: "prompt" (hộp thoại đánh tiếp như ts_bot), "end" (trận đã kết thúc mà không có
    hộp thoại - TS Realm), None = hết thời gian / dừng."""
    for _ in range(int(getattr(npc40, "CHECK_CHO_PROMPT", 450))):
        if not (client.running and not stop_event.is_set()):
            return None
        if client._npc40_prompt_seq > prompt_seq:
            return "prompt"
        if _battles(client) > battles and not getattr(getattr(client, "state", None), "in_battle", False):
            return "end"
        sleep_fn(poll_interval)
    if client._npc40_prompt_seq > prompt_seq:
        return "prompt"
    return None


def run_loop(client, point, stop_event, on_loss, before_repeat=None, window_open=lambda: True,
             max_consec_losses=0, sleep_fn=time.sleep, poll_interval=0.4, max_advances=30,
             npc40=None, floor_fn=None):
    """Trả lý do dừng (chuỗi). ``window_open()`` False = hết giờ sự kiện."""
    if npc40 is None:
        from train_bot import npc40
    lbl = getattr(client, "_label", "?")
    if floor_fn is None:
        from . import npc40_progress
        floor_fn = lambda: npc40_progress.floors_cleared(client)
    gioi_han = max_consec_losses if max_consec_losses and max_consec_losses > 0 else "∞"

    def thua_du(n):
        return bool(max_consec_losses) and max_consec_losses > 0 and n >= max_consec_losses

    def active():
        return client.running and not stop_event.is_set()

    def ket_thuc(ly_do):
        log.warning("[%s] 40NPC: %s -> dừng", lbl, ly_do)
        try:
            on_loss()
        except Exception as exc:
            log.warning("[%s] 40NPC: lỗi báo dừng: %s", lbl, exc)
        npc40._end_npc_dialog(client, sleep_fn)
        client._npc40_done = True
        return ly_do

    for lan in range(1, MAX_RETRY + 1):
        if client.navigate_to(int(point[0]), int(point[1]), flee=False):
            break
        if not active():
            return "dừng"
        log.warning("[%s] 40NPC: không tới được NPC %s (lần %d/%d)", lbl, tuple(point), lan, MAX_RETRY)
        sleep_fn(2.0)
    else:
        return ket_thuc("không tới được NPC")
    client._wait_combat_clear(idle=1.0, cap=20.0)
    sleep_fn(3.0)
    if not active():
        return "dừng"
    client.rearm_ready()

    prompt_seq = client._npc40_prompt_seq
    battles = _battles(client)
    for lan in range(1, MAX_RETRY + 1):
        if npc40._open_event_battle(client, client._battle_start_seq, stop_event, sleep_fn,
                                    poll_interval, max_advances):
            break
        if not active():
            return "dừng"
        log.warning("[%s] 40NPC: mở trận đầu không được (lần %d/%d)", lbl, lan, MAX_RETRY)
        client._wait_combat_clear(idle=1.0, cap=20.0)
        npc40._end_npc_dialog(client, sleep_fn)
    else:
        return ket_thuc("mở trận đầu không được")

    consec = 0
    thu_lai = 0
    try:
        tang_truoc = int(floor_fn() or 0)
    except Exception:
        tang_truoc = 0
    while active():
        got = _wait_end(client, npc40, prompt_seq, battles, stop_event, sleep_fn, poll_interval)
        if got == "end":
            # TS Realm không gửi hộp thoại "đánh tiếp?" như server VN -> hết trận (S:011-000) là mở
            # lại NPC ngay, không chờ ~3 phút rồi coi là "kẹt" (log 27/11 19:34-19:43).
            client._npc40_last_defeated = bool(npc40._da_thua_that(client))
            sleep_fn(AFTER_END)
        if not got:
            if not active():
                return "dừng"
            if npc40._da_thua_that(client):
                consec += 1
                log.warning("[%s] 40NPC: không có hỏi đánh tiếp và cả đội đã chết -> thua (liên tiếp %d/%s)"
                            " -> hồi máu/mana rồi đánh tiếp", lbl, consec, gioi_han)
                if thua_du(consec):
                    return ket_thuc("thua %d trận liên tiếp" % consec)
            else:
                thu_lai += 1
                if thu_lai > MAX_RETRY:
                    return ket_thuc("%d lần liền không vào lại được trận" % MAX_RETRY)
                log.warning("[%s] 40NPC: trận bị kẹt nhưng đội còn sống -> mở lại NPC (lần %d/%d)",
                            lbl, thu_lai, MAX_RETRY)
            if not window_open():
                return ket_thuc("hết giờ sự kiện")
            client._wait_combat_clear(idle=1.0, cap=20.0)
            npc40._end_npc_dialog(client, sleep_fn)
            if before_repeat is not None:
                try:
                    before_repeat()
                except Exception as exc:
                    log.warning("[%s] 40NPC: lỗi hồi phục: %s", lbl, exc)
            battles = _battles(client)
            npc40._open_event_battle(client, client._battle_start_seq, stop_event, sleep_fn,
                                     poll_interval, max_advances)
            continue

        thu_lai = 0
        try:
            tang = int(floor_fn() or 0)
        except Exception:
            tang = 0
        # Có Thắng Lệnh tầng mới = thắng, kể cả khi chốt HP cuối báo có người nằm (log 27/11 21:18:
        # qua tầng 37 mà vẫn ghi "thua").
        len_tang = bool(tang and tang_truoc and tang > tang_truoc)
        if tang:
            tang_truoc = max(tang_truoc, tang)
        if client._npc40_last_defeated and not len_tang:
            consec += 1
            log.warning("[%s] 40NPC: thua 1 trận (liên tiếp %d/%s) -> hồi máu/mana rồi đánh tiếp",
                        lbl, consec, gioi_han)
        else:
            consec = 0
        if thua_du(consec):
            return ket_thuc("thua %d trận liên tiếp" % consec)
        if tang:
            client._npc40_floor = tang
            log.info("[%s] 40NPC: đã qua tầng %d/40 (Thắng Lệnh %d trong túi)", lbl, tang, tang)
            if tang >= 40:
                return ket_thuc("đã qua đủ 40 tầng")
        if not window_open():
            return ket_thuc("hết giờ sự kiện")

        prompt_seq = client._npc40_prompt_seq
        log.info("[%s] 40NPC: hết trận -> đóng hộp thoại, hồi đầy party rồi đánh tiếp", lbl)
        npc40._end_npc_dialog(client, sleep_fn)
        if before_repeat is not None:
            try:
                before_repeat()
            except Exception as exc:
                log.warning("[%s] 40NPC: lỗi hồi phục: %s", lbl, exc)
        ok = False
        battles = _battles(client)
        for lan in range(1, MAX_RETRY + 1):
            ok = npc40._open_event_battle(client, client._battle_start_seq, stop_event, sleep_fn,
                                          poll_interval, max_advances)
            if ok or not active():
                break
            log.warning("[%s] 40NPC: vào trận tiếp không được (lần %d/%d)", lbl, lan, MAX_RETRY)
            client._wait_combat_clear(idle=1.0, cap=20.0)
            npc40._end_npc_dialog(client, sleep_fn)
        if not ok:
            if not active():
                return "dừng"
            return ket_thuc("không vào lại được trận")
    return "dừng"


def start(client, point, on_loss, before_repeat, window_open, max_consec_losses):
    """Chạy ``run_loop`` trong thread riêng, dùng cờ dừng ``client._npc40_stop`` như ts_bot."""
    stop = getattr(client, "_npc40_stop", None)
    if stop is None:
        stop = client._npc40_stop = threading.Event()
    stop.clear()
    client._npc40_started = True
    client._npc40_prompt_pending = False
    client._npc40_prompt_pending_at = 0.0
    client._npc40_done = False
    result = {"why": None}

    def _chay():
        try:
            result["why"] = run_loop(client, point, stop, on_loss, before_repeat, window_open,
                                     max_consec_losses)
        except Exception as exc:
            log.exception("[%s] 40NPC: vòng lặp lỗi: %s", getattr(client, "_label", "?"), exc)
            result["why"] = "lỗi: %s" % exc
        finally:
            client._npc40_started = False

    t = threading.Thread(target=_chay, daemon=True, name="realm-npc40")
    client._npc40_thread = t
    t.start()
    return t, result
