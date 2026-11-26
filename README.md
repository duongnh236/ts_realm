# TS Realm

Bot TS Online chạy bằng **dữ liệu server**, giống ts_bot: đăng nhập tài khoản, nối TCP vào server
game, nhận gói tin trận đấu rồi tự ra lệnh. Không bật game, không chụp màn hình.

TS Realm **dùng lại** gói `train_bot` của ts_bot (đăng nhập, giao thức, bản đồ, các luồng sự kiện)
ở chế độ chỉ đọc. Không file nào của ts_bot bị sửa. Phần thêm vào là luật đánh lấy từ APK
TS Manager Mobile, gắn vào `train_bot.combat` lúc chạy.

## Có gì

| Hoạt động | Lệnh `--features` | Làm gì |
|---|---|---|
| Boss Thế Giới | `world_boss` | 10:00–23:00. Đánh 5 lượt free, rồi dùng vé trong túi (vé tặng 46629 trước, vé shop 46614 sau). Dừng khi dame cộng dồn hôm nay ≥ `damage_goal` (mặc định 5.000.000) hoặc hết vé. Không tự mua vé |
| 40 NPC | `npc40` | T2/T4/T6 20:00–23:00. Sau mỗi trận hồi đầy party rồi đánh tiếp. Dừng khi hết giờ, thua 3 trận liên tiếp (`max_losses.npc40`), hoặc trận kẹt/không mở được NPC 3 lần liền. Đánh theo AI của TS Manager (`npc40_ai`) |
| Nhị Kiều (2k) | `nhi_kieu` | Chủ nhật 08:00–23:00. Leo tháp, thua thì hồi rồi leo tiếp |
| Phó bản đơn | `pb_don` | Đi tới khi hết lượt |
| Phó bản đội | `pb_doi` | Chủ phòng tạo phòng cấp `team_dungeon_level` (20/50/80/110) |

Luật đánh thêm (chỉ bật trong sự kiện/boss/phó bản, lúc farm thường không đổi):

1. **Hồi Sinh** vẫn đứng đầu như ts_bot.
2. **Giải khống chế đồng đội**: Hỗn Loạn > Đóng Băng > Trói > Ngủ > Độc. Thứ tự người được giải
   theo TS Manager: NV hệ Thủy/Địa > NV hệ Phong/Hỏa > NV khác > Tướng. Dùng skill giải chuyên dụng
   (rẻ) trước, có 2 người dính thì dùng skill giải vùng.
   Skill: Giải Hỗn Loạn, Giải Mê, Tan Băng, Giải Độc, Giải Trừ, Trạng Giải, C.Giải Trừ, Giải Thuật…
3. **Giải buff trên người boss**: mặc định chỉ 4 buff đáng giải theo TS Manager (Nhân Giả Vô Địch,
   Kết Giới, Linh Kính, Băng Tường). `dispel_mode: "all"` để giải cả 46 loại.
   Địch đang có Kết Giới thì không đánh vào, đánh con khác trong lúc chờ giải (`avoid_barrier`).
4. **Kiểu đánh boss** (`boss_style`):
   - `auto`: chỉ đặt khiên khi máu ô mình còn ≤ `auto_guard_hp` (mặc định 50%).
   - `full_attack`: không khiên, dồn dame.
   - `survive`: luôn khiên trước.

**Đăng nhập** (theo TS Manager): server báo sai tên/mật khẩu thì bot ghi nhớ và không thử lại
với đúng mật khẩu đó nữa (tránh khóa acc), sửa mật khẩu là chạy lại được. Acc đăng nhập được thì
lưu hồ sơ (tên, server, user_id, tên nhân vật) vào `runtime/login_profiles.json`, không lưu mật khẩu.

**Đẩu Chuyển** (13021, buff hệ Phong trên người địch): thấy là giải trước mọi việc, kể cả hồi
sinh, ở mọi chế độ có bật hỗ trợ (`dau_chuyen_first`).

**AI đánh 40 NPC** (`npc40_ai: "ts_manager"`), theo thứ tự vai trò của TS Manager: hồi sinh →
hồi máu toàn party khi máu party < `party_hp_emergency` (50%) → giải khống chế đồng đội → khiên
trước nếu máu mình ≤ `guard_hp` hoặc địch đông hơn ≥ `guard_outnumbered_by` → khống chế địch →
giải buff địch / phá khiên → khiên → hồi SP party → đánh (tránh con có Kết Giới, ưu tiên con ít máu).
Đặt `npc40_ai: "ts_bot"` để quay về thứ tự cũ của ts_bot.

Nhiều acc cùng đội không giải trùng một người trong cùng lượt (dùng cơ chế giữ chỗ của ts_bot).

## Cài và chạy (Mac)

```bash
cd ~/Documents/ts_realm
source .venv/bin/activate          # Python 3.9 có sẵn, không cần cài thêm gói
```

Sửa `settings.json`:

- `ts_bot_python`, `ts_bot_data`: đường dẫn tới ts_bot (mặc định `~/Documents/ts_bot/...`).
- `server`: tên server trong `servers.json` của ts_bot, ví dụ `trieu_van`.
- `accounts`: tên đăng nhập. Để trống `password` thì bot hỏi khi chạy (không lưu mật khẩu vào file).
- `world_boss`: `use_tickets`, `damage_goal`, `ticket_ids`.
- `rules`, `team_dungeon_level`, `max_losses`, `windows` (giờ server UTC+7).

