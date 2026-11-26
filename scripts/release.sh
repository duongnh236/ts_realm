#!/bin/bash
# Build bản APK mới để phát hành qua GitHub Release (nút ⟳ trong app sẽ tự thấy và cài).
#
#   scripts/release.sh 1.2.0                 # tăng phiên bản + build, in hướng dẫn tạo release
#   scripts/release.sh 1.2.0 "Ghi chú" --publish
#                                            # thêm: commit + tag v1.2.0 + push + tạo release + đính APK
#
# Quy ước: tag release = "v" + versionName (vd v1.2.0), đính kèm đúng 1 file .apk.
# Phải build trên máy này: APK ký bằng ~/.android/debug.keystore, khác khoá thì điện thoại không cho
# cài đè. Gradle còn chép train_bot từ ~/Documents/ts_bot.
set -euo pipefail
cd "$(dirname "$0")/.."

VER="${1:?Nhập số phiên bản, vd: scripts/release.sh 1.2.0}"
NOTES="${2:-}"
PUBLISH="${3:-}"
VER="${VER#v}"
PROPS=android/version.properties
CUR=$(grep '^versionName=' "$PROPS" | cut -d= -f2)
CODE=$(( $(grep '^versionCode=' "$PROPS" | cut -d= -f2) + 1 ))

python3 - "$VER" "$CUR" <<'PY'
import sys
a, b = ([int(x) for x in v.split(".")] for v in sys.argv[1:3])
if a <= b:
    sys.exit("Phiên bản mới %s phải lớn hơn bản hiện tại %s" % (sys.argv[1], sys.argv[2]))
PY

sed -i '' "s/^versionCode=.*/versionCode=$CODE/; s/^versionName=.*/versionName=$VER/" "$PROPS"
echo "==> versionName $CUR -> $VER (versionCode $CODE)"
(cd android && ./gradlew assembleRelease -q)
mkdir -p dist
APK="dist/TSRealm-v$VER.apk"
cp android/app/build/outputs/apk/release/TSRealm-release.apk "$APK"
echo "==> Đã build: $APK"

if [ "$PUBLISH" = "--publish" ]; then
    git add -A
    git commit -m "Release v$VER" || true
    git tag "v$VER"
    git push origin HEAD:main && git push origin "v$VER"
    if command -v gh >/dev/null; then
        gh release create "v$VER" "$APK" --title "v$VER" --notes "$NOTES"
        echo "==> Đã tạo release v$VER"
        exit 0
    fi
    # Không có gh: dùng chính tài khoản git đã lưu trong Keychain (cái vừa dùng để push).
    REPO=duongnh236/ts_realm
    TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null | sed -n 's/^password=//p')
    if [ -n "$TOKEN" ]; then
        BODY=$(python3 -c 'import json,sys;print(json.dumps({"tag_name":sys.argv[1],"name":sys.argv[1],"body":sys.argv[2]}))' "v$VER" "$NOTES")
        RID=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
              "https://api.github.com/repos/$REPO/releases" -d "$BODY" \
              | python3 -c 'import sys,json;print(json.loads(sys.stdin.read(),strict=False).get("id",""))')
        if [ -n "$RID" ]; then
            curl -s -o /dev/null -w "upload APK: %{http_code}\n" -X POST -H "Authorization: Bearer $TOKEN" \
                 -H "Content-Type: application/vnd.android.package-archive" --data-binary @"$APK" \
                 "https://uploads.github.com/repos/$REPO/releases/$RID/assets?name=$(basename "$APK")"
            unset TOKEN
            echo "==> Đã tạo release v$VER: https://github.com/$REPO/releases/tag/v$VER"
            exit 0
        fi
        unset TOKEN
        echo "Tạo release qua API không được -> làm bằng tay như dưới."
    else
        echo "Không thấy tài khoản GitHub trong Keychain -> tạo release bằng tay như dưới."
    fi
fi
cat <<MSG

Tạo release trên GitHub:
  1. Mở https://github.com/duongnh236/ts_realm/releases/new
  2. Tag: v$VER
  3. Kéo file $APK vào ô đính kèm
  4. Bấm Publish release
Trên điện thoại: mở TS Realm, bấm ⟳ ở thanh trên cùng.
MSG
