#!/bin/sh
# MVS OS — упаковка исходников в обычный ZIP без сторонних программ.
#
# Зачем свой скрипт: в Android-оболочке нет zip, а отдавать проект нужно
# файлом, который открывается везде. Формат ZIP (метод store, без сжатия)
# собирается из awk/cat: gzip кладёт в трейлер тот же CRC-32, что и ZIP,
# поэтому CRC берётся готовым, без своей реализации.
#
# Запуск:  sh tools/make-zip.sh [путь.zip]
# Проверка: unzip -t MVS-OS-1.0-src.zip

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(tr -d ' \n' < "$ROOT/VERSION")
NAME="MVS-OS-${VERSION}-src"
OUT=${1:-"$ROOT/../${NAME}.zip"}

case "$OUT" in
    /*) ;;
    *) OUT="$(pwd)/$OUT" ;;
esac

TMP=$(mktemp -d 2>/dev/null) || { echo "Ошибка: нет mktemp" >&2; exit 1; }
trap 'rm -rf "$TMP"' EXIT INT TERM

LIST="$TMP/list"
META="$TMP/meta"

# --- запись двоичных полей -------------------------------------------------
# Заголовки собирает awk: printf "%c" даёт сырой байт, включая NUL.
# Так на 177 файлов приходится ~180 процессов вместо тысяч подоболочек.

LOCAL_AWK='
function le16(n) { printf "%c%c", n % 256, int(n / 256) % 256 }
function le32(n) {
    printf "%c%c%c%c", n % 256, int(n / 256) % 256,
        int(n / 65536) % 256, int(n / 16777216) % 256
}
function hx(c) { return index("0123456789abcdef", tolower(c)) - 1 }
function hexbytes(h,  i) {
    for (i = 1; i <= length(h); i += 2)
        printf "%c", hx(substr(h, i, 1)) * 16 + hx(substr(h, i + 1, 1))
}
BEGIN {
    printf "%c%c%c%c", 80, 75, 3, 4
    le16(20); le16(2048); le16(0); le16(24576); le16(23917)
    hexbytes(crc)
    le32(size); le32(size)
    le16(length(name)); le16(0)
    printf "%s", name
}'

CENTRAL_AWK='
function le16(n) { printf "%c%c", n % 256, int(n / 256) % 256 }
function le32(n) {
    printf "%c%c%c%c", n % 256, int(n / 256) % 256,
        int(n / 65536) % 256, int(n / 16777216) % 256
}
function hx(c) { return index("0123456789abcdef", tolower(c)) - 1 }
function hexbytes(h,  i) {
    for (i = 1; i <= length(h); i += 2)
        printf "%c", hx(substr(h, i, 1)) * 16 + hx(substr(h, i + 1, 1))
}
{
    printf "%c%c%c%c", 80, 75, 1, 2
    le16(788); le16(20); le16(2048); le16(0); le16(24576); le16(23917)
    hexbytes($5)
    le32($2); le32($2)
    le16(length($4)); le16(0); le16(0); le16(0); le16(0)
    le32($3 * 65536)
    le32($1)
    printf "%s", $4
}'

emit_local() { awk -v crc="$1" -v size="$2" -v name="$3" "$LOCAL_AWK"; }

# CRC-32 файла в виде hex-строки (байты уже в порядке little-endian).
crc_of() {
    gzip -c "$1" | tail -c 8 | head -c 4 | od -An -tx1 | tr -d ' \n'
}

# --- список файлов ---------------------------------------------------------

cd "$ROOT"

find . -type f \
    ! -path './build/*' \
    ! -path './.git/*' \
    ! -path '*/__pycache__/*' \
    ! -name '*.iso' \
    ! -name '*.iso.sha256' \
    ! -name 'SHA256SUMS' \
    ! -name 'BUILD-INFO-*.txt' \
    ! -name 'PACKAGES-*.txt' \
    ! -name '*.pyc' \
    ! -name '.DS_Store' \
    ! -name 'Thumbs.db' \
    | sed 's|^\./||' | LC_ALL=C sort > "$LIST"

if [ ! -s "$LIST" ]; then
    echo "Ошибка: нечего упаковывать" >&2
    exit 1
fi

# Имена должны быть ASCII: иначе длина в байтах не совпадёт с ${#name}.
if LC_ALL=C grep -q '[^ -~]' "$LIST"; then
    echo "Ошибка: в именах файлов есть не-ASCII символы" >&2
    LC_ALL=C grep -n '[^ -~]' "$LIST" >&2
    exit 1
fi

: > "$META"
: > "$OUT"
count=0

# --- локальные заголовки и данные -----------------------------------------

while IFS= read -r name; do
    [ -n "$name" ] || continue
    size=$(stat -c%s "$name")
    crc=$(crc_of "$name")
    offset=$(stat -c%s "$OUT")
    # Всё лежит в одной папке mvs-os/, чтобы распаковка не рассыпала
    # файлы по текущему каталогу.
    entry="mvs-os/$name"

    # Права: скрипты и хуки должны остаться исполняемыми после распаковки,
    # хотя на FUSE-хранилище телефона права и так не сохраняются.
    mode=33188          # 0100644
    case "$name" in
        build.sh|check.sh|tools/*.sh)
            mode=33261  # 0100755
            ;;
        config/hooks/live/*.hook.chroot)
            mode=33261
            ;;
        config/includes.chroot/usr/local/bin/*)
            mode=33261
            ;;
        config/includes.chroot/usr/local/share/mvs-os/games/*.sh)
            mode=33261
            ;;
    esac

    emit_local "$crc" "$size" "$entry" >> "$OUT"
    cat "$name" >> "$OUT"

    printf '%s|%s|%s|%s|%s\n' "$offset" "$size" "$mode" "$entry" "$crc" >> "$META"
    count=$((count + 1))
done < "$LIST"

# --- центральный каталог ---------------------------------------------------

cd_offset=$(stat -c%s "$OUT")
awk -F'|' "$CENTRAL_AWK" "$META" >> "$OUT"
cd_size=$(( $(stat -c%s "$OUT") - cd_offset ))

# --- конец центрального каталога ------------------------------------------

awk -v count="$count" -v cd_size="$cd_size" -v cd_offset="$cd_offset" '
function le16(n) { printf "%c%c", n % 256, int(n / 256) % 256 }
function le32(n) {
    printf "%c%c%c%c", n % 256, int(n / 256) % 256,
        int(n / 65536) % 256, int(n / 16777216) % 256
}
BEGIN {
    printf "%c%c%c%c", 80, 75, 5, 6
    le16(0); le16(0)
    le16(count); le16(count)
    le32(cd_size); le32(cd_offset)
    le16(0)
}' >> "$OUT"

echo "ZIP: $OUT"
echo "Файлов: $count"
echo "Размер: $(du -h "$OUT" | cut -f1)"

# Проверка тем же unzip, который потом откроет пользователь.
if command -v unzip >/dev/null 2>&1; then
    if unzip -tq "$OUT" >/dev/null 2>&1; then
        echo "Проверка unzip: ok"
    else
        echo "Ошибка: unzip не смог прочитать архив" >&2
        unzip -t "$OUT" >&2 || true
        exit 1
    fi
else
    echo "Проверка unzip: пропущена (нет unzip)"
fi
