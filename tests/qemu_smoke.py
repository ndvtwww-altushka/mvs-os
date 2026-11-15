#!/usr/bin/env python3
"""MVS OS — дымовой тест загрузки ISO в QEMU.

Что проверяется:
    1. ISO вообще стартует в виртуальной машине (нет паники ядра, нет
       мгновенного выхода QEMU).
    2. К моменту снимка экрана framebuffer не пустой: значит, ядро
       инициализировало графику и что-то нарисовало (GRUB или система).

Режимы:
    BIOS (по умолчанию) — обычная загрузка, как на старом ПК.
    --uefi              — загрузка через OVMF, проверка UEFI-пути.

Чего тест НЕ проверяет (честно):
    работоспособность установщика, звук, Wi-Fi, реальные драйверы.
    Это требует ручной проверки на железе или полноценного autopilot.

Запуск:
    python3 tests/qemu_smoke.py MVS-OS-1.0-amd64.iso
    python3 tests/qemu_smoke.py --uefi MVS-OS-1.0-amd64.iso

Переменные:
    MVS_QEMU_BOOT   секунд на загрузку (по умолчанию 180)
    MVS_OVMF        путь к OVMF_CODE или объединённому OVMF.fd
    MVS_OVMF_VARS   путь к OVMF_VARS (если не угадывается рядом)
"""

import os
import shutil
import socket
import subprocess
import sys
import time

BOOT_SECONDS = int(os.environ.get("MVS_QEMU_BOOT", "180"))

OVMF_PAIRS = [
    ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
    ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
    ("/usr/share/ovmf/OVMF_CODE.fd", "/usr/share/ovmf/OVMF_VARS.fd"),
]

OVMF_COMBINED = [
    "/usr/share/ovmf/OVMF.fd",
    "/usr/share/OVMF/OVMF.fd",
    "/usr/share/qemu/OVMF.fd",
]


def uefi_arguments(vars_copy):
    """Возвращает аргументы QEMU для OVMF или понятную ошибку."""
    code = os.environ.get("MVS_OVMF", "")
    vars_path = os.environ.get("MVS_OVMF_VARS", "")

    if not code:
        for candidate_code, candidate_vars in OVMF_PAIRS:
            if os.path.isfile(candidate_code):
                code = candidate_code
                if not vars_path and os.path.isfile(candidate_vars):
                    vars_path = candidate_vars
                break

    if not code:
        for candidate in OVMF_COMBINED:
            if os.path.isfile(candidate):
                code = candidate
                break

    if not code:
        raise RuntimeError(
            "нет OVMF: sudo apt install ovmf "
            "(или задайте MVS_OVMF и MVS_OVMF_VARS)"
        )

    if vars_path:
        if not os.path.isfile(vars_path):
            raise RuntimeError("нет файла OVMF_VARS: %s" % vars_path)
        shutil.copyfile(vars_path, vars_copy)
        return [
            "-drive", "if=pflash,format=raw,readonly=on,file=%s" % code,
            "-drive", "if=pflash,format=raw,file=%s" % vars_copy,
        ]

    # Объединённый OVMF.fd (код + переменные) читается через -bios.
    return ["-bios", code]


def wait_for_socket(path, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.5)
    return False


def monitor_command(sock, text):
    sock.sendall(text.encode("utf-8") + b"\n")
    time.sleep(0.7)
    try:
        sock.recv(65536)
    except OSError:
        pass


def ppm_is_not_blank(path):
    """PPM (P6) — заголовок из 3 строк, дальше RGB-данные."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(b"P6"):
        return False, "файл не PPM P6"
    fields = []
    position = 2
    while len(fields) < 3 and position < len(data):
        if data[position:position + 1].isspace():
            position += 1
            continue
        start = position
        while position < len(data) and not data[position:position + 1].isspace():
            position += 1
        fields.append(int(data[start:position]))
    pixels = data[position + 1:]
    if len(pixels) < 300:
        return False, "в снимке нет пикселей"
    sample = pixels[: 3 * 20000]
    return len(set(sample)) > 24, "уникальных байт: %d" % len(set(sample))


def main(argv):
    uefi = False
    paths = []
    for arg in argv[1:]:
        if arg == "--uefi":
            uefi = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        elif arg.startswith("-"):
            print("Неизвестный аргумент: %s" % arg, file=sys.stderr)
            return 2
        else:
            paths.append(arg)

    if len(paths) != 1:
        print("Укажите один путь к ISO (см. --help)", file=sys.stderr)
        return 2

    iso = paths[0]
    if not os.path.isfile(iso):
        print("ISO не найден: %s" % iso, file=sys.stderr)
        return 2

    suffix = "-uefi" if uefi else ""
    monitor = "/tmp/mvs-qemu-monitor%s.sock" % suffix
    screenshot = "boot%s.ppm" % suffix
    serial = "serial%s.log" % suffix
    log = "qemu%s.log" % suffix
    vars_copy = "ovmf-vars%s.fd" % suffix

    for path in (monitor, screenshot):
        if os.path.exists(path):
            os.unlink(path)

    command = [
        "qemu-system-x86_64",
        "-m", "2048",
        "-smp", "2",
        "-cdrom", iso,
        "-boot", "d",
        "-display", "none",
        "-no-reboot",
        "-monitor", "unix:%s,server,nowait" % monitor,
        "-serial", "file:%s" % serial,
    ]

    if uefi:
        try:
            command.extend(uefi_arguments(vars_copy))
        except RuntimeError as exc:
            print("FAIL: %s" % exc, file=sys.stderr)
            return 2

    print("Режим: %s" % ("UEFI (OVMF)" if uefi else "BIOS"))
    print("$ %s" % " ".join(command))
    with open(log, "wb") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)

    try:
        if not wait_for_socket(monitor):
            print("FAIL: монитор QEMU не поднялся")
            return 1

        print("Ждём %d секунд загрузки…" % BOOT_SECONDS)
        time.sleep(BOOT_SECONDS)

        if process.poll() is not None:
            print("FAIL: QEMU завершился с кодом %s" % process.returncode)
            return 1

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(monitor)
            monitor_command(sock, "screendump %s" % screenshot)
            time.sleep(2)
            monitor_command(sock, "quit")
            time.sleep(1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

    if not os.path.isfile(screenshot):
        print("FAIL: снимок экрана не создан")
        return 1

    ok, detail = ppm_is_not_blank(screenshot)
    print("%s: %s" % ("OK" if ok else "FAIL", detail))

    serial_text = ""
    if os.path.isfile(serial):
        with open(serial, "r", encoding="utf-8", errors="replace") as handle:
            serial_text = handle.read()
    if "Kernel panic" in serial_text:
        print("FAIL: в последовательном порту паника ядра")
        return 1

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
