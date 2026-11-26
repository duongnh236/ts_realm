# So sánh TS Manager (bản PC v1.0.183) với ts_bot

TS Manager bản PC là Python dịch bằng Nuitka, nên không có code `.py` để đọc. Phần lấy được là
bảng hằng số của 226 module: tên hàm, tham số, chuỗi log và các bảng luật `*_policy_generated`.
Bảng nào có tên trường rõ ràng (dict, set skill) thì tin được. Con số đứng riêng lẻ thì có thể
ghép nhầm tên, nên chỉ dùng khi ts_bot cũng ra cùng kết quả.

## Boss Thế Giới

| | TS Manager | ts_bot | ts_realm |
|---|---|---|---|
| Giờ mở | 12h–23h (`world_boss_window_open`) | có | 12:00–23:00 |
| Số lượt | mặc định 5, chỉnh được | đánh tới 5/5 | dùng của ts_bot |
| Chọn tướng mang theo | `world_boss_hero_id` | — | chưa làm |
| Lượt cuối thì bỏ hồi SP | `boss_should_sacrifice_turn_for_sp` | — | chưa làm |
| Giải buff boss | chỉ 4 buff đáng giải: Nhân Giả Vô Địch 21026, Kết Giới 10010, Linh Kính 10026, Băng Tường 11002 | có phá bảo vệ | **mới:** `dispel_mode: worthy` |
| Kết Giới thì không đánh vào | `DAMAGE_AVOID_ENEMY_BUFF_SKILL_IDS = {10010}` | — | **mới:** đánh con khác, chờ giải |

## Giải khống chế (dùng chung mọi chế độ)

| | TS Manager | ts_realm |
|---|---|---|
| Ai được giải trước | NV hệ Thủy/Địa > NV hệ Phong/Hỏa > NV khác > Tướng (`CLEANSE_ALLY_LADDER`) | **mới**, theo đúng thứ tự này |
| Skill | Đóng băng thì dùng Tan Băng 11015; giải chung 11012 / 11025 / 11031; Giải Kết Giới 10009 | có |
| Ưu tiên hành động với địch | khống chế trước, giải buff sau (`ENEMY_ACTION_PRIORITY`) | ts_bot đã làm |
| Chia việc trong party | hồi sinh → hồi máu party (máu < 50%) → giải → khống chế → hồi SP → dame | ts_bot có cơ chế giữ chỗ, ts_realm dùng lại |

## 40 NPC

| | TS Manager | ts_bot | ts_realm |
|---|---|---|---|
| Giờ | T2/T4/T6, 20:00–22:00 | 20:00–22:00 | **sửa:** trước ghi nhầm 12:00, nay 20:00 |
| Số tầng | 40 | có | — |
| Thua | ở lại sân, đi Hoa Đà hồi rồi đánh tiếp | `on_loss`, thua 2 trận liền thì dừng | hồi rồi đánh tiếp, tối đa `max_losses` |
| Đi theo nhóm 5 acc, chọn phân khu vắng, tự rao tuyển | `npc40_group` | có party | chưa làm (chạy 1 acc) |
| Đổi tướng theo tầng | `npc40_hero_for_floor` | — | chưa làm |

## Nhị Kiều (2k)

| | TS Manager | ts_bot |
|---|---|---|
| Tháp | 12922 → 12934, 12 cổng lên tầng, 33 cửa ẩn | 12922 → 12959, nhiều khu hơn |
| Cổng tầng 12930 | door 3 | door 3 (khớp) |
| Chỉ đội trưởng bắn cửa ẩn | có | có `du_party` |
| Dừng khi | thua, rời tầng, server không đáp, đứng yên quá lâu | thua, kẹt cổng, mất kết nối |

Bảng tầng và cửa ẩn của TS Manager nằm ở `data/nhi_kieu_ts_manager.json` để đối chiếu. ts_bot đi
được nhiều tầng hơn nên ts_realm vẫn dùng luồng leo tháp của ts_bot.

## Phó bản đơn

| | TS Manager | ts_bot |
|---|---|---|
| Lượt 2 | mua bằng KNB (`PB_DON_SECOND_RUN_KNB_COST`), chưa biết số dư thì chờ, thiếu thì thôi | thử vé free, lỗi thì mua vé |
| Đang ở Dị Giới | hoãn PB đơn tới khi rời Dị Giới | — |
| Kẹt | tự gỡ cờ "đang chạy" | — |

## Phó bản đội

| | TS Manager | ts_bot |
|---|---|---|
| Cấp phòng | `TEAM_DUNGEONS`, chọn tự động | 20 / 50 / 80 / 110 |
| Mua thêm lượt | có | — |
| Cờ "hết lượt" của hôm qua | đối chiếu với nhiệm vụ "Hoàn thành phó bản đội" | — |
| Kick thành viên treo | chủ phòng, khi chưa bắt đầu | — |

## Đã đưa vào ts_realm lần này

1. Thứ tự giải khống chế theo hệ nhân vật (`CLEANSE_ALLY_LADDER`).
2. Chỉ giải 4 buff đáng giải (`dispel_mode: "worthy"`; đổi thành `"all"` để giải cả 46 loại).
3. Địch có Kết Giới thì đánh con khác trong lúc chờ giải (`avoid_barrier`).
4. Sửa giờ 40 NPC thành 20:00–22:00.

Những phần ghi "chưa làm" cần thêm lệnh gửi lên server (đổi tướng, mua lượt, kick, đổi phân khu).
Mình chưa làm vì phải đoán định dạng gói tin.