Chạy:

```bash
python -m realm.main --account acc1 --features world_boss,nhi_kieu,npc40,pb_don,pb_doi
```

Bấm `Ctrl+C` để dừng. Bot chạy lần lượt các hoạt động, cái nào ngoài giờ thì bỏ qua.

## App Android (nhiều tab, mỗi tab một acc)

Thư mục `android/`. App Java + Chaquopy (Python 3.8) giống ts_bot, nhúng `train_bot` + dữ liệu game
của ts_bot (Gradle chỉ chép, không sửa ts_bot) và gói `realm`.

Màn hình:
- Thanh tab trên cùng: `+` thêm tab, bấm giữ một tab để đóng (acc trong tab đăng xuất).
  Chấm màu: xám chưa vào, vàng đang đăng nhập, xanh dương đã vào game, xanh lá đang chạy, đỏ lỗi.
- Mỗi tab: chọn server, tên đăng nhập, mật khẩu, "Nhớ tài khoản" (mật khẩu chỉ nhớ khi tick
  "Nhớ cả mật khẩu", lưu trong máy), nút Đăng nhập/Đăng xuất.
- Hoạt động: Boss TG (dùng vé sau 5 lượt free, mốc dame dừng), Nhị Kiều (2k), 40 NPC (số trận thua
  liên tiếp thì dừng), phó bản đơn, phó bản đội (cấp phòng). Nút ▶ Chạy và ■ Dừng.
- Nhật ký riêng từng tab, cập nhật mỗi giây.
- Có acc vào game là app chạy nền (thông báo "N tài khoản đang vào game"), tắt màn hình vẫn chạy.
  Nút Back chỉ đưa app xuống nền, không thoát.
- Chế độ cửa sổ như ts_bot: app mở dạng cửa sổ nổi (94% x 78% màn hình) đè lên game, chạm ra ngoài
  thì vẫn bấm được game phía sau. Kéo thanh tiêu đề để di chuyển (nhớ vị trí), `−` thu xuống nền,
  `□` phóng to hết màn hình / thu lại. Chạy được chia đôi màn hình hoặc cửa sổ tự do (DeX, tablet).

Build trên Mac:
1. Để `ts_bot` và `ts_realm` cạnh nhau trong `~/Documents` (đường dẫn khác thì sửa `tsBotDir`
   trong `android/gradle.properties`).
2. Android Studio → Open → chọn `ts_realm/android` → chờ Gradle sync → Run, hoặc
   `cd android && ./gradlew assembleDebug` → file `app/build/outputs/apk/debug/TSRealm-debug.apk`.

## Kiểm tra

```bash
python -m unittest discover -s tests -v
```

41 test, không cần server: luật giải khống chế/giải buff, kiểu đánh boss, giờ sự kiện, luồng
40 NPC / Nhị Kiều với client giả, và gắn luật vào `train_bot.combat` thật của ts_bot.

## Thư mục

```
realm/
  bootstrap.py     nạp train_bot của ts_bot trên máy tính (thay phần Chaquopy)
  status_logic.py  bảng CC / buff boss / skill giải lấy từ APK
  combat_rules.py  luật giải khống chế, giải buff, kiểu đánh boss
  features.py      Boss TG, 40 NPC, Nhị Kiều, phó bản đơn, phó bản đội
  npc40_loop.py    vòng 40 NPC (giờ 23:00, thua 3 trận liên tiếp mới dừng)
  world_boss.py    Boss TG: lượt free + vé, đếm dame theo ngày (runtime/world_boss_damage.json)
  login_guard.py   hồ sơ đăng nhập + chặn thử lại khi sai mật khẩu
  main.py          dòng lệnh
  android_api.py   cầu nối cho app Android (mỗi tab một phiên)
android/           app Android (Java + Chaquopy)
settings.json
tests/test_realm.py
data/nhi_kieu_ts_manager.json   tầng + cửa ẩn Nhị Kiều trích từ TS Manager (để đối chiếu)
SO_SANH.md                      so sánh TS Manager bản PC với ts_bot
```

Chưa chạy thử với server thật. Lần đầu nên chạy từng hoạt động một và xem log.

## Cập nhật app qua GitHub Release

App có nút **⟳** ở thanh trên cùng: đọc release mới nhất của `duongnh236/ts_realm`, nếu tag mới
hơn phiên bản đang cài thì tải file `.apk` đính kèm và mở trình cài đặt của Android.

Phát hành bản mới (trên máy Mac này, vì APK ký bằng `~/.android/debug.keystore` và build chép
`train_bot` từ `~/Documents/ts_bot`):

```bash
scripts/release.sh 1.2.0            # tăng versionName/versionCode + build -> dist/TSRealm-v1.2.0.apk
```

Rồi tạo release trên GitHub với tag `v1.2.0` và đính kèm file APK đó (hoặc thêm
`"ghi chú" --publish` để script tự commit, tag, push và tạo release nếu đã cài `gh`).
Tag phải trùng `versionName` trong `android/version.properties`, nếu không app sẽ báo cập nhật mãi.
