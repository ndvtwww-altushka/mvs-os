#!/bin/sh
# MVS OS — подготовка Debian 12 и локальная сборка ISO одной командой.
#
#   sudo sh tools/build-local.sh
#
# Скрипт ставит только зависимости сборки (live-build, xorriso, GRUB,
# syslinux) и передаёт управление build.sh. Сами пакеты MVS OS ставятся
# внутрь образа, на хост они не попадают.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "нужен root: sudo sh tools/build-local.sh"

[ -r /etc/os-release ] || die "не найден /etc/os-release: это не Debian?"
# shellcheck disable=SC1091
. /etc/os-release

[ "${ID:-}" = "debian" ] || die "нужен Debian 12 (bookworm), а здесь ${PRETTY_NAME:-неизвестная система}"
if [ "${VERSION_CODENAME:-}" != "bookworm" ]; then
    printf 'Предупреждение: хост %s, а образ собирается для bookworm.\n' "${PRETTY_NAME:-неизвестно}"
    printf 'Обычно это работает, но CI использует чистый Debian 12.\n\n'
fi

printf '▸ установка зависимостей сборки\n'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    live-build debootstrap squashfs-tools xorriso fakeroot \
    syslinux syslinux-common isolinux syslinux-efi \
    grub-efi-amd64-bin grub-pc-bin mtools dosfstools \
    file rsync wget xz-utils bzip2 cpio apt-utils

printf '\n▸ запуск build.sh\n'
exec sh "$ROOT/build.sh"
