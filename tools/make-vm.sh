#!/bin/sh
# MVS OS — запуск в окне QEMU без перезагрузки хоста.
#
# Просто посмотреть ISO (Live, изменения не сохраняются):
#   sh make-vm.sh --live
# Установить систему в виртуальный диск:
#   sh make-vm.sh --install
# Запустить уже установленную систему:
#   sh make-vm.sh
#
# Скрипт можно положить на флешку рядом с ISO: он сам найдёт образ,
# QEMU и KVM. Закрыли окно — вернулись в Linux, хост не перезагружался.
#
# Переменные окружения:
#   MVS_ISO       путь к ISO (иначе ищется рядом со скриптом)
#   MVS_VM_DISK   путь к диску VM (по умолчанию ~/.local/share/mvs-os/mvs.qcow2)
#   MVS_VM_SIZE   размер нового диска (по умолчанию 24G)
#   MVS_RAM       память в МБ (по умолчанию 4096)
#   MVS_CPUS      число ядер (по умолчанию 4)
#   MVS_VGA       auto, std или virtio (по умолчанию auto)
#   MVS_NIC       параметры -nic (по умолчанию virtio-net)
#   MVS_DISPLAY   gtk или sdl (по умолчанию выбирается автоматически)
#   MVS_GL=1      включить 3D-ускорение (OpenGL) в окне GTK
#   MVS_AUDIO     auto, 1 или 0 — звук через PulseAudio/PipeWire
#   MVS_GRAB=1    захватывать клавиатуру (нужно для Alt+Tab внутри VM)
#   MVS_NO_KVM=1  не использовать KVM (медленный программный режим)
#   MVS_VERIFY=1  проверить SHA256 ISO перед запуском
#
# Установщик Calamares внутри VM интерактивный: скрипт создаёт диск,
# проверяет ISO и запускает QEMU, но не нажимает за вас «Установить».

set -eu

SELF=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# В репозитории скрипт лежит в tools/, на флешке — рядом с ISO.
if [ -f "$SELF/../VERSION" ] && [ -d "$SELF/../config" ]; then
    ROOT=$(CDPATH= cd -- "$SELF/.." && pwd)
else
    ROOT=$SELF
fi

VERSION=$(tr -d ' \n' < "$ROOT/VERSION" 2>/dev/null || printf '1.0')
SIZE=${MVS_VM_SIZE:-24G}
RAM=${MVS_RAM:-4096}
CPUS=${MVS_CPUS:-4}
VGA=${MVS_VGA:-auto}
NIC=${MVS_NIC:-user,model=virtio-net-pci}
AUDIO=${MVS_AUDIO:-auto}
DISK=${MVS_VM_DISK:-"${XDG_DATA_HOME:-${HOME:-$ROOT}/.local/share}/mvs-os/mvs.qcow2"}
MODE=auto
FULLSCREEN=0
ISO=""

usage() {
    cat <<EOF
MVS OS — виртуальная машина

  sh make-vm.sh --live       запустить ISO в окне, без установки
  sh make-vm.sh --install    создать диск и запустить установку с ISO
  sh make-vm.sh              запустить уже установленную систему

  --iso PATH       путь к ISO (иначе ищется рядом со скриптом)
  --fullscreen     открыть окно на весь экран
  -h, --help       эта справка

Окно ведёт себя как обычное окно Linux: Alt+Tab переключает на
основную систему, клик по окну возвращает в MVS OS. Для Alt+Tab
внутри VM запустите с MVS_GRAB=1 (или View → Grab Input).

Переменные: MVS_ISO, MVS_VM_DISK, MVS_VM_SIZE, MVS_RAM, MVS_CPUS,
            MVS_VGA, MVS_NIC, MVS_DISPLAY, MVS_GL, MVS_AUDIO, MVS_GRAB,
            MVS_NO_KVM, MVS_VERIFY.
Диск по умолчанию: $DISK
EOF
}

die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

