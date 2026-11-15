#!/bin/sh
# MVS OS — запись ISO на USB-флешку с проверками.
#
#   sudo sh tools/write-usb.sh /dev/sdb
#   sudo sh tools/write-usb.sh --force /dev/nvme0n1   # USB-SSD, если очень надо
#
# Скрипт отказывается писать на системный диск, на смонтированную флешку
# и на устройство меньше ISO. Перед записью нужно ввести YES.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(tr -d ' \n' < "$ROOT/VERSION" 2>/dev/null || printf '1.0')

FORCE=0
case "${1:-}" in
    --force) FORCE=1; shift ;;
esac

ISO=${MVS_ISO:-"$ROOT/MVS-OS-${VERSION}-amd64.iso"}

die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
MVS OS — запись ISO на флешку

  sudo sh tools/write-usb.sh /dev/sdb
  sudo sh tools/write-usb.sh --force /dev/nvme0n1

ISO по умолчанию: $ISO
Все данные на выбранном устройстве будут стёрты.
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac

[ "$(id -u)" -eq 0 ] || die "нужен root: sudo sh tools/write-usb.sh /dev/sdX"
command -v lsblk >/dev/null 2>&1 || die "нет lsblk (пакет util-linux)"
command -v sha256sum >/dev/null 2>&1 || die "нет sha256sum (пакет coreutils)"

[ -f "$ISO" ] || die "нет ISO: $ISO
Соберите его (sudo sh ./build.sh) или скачайте артефакт mvs-os-iso из GitHub Actions."

# --- проверка ISO ---------------------------------------------------------

printf '▸ ISO: %s (%s)\n' "$ISO" "$(du -h "$ISO" | cut -f1)"

if [ -f "$ISO.sha256" ]; then
    ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$ISO").sha256" ) \
        || die "ISO повреждён: SHA256 не совпал"
elif [ -f "$(dirname "$ISO")/SHA256SUMS" ]; then
    ( cd "$(dirname "$ISO")" && sha256sum -c SHA256SUMS ) \
        || die "ISO повреждён: SHA256 не совпал"
else
    printf '  SHA256: %s\n' "$(sha256sum "$ISO" | cut -d' ' -f1)"
fi

# --- выбор устройства -----------------------------------------------------

if [ -z "${1:-}" ]; then
    printf '\nСъёмные диски:\n'
    lsblk -dpno NAME,SIZE,TYPE,RM 2>/dev/null \
        | awk '$3 == "disk" && $4 == "1" { printf "  %-14s %s\n", $1, $2 }'
    printf '\nВведите устройство (например /dev/sdb): '
    read -r DEV || die "устройство не выбрано"
else
    DEV=$1
fi

[ -n "${DEV:-}" ] || die "устройство не выбрано"
[ -b "$DEV" ] || die "это не блочное устройство: $DEV"

# Симлинк /dev/disk/by-id/... приводим к /dev/sdX.
DEV=$(readlink -f "$DEV" 2>/dev/null || printf '%s' "$DEV")
case "$DEV" in
    /dev/*) ;;
    *) die "неожиданный путь устройства: $DEV" ;;
esac

BASE=${DEV#/dev/}
case "$BASE" in
    */*) die "это не целый диск: $DEV" ;;
    loop*|ram*|zram*|sr*|nbd*|md*|dm-*)
        die "$DEV не флешка, а служебное устройство" ;;
esac

[ -e "/sys/block/$BASE/removable" ] || die "нет /sys/block/$BASE — это не диск"

REMOVABLE=$(cat "/sys/block/$BASE/removable" 2>/dev/null || printf '0')
if [ "$REMOVABLE" != "1" ] && [ "$FORCE" -eq 0 ]; then
    die "/dev/$BASE не помечен как съёмный (removable=0).
Если это USB-SSD и вы уверены — добавьте --force."
fi

# --- защита системного диска ---------------------------------------------

ROOT_SRC=$(findmnt -n -o SOURCE / 2>/dev/null || true)
if [ -n "$ROOT_SRC" ]; then
    ROOT_DISK=$(lsblk -n -o PKNAME "$ROOT_SRC" 2>/dev/null | head -n 1 || true)
    if [ -n "$ROOT_DISK" ] && [ "$ROOT_DISK" = "$BASE" ]; then
        die "$DEV — диск, на котором работает текущая система"
    fi
fi

# --- размер и занятость ---------------------------------------------------

ISO_SIZE=$(wc -c < "$ISO" | tr -d ' ')
if command -v blockdev >/dev/null 2>&1; then
    DEV_SIZE=$(blockdev --getsize64 "$DEV" 2>/dev/null) \
        || die "не удалось узнать размер $DEV"
else
    DEV_SIZE=$(lsblk -bndo SIZE "$DEV" | tr -d ' ')
fi

[ "$DEV_SIZE" -ge "$ISO_SIZE" ] || die "флешка меньше ISO: $DEV"

MOUNTS=$(lsblk -nlo MOUNTPOINT "$DEV" 2>/dev/null | sed '/^[[:space:]]*$/d' || true)
if [ -n "$MOUNTS" ]; then
    printf 'Устройство смонтировано:\n%s\n' "$MOUNTS"
    printf 'Отмонтируйте и запустите снова:\n'
    printf '%s\n' "$MOUNTS" | while IFS= read -r mp; do
        printf '  umount %s\n' "$mp"
    done
    exit 1
fi

MODEL=$(lsblk -dno MODEL "$DEV" 2>/dev/null | sed 's/[[:space:]]*$//' || true)
printf '\n▸ устройство: %s (%s)\n' "$DEV" "$(lsblk -dno SIZE "$DEV" | tr -d ' ')"
[ -n "$MODEL" ] && printf '  модель: %s\n' "$MODEL"
printf '  ISO: %s\n' "$(du -h "$ISO" | cut -f1)"

printf '\nВСЁ НА %s БУДЕТ СТЁРТО.\n' "$DEV"
printf 'Чтобы продолжить, введите YES: '
read -r ANSWER || die "отменено"
[ "$ANSWER" = "YES" ] || die "отменено"

# --- запись ---------------------------------------------------------------

printf '\n▸ запись (это может занять несколько минут)\n'
dd if="$ISO" of="$DEV" bs=4M status=progress oflag=sync conv=fsync
sync

printf '\nГотово. Можно загружаться с %s.\n' "$DEV"
if command -v eject >/dev/null 2>&1; then
    eject "$DEV" 2>/dev/null || true
fi
