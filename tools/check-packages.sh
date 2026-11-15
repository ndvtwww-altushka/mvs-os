#!/bin/sh
# MVS OS — проверка имён пакетов по настоящему архиву Debian bookworm.
#
# Зачем: ISO собирается 20–60 минут. Опечатка в имени пакета всплывает
# только в конце, когда apt внутри chroot уже всё скачал. Этот скрипт
# сверяет каждый пакет из config/package-lists со списком Packages
# для amd64 и all — за несколько секунд и без сборки.
#
# Запуск:
#   sh tools/check-packages.sh
#
# Переменные:
#   MVS_DEBIAN_MIRROR  зеркало (по умолчанию https://deb.debian.org/debian)
#   MVS_DEBIAN_DIST    выпуск (по умолчанию bookworm)
#   MVS_PACKAGES_DIR   локальная папка с Packages для офлайн-проверки:
#                      $MVS_PACKAGES_DIR/main/binary-amd64/Packages
#                      (можно Packages, Packages.gz или Packages.xz)
#
# Скрипту нужны curl или wget и xz-utils (или gzip). В GitHub Actions
# они есть; на телефоне скрипт честно скажет, чего не хватает.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MIRROR=${MVS_DEBIAN_MIRROR:-https://deb.debian.org/debian}
DIST=${MVS_DEBIAN_DIST:-bookworm}

AREAS="main contrib non-free non-free-firmware"
ARCHES="binary-amd64 binary-all"

say() { printf '%s\n' "$*"; }
die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
    -h|--help)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    "") ;;
    *) die "неизвестный аргумент: $1 (см. --help)" ;;
esac

TMP=$(mktemp -d 2>/dev/null) || die "нет mktemp"
trap 'rm -rf "$TMP"' EXIT INT TERM

# --- загрузка -------------------------------------------------------------

if [ -n "${MVS_PACKAGES_DIR:-}" ]; then
    [ -d "$MVS_PACKAGES_DIR" ] || die "нет папки MVS_PACKAGES_DIR: $MVS_PACKAGES_DIR"
else
    if command -v curl >/dev/null 2>&1; then
        DOWNLOAD=curl
    elif command -v wget >/dev/null 2>&1; then
        DOWNLOAD=wget
    else
        die "нужен curl или wget (или задайте MVS_PACKAGES_DIR)"
    fi
fi

fetch() {
    area_arch=$1
    target=$2

    if [ -n "${MVS_PACKAGES_DIR:-}" ]; then
        for candidate in \
            "$MVS_PACKAGES_DIR/$area_arch/Packages" \
            "$MVS_PACKAGES_DIR/$area_arch/Packages.gz" \
            "$MVS_PACKAGES_DIR/$area_arch/Packages.xz"; do
            if [ -f "$candidate" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
        printf 'нет %s/Packages[.gz|.xz]\n' "$area_arch" >&2
        return 1
    fi

    url="$MIRROR/dists/$DIST/$area_arch/Packages.xz"
    if [ "$DOWNLOAD" = curl ]; then
        curl -fsSL --retry 3 --connect-timeout 20 "$url" -o "$target" || return 1
    else
        wget -q --tries=3 --timeout=30 -O "$target" "$url" || return 1
    fi
    printf '%s\n' "$target"
}

read_names() {
    case "$1" in
        *.xz) xzcat "$1" ;;
        *.gz) gzip -dc "$1" ;;
        *) cat "$1" ;;
    esac | awk '$1 == "Package:" { print $2 }'
}

# --- имена из архива ------------------------------------------------------

: > "$TMP/available"
say "▸ архив Debian $DIST ($MIRROR)"

for area in $AREAS; do
    for arch in $ARCHES; do
        key="$area/$arch"
        file=$(fetch "$key" "$TMP/$area-$arch.xz") \
            || die "не удалось получить Packages для $key"
        case "$file" in
            *.xz) command -v xzcat >/dev/null 2>&1 \
                    || die "нет xzcat: установите xz-utils" ;;
            *.gz) command -v gzip >/dev/null 2>&1 \
                    || die "нет gzip" ;;
        esac
        read_names "$file" >> "$TMP/available"
        printf '  ok   %s\n' "$key"
    done
done

[ -s "$TMP/available" ] || die "список пакетов архива пуст"
LC_ALL=C sort -u "$TMP/available" -o "$TMP/available"
say "  пакетов в архиве: $(wc -l < "$TMP/available" | tr -d ' ')"

# --- имена из проекта -----------------------------------------------------

: > "$TMP/requested"
for list in "$ROOT"/config/package-lists/*.list.chroot; do
    [ -f "$list" ] || continue
    name=$(basename "$list")
    awk -v source="$name" '
        /^[a-z0-9]/ {
            sub(/#.*/, "")
            sub(/[[:space:]].*/, "")
            if ($0 != "") print $0 "|" source
        }
    ' "$list" >> "$TMP/requested"
done

[ -s "$TMP/requested" ] || die "в config/package-lists нет имён пакетов"

# Наборы MVS Store тоже ставятся через apt. Проверяем и их, кроме наборов
# с отдельным репозиторием (например, VS Code из репозитория Microsoft).
PRESETS="$ROOT/config/includes.chroot/usr/share/mvs/store/presets.json"
if [ -f "$PRESETS" ]; then
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$PRESETS" >> "$TMP/requested" <<'PY' || die "не удалось разобрать $PRESETS"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

for item in data.get("sets", []):
    if item.get("repository"):
        continue
    source = "store/" + str(item.get("id", "set"))
    for name in item.get("packages", []):
        if isinstance(name, str) and name:
            print("%s|%s" % (name, source))
PY
    else
        say "  python3 нет: наборы MVS Store не проверяются"
    fi
fi

LC_ALL=C sort -u "$TMP/requested" -o "$TMP/requested"
say "  пакетов в проекте: $(wc -l < "$TMP/requested" | tr -d ' ')"

# --- сверка ---------------------------------------------------------------

awk -F'|' '
    NR == FNR { available[$1] = 1; next }
    !($1 in available) { print "  НЕТ  " $1 "  (" $2 ")" ; bad++ }
    END {
        if (bad) {
            printf "\nНе найдено пакетов: %d\n", bad
            exit 1
        }
    }
' "$TMP/available" "$TMP/requested" || {
    say ""
    die "имена пакетов не совпали с архивом Debian $DIST"
}

say ""
say "Все пакеты есть в архиве Debian $DIST."