find_iso() {
    if [ -n "${MVS_ISO:-}" ]; then
        printf '%s\n' "$MVS_ISO"
        return 0
    fi
    for dir in "$ROOT" "$SELF" "$PWD" "${HOME:-$ROOT}/Downloads"; do
        for candidate in "$dir"/MVS-OS-*-amd64.iso; do
            if [ -f "$candidate" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
    done
    return 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --live) MODE=live ;;
        --install) MODE=install ;;
        --installed) MODE=installed ;;
        --fullscreen) FULLSCREEN=1 ;;
        --iso)
            [ $# -ge 2 ] || die "после --iso нужен путь к файлу"
            ISO=$2
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "неизвестный аргумент: $1 (см. --help)" ;;
    esac
    shift
done

[ -n "$ISO" ] || ISO=$(find_iso || true)

# Без аргументов: есть диск — запускаем его, нет — пробуем Live с ISO.
if [ "$MODE" = auto ]; then
    if [ -f "$DISK" ]; then
        MODE=installed
    elif [ -n "$ISO" ]; then
        MODE=live
    else
        MODE=installed
    fi
fi

command -v qemu-system-x86_64 >/dev/null 2>&1 || die "нет QEMU.
Debian/Ubuntu: sudo apt install qemu-system-x86
Fedora:        sudo dnf install qemu-system-x86
Arch:          sudo pacman -S qemu-full"

if [ "$MODE" = install ]; then
    command -v qemu-img >/dev/null 2>&1 || die "нет qemu-img.
Debian/Ubuntu: sudo apt install qemu-utils"
fi

if [ "$MODE" = installed ]; then
    [ -f "$DISK" ] || die "диска VM ещё нет: $DISK
Посмотреть Live без установки: sh make-vm.sh --live
Установить в виртуальный диск:   sh make-vm.sh --install"
else
    [ -n "$ISO" ] || die "не найден ISO MVS-OS-*-amd64.iso.
Положите ISO рядом со скриптом или укажите путь:
  sh make-vm.sh --live --iso /путь/MVS-OS-${VERSION}-amd64.iso"
    [ -f "$ISO" ] || die "ISO не найден: $ISO"
fi

# KVM ускоряет работу в разы. Без него QEMU тоже запустится.
KVM=0
if [ "${MVS_NO_KVM:-0}" != "1" ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    KVM=1
fi
if [ "$KVM" -eq 0 ]; then
    printf 'Предупреждение: /dev/kvm недоступен, будет медленный программный режим.\n'
    printf 'Обычно помогает: sudo usermod -aG kvm "$USER" и повторный вход.\n\n'
fi

# Выбираем графический бэкенд, который собран в этом QEMU.
DISPLAY_MODE=""
if [ -n "${MVS_DISPLAY:-}" ]; then
    DISPLAY_MODE=$MVS_DISPLAY
elif qemu-system-x86_64 -display help 2>/dev/null | grep -qw gtk; then
    DISPLAY_MODE=gtk
elif qemu-system-x86_64 -display help 2>/dev/null | grep -qw sdl; then
    DISPLAY_MODE=sdl
fi

# virtio-видео быстрее std: кадр передаётся напрямую, без медленной
# эмуляции VGA. Если QEMU собран без virtio — спокойно остаёмся на std.
if [ "$VGA" = auto ]; then
    if qemu-system-x86_64 -vga help 2>&1 | grep -qw virtio; then
        VGA=virtio
    else
        VGA=std
    fi
fi

# Звук: QEMU подключается к PulseAudio/PipeWire хоста. Если сервера
# не видно, не добавляем аудиоустройства — иначе QEMU может не стартовать.
AUDIO_ENABLED=0
case "$AUDIO" in
    1) AUDIO_ENABLED=1 ;;
    0) ;;
    auto)
        runtime=${XDG_RUNTIME_DIR:-/run/user/$(id -u 2>/dev/null || printf 0)}
        if [ -n "${PULSE_SERVER:-}" ] || [ -S "$runtime/pulse/native" ]; then
            AUDIO_ENABLED=1
        fi
        ;;
    *) die "MVS_AUDIO: ожидается auto, 1 или 0" ;;
esac

# Окно GTK по умолчанию НЕ захватывает клавиатуру: Alt+Tab обрабатывает
# рабочий стол Linux, а не гость. MVS_GRAB=1 включает захват — тогда
# Alt+Tab переключает окна внутри MVS OS, а на хост ведёт Ctrl+Alt+G.
if [ "$DISPLAY_MODE" = gtk ]; then
    if [ "${MVS_GRAB:-0}" = 1 ]; then
        DISPLAY_ARGS="gtk,grab-on-hover=on"
    else
        DISPLAY_ARGS="gtk,grab-on-hover=off"
    fi
    if [ "${MVS_GL:-0}" = 1 ]; then
        DISPLAY_ARGS="$DISPLAY_ARGS,gl=on"
    fi
else
    DISPLAY_ARGS=$DISPLAY_MODE
fi

if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ "$DISPLAY_MODE" != "none" ]; then
    printf 'Предупреждение: не видно графического сеанса (DISPLAY/WAYLAND_DISPLAY).\n'
    printf 'Запускайте скрипт из терминала на рабочем столе, а не по SSH.\n\n'
fi

printf '▸ MVS OS %s в окне QEMU\n' "$VERSION"
printf '  режим: %s\n' "$MODE"
printf '  RAM:   %s МБ, ядер: %s, KVM: %s\n' "$RAM" "$CPUS" \
    "$([ "$KVM" -eq 1 ] && printf да || printf нет)"
