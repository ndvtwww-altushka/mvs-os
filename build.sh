#!/bin/sh
# MVS OS — сборка Live ISO через live-build. Версия берётся из файла VERSION.
#
# Локально:
#   sudo sh ./build.sh
# Нужен Debian 12 (или контейнер Debian 12), live-build, squashfs-tools,
# xorriso, интернет и ~12 ГБ свободного места.
#
# В GitHub Actions этот же скрипт запускает .github/workflows/build.yml.
# Результат: MVS-OS-<версия>-amd64.iso, .iso.sha256 и SHA256SUMS.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD="$ROOT/build"

say() { printf '%s\n' "$*"; }
die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

VERSION=$(tr -d ' \n' < "$ROOT/VERSION" 2>/dev/null || true)
CODENAME=$(tr -d '\r\n' < "$ROOT/CODENAME" 2>/dev/null || true)
[ -n "$VERSION" ] || die "пустой или отсутствует файл VERSION"
[ -n "$CODENAME" ] || CODENAME="Aurora Nova"
NAME="MVS-OS-${VERSION}-amd64"

say "▸ проверка окружения"

[ "$(id -u)" -eq 0 ] || die "нужен root: sudo sh ./build.sh"
command -v lb >/dev/null 2>&1 || die "нет live-build: apt-get install live-build"
command -v mksquashfs >/dev/null 2>&1 || die "нет squashfs-tools"
command -v xorriso >/dev/null 2>&1 || die "нет xorriso"

[ -d "$ROOT/config" ] || die "нет папки config рядом со скриптом"

