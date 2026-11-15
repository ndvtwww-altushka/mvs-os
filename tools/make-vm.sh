#!/bin/sh
# MVS OS — запуск системы в виртуальной машине, без перезагрузки хоста.
#
# Первый раз (установка в VM):
#   sh tools/make-vm.sh --install
# Дальше (обычный запуск установленной системы):
#   sh tools/make-vm.sh
#
# Переменные окружения:
#   MVS_ISO       путь к ISO (по умолчанию MVS-OS-1.0-amd64.iso в корне)
#   MVS_VM_DISK   путь к диску VM (по умолчанию ~/.local/share/mvs-os/mvs.qcow2)
#   MVS_VM_SIZE   размер нового диска (по умолчанию 24G)
#   MVS_RAM       память в МБ (по умолчанию 4096)
#   MVS_CPUS      число ядер (по умолчанию 4)
#   MVS_VGA       std или virtio (по умолчанию std)
#
# Установщик Calamares внутри VM интерактивный: скрипт создаёт диск,
# проверяет ISO и запускает QEMU, но не нажимает за вас «Установить».

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(tr -d ' \n' < "$ROOT/VERSION" 2>/dev/null || printf '1.0')
ISO=${MVS_ISO:-"$ROOT/MVS-OS-${VERSION}-amd64.iso"}
SIZE=${MVS_VM_SIZE:-24G}
RAM=${MVS_RAM:-4096}
CPUS=${MVS_CPUS:-4}
VGA=${MVS_VGA:-std}
DISK=${MVS_VM_DISK:-"${XDG_DATA_HOME:-${HOME:-$ROOT}/.local/share}/mvs-os/mvs.qcow2"}

INSTALL=0

usage() {
    cat <<EOF
MVS OS — виртуальная машина

  sh tools/make-vm.sh --install   создать диск и запустить установку с ISO
  sh tools/make-vm.sh             запустить уже установленную систему

Переменные: MVS_ISO, MVS_VM_DISK, MVS_VM_SIZE, MVS_RAM, MVS_CPUS, MVS_VGA.
Диск по умолчанию: $DISK
EOF
}

die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

for arg in "$@"; do
    case "$arg" in
        --install) INSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "неизвестный аргумент: $arg (см. --help)" ;;
    esac
done

command -v qemu-system-x86_64 >/dev/null 2>&1 || die "нет QEMU: sudo apt install qemu-system-x86"
command -v qemu-img >/dev/null 2>&1 || die "нет qemu-img: sudo apt install qemu-utils"

# KVM сильно ускоряет работу. Без него QEMU запустится, но будет медленным.
KVM=0
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    KVM=1
else
    printf 'Предупреждение: /dev/kvm недоступен. Будет медленный программный режим.\n'
    printf 'Обычно помогает: sudo usermod -aG kvm "$USER" и повторный вход.\n\n'
fi

printf '▸ MVS OS %s в виртуальной машине\n' "$VERSION"
printf '  диск: %s\n' "$DISK"
printf '  RAM:  %s МБ, ядер: %s, KVM: %s\n' "$RAM" "$CPUS" "$([ "$KVM" -eq 1 ] && printf да || printf нет)"

if [ "$INSTALL" -eq 1 ]; then
    [ -f "$ISO" ] || die "нет ISO: $ISO (соберите build.sh или скачайте артефакт из Actions)"
    printf '  ISO:  %s\n' "$ISO"

    # Проверяем контрольную сумму, если рядом есть файл от сборки.
    if [ -f "$ISO.sha256" ]; then
        ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$ISO").sha256" ) || die "ISO повреждён (SHA256 не совпал)"
    elif [ -f "$ROOT/SHA256SUMS" ] && [ "$(dirname "$ISO")" = "$ROOT" ]; then
        ( cd "$ROOT" && sha256sum -c SHA256SUMS ) || die "ISO повреждён (SHA256 не совпал)"
    elif command -v sha256sum >/dev/null 2>&1; then
        printf '  SHA256: %s\n' "$(sha256sum "$ISO" | cut -d' ' -f1)"
    fi

    if [ -e "$DISK" ]; then
        die "диск VM уже существует: $DISK
Удалите его вручную, если действительно хотите переустановить систему."
    fi

    mkdir -p "$(dirname "$DISK")"
    printf '\n▸ создаю диск %s\n' "$SIZE"
    qemu-img create -f qcow2 "$DISK" "$SIZE" >/dev/null
else
    [ -f "$DISK" ] || die "диска VM ещё нет: $DISK
Сначала установите систему: sh tools/make-vm.sh --install"
fi

if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    printf 'Предупреждение: не видно графического сеанса (DISPLAY/WAYLAND_DISPLAY).\n'
    printf 'Запускайте скрипт из терминала на рабочем столе, а не по SSH.\n\n'
fi

set -- qemu-system-x86_64
[ "$KVM" -eq 1 ] && set -- "$@" -enable-kvm
set -- "$@" \
    -name "MVS OS" \
    -m "$RAM" -smp "$CPUS" \
    -nic user,model=e1000 \
    -usb -device usb-tablet \
    -vga "$VGA" \
    -drive "file=$DISK,if=virtio"

if [ "$INSTALL" -eq 1 ]; then
    set -- "$@" -cdrom "$ISO" -boot d
    printf '\n▸ загрузка с ISO\n'
    printf '  Внутри: «Установить MVS OS» → диск /dev/vda (%s).\n' "$SIZE"
    printf '  После установки закройте окно и запустите скрипт без --install.\n\n'
else
    set -- "$@" -boot c
    printf '\n▸ загрузка установленной системы\n\n'
fi

exec "$@"