printf '  видео: %s, сеть: virtio, звук: %s\n' "$VGA" \
    "$([ "$AUDIO_ENABLED" -eq 1 ] && printf да || printf нет)"
if [ -n "$ISO" ]; then
    printf '  ISO:   %s\n' "$ISO"
fi

if [ "$MODE" = install ]; then
    printf '  диск:  %s\n' "$DISK"

    if [ -f "$ISO.sha256" ]; then
        ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$ISO").sha256" ) \
            || die "ISO повреждён (SHA256 не совпал)"
    elif [ -f "$ROOT/SHA256SUMS" ] && [ "$(dirname "$ISO")" = "$ROOT" ]; then
        ( cd "$ROOT" && sha256sum -c SHA256SUMS ) \
            || die "ISO повреждён (SHA256 не совпал)"
    fi

    if [ -e "$DISK" ]; then
        die "диск VM уже существует: $DISK
Удалите его вручную, если действительно хотите переустановить систему."
    fi

    mkdir -p "$(dirname "$DISK")"
    printf '\n▸ создаю диск %s\n' "$SIZE"
    qemu-img create -f qcow2 "$DISK" "$SIZE" >/dev/null
else
    if [ -f "$ISO.sha256" ] || { [ -f "$ROOT/SHA256SUMS" ] && [ "$(dirname "$ISO")" = "$ROOT" ]; }; then
        if [ "${MVS_VERIFY:-0}" = "1" ]; then
            if [ -f "$ISO.sha256" ]; then
                ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$ISO").sha256" ) \
                    || die "ISO повреждён (SHA256 не совпал)"
            else
                ( cd "$ROOT" && sha256sum -c SHA256SUMS ) \
                    || die "ISO повреждён (SHA256 не совпал)"
            fi
        fi
    fi
fi

if [ "$KVM" -eq 1 ]; then
    set -- qemu-system-x86_64 -enable-kvm -cpu host
else
    set -- qemu-system-x86_64 -cpu max
fi
set -- "$@" \
    -name "MVS OS $VERSION" \
    -m "$RAM" -smp "$CPUS" \
    -object iothread,id=mvsio \
    -nic "$NIC" \
    -device qemu-xhci -device usb-tablet \
    -vga "$VGA"

if [ "$AUDIO_ENABLED" -eq 1 ]; then
    set -- "$@" \
        -audiodev pa,id=mvsaudio \
        -device ich9-intel-hda \
        -device hda-duplex,audiodev=mvsaudio
fi

if [ -n "$DISPLAY_ARGS" ]; then
    set -- "$@" -display "$DISPLAY_ARGS"
fi
if [ "$FULLSCREEN" -eq 1 ]; then
    set -- "$@" -full-screen
fi

case "$MODE" in
    live)
        set -- "$@" -cdrom "$ISO" -boot d
        printf '\n▸ загрузка Live с ISO\n'
        printf '  Изменения не сохраняются: это безопасная примерка.\n'
        printf '  Установить на виртуальный диск: sh make-vm.sh --install\n'
        ;;
    install)
        set -- "$@" \
            -drive "file=$DISK,if=none,id=mvsdisk,cache=writeback,discard=unmap,detect-zeroes=unmap" \
            -device "virtio-blk-pci,drive=mvsdisk,iothread=mvsio" \
            -cdrom "$ISO" -boot d
        printf '\n▸ загрузка с ISO\n'
        printf '  Внутри: «Установить MVS OS» → диск /dev/vda (%s).\n' "$SIZE"
        printf '  После установки закройте окно и запустите скрипт без --install.\n'
        ;;
    installed)
        set -- "$@" \
            -drive "file=$DISK,if=none,id=mvsdisk,cache=writeback,discard=unmap,detect-zeroes=unmap" \
            -device "virtio-blk-pci,drive=mvsdisk,iothread=mvsio" \
            -boot c
        printf '\n▸ загрузка установленной системы\n'
        ;;
esac

printf '\n  Alt+Tab — переключиться на Linux, клик по окну — назад в MVS OS.\n'
if [ "${MVS_GRAB:-0}" = 1 ]; then
    printf '  Захват включён: Alt+Tab работает внутри VM, Ctrl+Alt+G — выход на хост.\n'
fi
printf '  Закрыть окно — выключить VM и вернуться в Linux.\n'
printf '  Ctrl+Alt+2 → quit → Enter — аварийный выход. Ctrl+Alt+1 — назад.\n\n'

# Проверка команды без запуска: MVS_DRY_RUN=1 sh make-vm.sh --live
if [ "${MVS_DRY_RUN:-0}" = 1 ]; then
    printf '▸ команда QEMU (dry run):\n'
    printf '  %s\n' "$@"
    exit 0
fi

exec "$@"