# Списки пакетов: каждый должен существовать и не быть пустым.
for list in "$ROOT"/config/package-lists/*.list.chroot; do
    [ -f "$list" ] || die "нет ни одного списка пакетов в config/package-lists"
    if ! grep -qE '^[a-z0-9]' "$list"; then
        die "пустой список пакетов: $list"
    fi
done

# Опечатка в имени пакета иначе всплывёт через 20–60 минут, в конце сборки.
# Сверяем имена с настоящим архивом Debian до запуска live-build.
say "▸ проверка имён пакетов по архиву Debian"
sh "$ROOT/tools/check-packages.sh" \
    || die "имена пакетов не совпали с архивом Debian (см. вывод выше)"

say "▸ MVS OS ${VERSION} «${CODENAME}»"
say "  проект: $ROOT"
say "  сборка: $BUILD"

# live-build запускает хуки и программы только с правом на выполнение.
# На FAT/exFAT и FUSE chmod может не сработать, поэтому окончательные
# права выставляются ниже, уже после копирования в build/config.
chmod 755 "$ROOT"/config/hooks/live/*.hook.chroot 2>/dev/null || true
chmod 755 "$ROOT"/config/includes.chroot/usr/local/bin/* 2>/dev/null || true
chmod 755 "$ROOT"/config/includes.chroot/usr/local/share/mvs-os/games/*.sh 2>/dev/null || true
chmod 755 "$ROOT"/tools/*.sh 2>/dev/null || true
chmod 644 "$ROOT"/config/includes.chroot/usr/share/applications/*.desktop 2>/dev/null || true

# Иконки должны быть на месте: их генерирует tools/gen-icons.sh, но если
# кто-то забыл — соберём перед сборкой (скрипт идемпотентный).
if [ ! -f "$ROOT/config/includes.chroot/usr/share/icons/MVS/apps/scalable/mvs-hub.svg" ]; then
    say "▸ иконки MVS отсутствуют — генерирую"
    sh "$ROOT/tools/gen-icons.sh"
fi

rm -rf "$BUILD"
mkdir -p "$BUILD"
cd "$BUILD"

say "▸ настройка live-build (Debian 12 bookworm)"
lb config \
    --architecture amd64 \
    --distribution bookworm \
    --archive-areas "main contrib non-free non-free-firmware" \
    --binary-images iso-hybrid \
    --bootloaders "syslinux,grub-efi" \
    --bootappend-live "boot=live components quiet splash loglevel=3 locales=ru_RU.UTF-8 keyboard-layouts=us,ru keyboard-variants=,winkeys timezone=Europe/Moscow username=mvs hostname=mvs-os security=apparmor apparmor=1 console=ttyS0,115200n8 console=tty0" \
    --debian-installer false \
    --iso-application "MVS OS" \
    --iso-preparer "MVS OS" \
    --iso-publisher "MVS OS" \
    --iso-volume "MVS_OS" \
    --chroot-squashfs-compression-type xz \
    --chroot-filesystem squashfs \
    --memtest none \
    --apt-recommends false \
    --linux-flavours amd64 \
    --checksums sha256

# Наши настройки поверх сгенерированных live-build'ом.
cp -a "$ROOT/config/." config/

# Версия и кодовое имя — из одного файла VERSION/CODENAME.
# Эти файлы читают приложения MVS и mvs-identity, поэтому в образе
# не может оказаться «1.0» из старого статического os-release.
mkdir -p config/includes.chroot/etc
printf '%s\n' "$VERSION" > config/includes.chroot/etc/mvs-version
printf '%s\n' "$CODENAME" > config/includes.chroot/etc/mvs-codename
cat > config/includes.chroot/etc/os-release <<EOF
PRETTY_NAME="MVS OS $VERSION (Live)"
NAME="MVS OS"
VERSION_ID="$VERSION"
VERSION="$VERSION «$CODENAME» (Live)"
VERSION_CODENAME=bookworm
ID=mvs
ID_LIKE=debian
HOME_URL="https://github.com/ndvtwww-altushka/mvs-os"
MVS_VERSION="$VERSION"
MVS_EDITION="$CODENAME"
MVS_MODE="live"
EOF
cat > config/includes.chroot/etc/lsb-release <<EOF
DISTRIB_ID=MVS
DISTRIB_RELEASE=$VERSION
DISTRIB_CODENAME=mvs
DISTRIB_DESCRIPTION="MVS OS $VERSION «$CODENAME»"
EOF

# Шаблоны интерфейса: версия в них не вписана руками, а подставляется
# из VERSION/CODENAME. Так номер меняется в одном файле.
for tpl in \
    config/includes.chroot/etc/issue \
    config/includes.chroot/etc/issue.net \
    config/includes.chroot/usr/share/calamares/branding/mvs/branding.desc; do
    [ -f "$tpl" ] || continue
    sed -i "s/@VERSION@/$VERSION/g; s/@CODENAME@/$CODENAME/g" "$tpl"
done

# Права после копирования. Исходники могут лежать на FUSE (телефон),
# FAT/exFAT (флешка) или в ZIP с Windows — там chmod не сохраняется,
# и все файлы приезжают как 0660. Для системы это означает, что
# /etc/os-release, темы и иконки не прочитает обычный пользователь,
# а скрипты не запустятся. Приводим дерево в порядок уже в build/,
# на нормальной файловой системе.
find config -type d -exec chmod 755 {} + 2>/dev/null || true
find config -type f -exec chmod 644 {} + 2>/dev/null || true
chmod 755 config/hooks/live/*.hook.chroot 2>/dev/null || true
chmod 755 config/includes.chroot/usr/local/bin/* 2>/dev/null || true
chmod 755 config/includes.chroot/usr/local/sbin/* 2>/dev/null || true
chmod 755 config/includes.chroot/etc/grub.d/40_mvs_snapshots 2>/dev/null || true
chmod 755 config/includes.chroot/usr/local/share/mvs-os/games/*.sh 2>/dev/null || true
chmod 755 config/includes.chroot/etc/skel/Desktop/*.desktop 2>/dev/null || true
# sudo требует, чтобы файлы sudoers не были доступны на запись группе/другим.
# 90-mvs-live создаётся хуком 0200 уже внутри chroot, в исходниках его нет.
chmod 440 config/includes.chroot/etc/sudoers.d/10-mvs-hardening 2>/dev/null || true

say "▸ сборка ISO (20–60 минут, много вывода)"
say "  если сборка упала — смотрите последние 40 строк вывода и build/chroot"
lb build

ISO=$(find "$BUILD" -maxdepth 1 -name '*.iso' -type f | head -n 1)
[ -n "$ISO" ] || die "ISO не найден после сборки"

# Live-вход держится на одном пакете: live-config/0030-user-setup молча
# выходит, если user-setup не установлен, и пользователь mvs не создаётся.
# Проверяем это до упаковки, а не после публикации.
if ! chroot "$BUILD/chroot" dpkg-query -W user-setup >/dev/null 2>&1; then
    die "в образе нет user-setup: Live-вход не будет работать"
fi
if [ ! -x "$BUILD/chroot/usr/lib/user-setup/user-setup-apply" ]; then
    die "в образе нет /usr/lib/user-setup/user-setup-apply: Live-вход не будет работать"
fi
say "  Live-вход: user-setup на месте"

cp -f "$ISO" "$ROOT/${NAME}.iso"
cd "$ROOT"
sha256sum "${NAME}.iso" > "${NAME}.iso.sha256"
sha256sum "${NAME}.iso" > SHA256SUMS

# Полный список пакетов образа: по нему видно, что именно вошло в ISO,
# без распаковки squashfs. Если chroot недоступен — честно пропускаем.
PACKAGES="PACKAGES-${VERSION}.txt"
PACKAGES_COUNT="?"
say "▸ список установленных пакетов"
if chroot "$BUILD/chroot" dpkg-query -W -f='${Package}\t${Version}\n' \
        > "$ROOT/$PACKAGES.raw" 2>/dev/null; then
    LC_ALL=C sort "$ROOT/$PACKAGES.raw" > "$ROOT/$PACKAGES"
    rm -f "$ROOT/$PACKAGES.raw"
    PACKAGES_COUNT=$(wc -l < "$ROOT/$PACKAGES" | tr -d ' ')
    say "  $PACKAGES: $PACKAGES_COUNT пакетов"
else
    rm -f "$ROOT/$PACKAGES.raw"
    printf '# Список пакетов не получен: chroot или dpkg-query недоступны\n' \
        > "$ROOT/$PACKAGES"
    PACKAGES_COUNT="?"
    say "  предупреждение: не удалось получить список пакетов"
fi

SIZE_BYTES=$(wc -c < "${NAME}.iso" | tr -d ' ')
SIZE_HUMAN=$(du -h "${NAME}.iso" | cut -f1)

{
    printf 'MVS OS %s «%s»\n' "$VERSION" "$CODENAME"
    printf 'Собрано: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'Коммит: %s\n' "${GITHUB_SHA:-локальная сборка}"
    printf 'Файл: %s\n' "${NAME}.iso"
    printf 'Размер: %s (%s байт)\n' "$SIZE_HUMAN" "$SIZE_BYTES"
    printf 'SHA256: %s\n' "$(cut -d' ' -f1 "${NAME}.iso.sha256")"
    printf 'Ядро: %s\n' "$(ls "$BUILD/chroot/boot"/vmlinuz-* 2>/dev/null | head -n 1 | sed 's|.*/vmlinuz-||')"
    printf 'Пакетов: %s\n' "$PACKAGES_COUNT"
    [ -z "$PACKAGES" ] || printf 'Список пакетов: %s\n' "$PACKAGES"
} > "BUILD-INFO-${VERSION}.txt" 2>/dev/null || true

say ""
say "Готово:"
say "  $ROOT/${NAME}.iso  ($SIZE_HUMAN)"
say "  $ROOT/${NAME}.iso.sha256"
say "  $ROOT/SHA256SUMS"
[ -z "$PACKAGES" ] || say "  $ROOT/$PACKAGES"
say ""
say "Проверка:   sha256sum -c SHA256SUMS"
say "Запись:     см. docs/building.md"

# GitHub Release принимает файл до 2 ГБ. Честно предупреждаем заранее.
if [ "$SIZE_BYTES" -gt 2000000000 ]; then
    say ""
    say "ВНИМАНИЕ: ISO больше 2 ГБ — GitHub Release не примет такой файл."
    say "Варианты: убрать firefox-esr из 03-apps.list.chroot или выложить ISO"
    say "на внешний хостинг, оставив в Release только SHA256SUMS."
fi
