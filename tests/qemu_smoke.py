#!/usr/bin/env python3
"""MVS OS — дымовой тест загрузки ISO в QEMU.

Что проверяется:
    1. ISO не просто показывает меню GRUB: тест нажимает Enter и ждёт,
       пока ядро начнёт загрузку.
    2. Система дошла до настоящего Live-сеанса: служба mvs-boot-check
       пишет в последовательный порт MVS_BOOT_OK только когда пользователь
       mvs создан и у него работает XFCE. Меню GRUB или экран входа
       с несуществующим пользователем этот маркер не дают.
    3. Снимок экрана не пустой и похож на рабочий стол.

Режимы:
    BIOS (по умолчанию) — обычная загрузка, как на старом ПК.
    --uefi              — загрузка через OVMF, проверка UEFI-пути.
    --secure-boot       — UEFI с включённой проверкой подписи (shim + GRUB).

Чего тест НЕ проверяет (честно):
    работоспособность установщика, звук, Wi-Fi, реальные драйверы.
    Это требует ручной проверки на железе или полноценного autopilot.

Запуск:
    python3 tests/qemu_smoke.py MVS-OS-1.4-amd64.iso
    python3 tests/qemu_smoke.py --uefi MVS-OS-1.4-amd64.iso
    python3 tests/qemu_smoke.py --secure-boot MVS-OS-1.4-amd64.iso

Переменные:
    MVS_QEMU_BOOT   секунд на загрузку (по умолчанию 180)
    MVS_OVMF        путь к OVMF_CODE или объединённому OVMF.fd
    MVS_OVMF_VARS   путь к OVMF_VARS (если не угадывается рядом)
    MVS_OVMF_SECBOOT       OVMF_CODE с поддержкой Secure Boot
    MVS_OVMF_SECBOOT_VARS  переменные OVMF с ключами Microsoft
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

# Secure Boot: OVMF с SMM и ключами Microsoft. Прошивка проверит подпись
# shim (BOOTX64.EFI), shim — подпись GRUB, и только потом ядро.
OVMF_SECBOOT_PAIRS = [
    ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
    ("/usr/share/OVMF/OVMF_CODE.secboot.fd", "/usr/share/OVMF/OVMF_VARS.ms.fd"),
    ("/usr/share/ovmf/OVMF_CODE_4M.secboot.fd", "/usr/share/ovmf/OVMF_VARS_4M.ms.fd"),
    ("/usr/share/OVMF/OVMF_CODE.secboot.fd", "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
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


def secure_boot_arguments(vars_copy):
    """QEMU с включённой проверкой подписи загрузчика."""
    code = os.environ.get("MVS_OVMF_SECBOOT", "")
    vars_path = os.environ.get("MVS_OVMF_SECBOOT_VARS", "")

    if not code:
        for candidate_code, candidate_vars in OVMF_SECBOOT_PAIRS:
            if os.path.isfile(candidate_code):
                code = candidate_code
                if not vars_path and os.path.isfile(candidate_vars):
                    vars_path = candidate_vars
                break

    if not code or not vars_path:
        raise RuntimeError(
            "нет OVMF для Secure Boot: sudo apt install ovmf "
            "(или задайте MVS_OVMF_SECBOOT и MVS_OVMF_SECBOOT_VARS)"
        )

    shutil.copyfile(vars_path, vars_copy)
    return [
        "-machine", "q35,smm=on",
        "-global", "driver=cfi.pflash01,property=secure,value=on",
        "-drive", "if=pflash,format=raw,readonly=on,file=%s" % code,
        "-drive", "if=pflash,format=raw,file=%s" % vars_copy,
    ]


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


def screen_state(path):
    """Похож ли снимок на загруженную систему, а не на экран ошибки.

    Ошибка Secure Boot в OVMF — это чёрный фон и несколько строк текста.
    Рабочий стол или экран входа — это заливка, значки и градиенты.
    Поэтому смотрим долю «цветных» точек и число оттенков, а не просто
    «файл не пустой»: иначе сообщение «Secure Boot violation» прошло бы
    как успешная загрузка.
    """
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
        if position >= len(data):
            break
        fields.append(int(data[start:position]))
    pixels = data[position + 1:]
    if len(fields) < 3 or len(pixels) < 3000:
        return False, "в снимке нет пикселей"

    # Шаг кратен трём байтам, иначе RGB-каналы разъедутся.
    step = max(3, (len(pixels) // 3 // 40000) * 3)
    colors = set()
    colored = 0
    samples = 0
    for offset in range(0, len(pixels) - 2, step):
        red, green, blue = pixels[offset], pixels[offset + 1], pixels[offset + 2]
        colors.add((red >> 3, green >> 3, blue >> 3))
        if red + green + blue > 36:
            colored += 1
        samples += 1

    share = colored / samples if samples else 0.0
    detail = "цветных точек %.0f%%, оттенков %d" % (share * 100, len(colors))
    return share >= 0.04 and len(colors) >= 24, detail


def read_text(path):
    """Содержимое файла или пустая строка, если его ещё нет."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def wait_for_boot(sock, serial_path, timeout, process):
    """Нажимает Enter в меню и ждёт маркер реального сеанса.

    Возвращает (успех, пояснение, текст serial). Маркер MVS_BOOT_OK
    пишет служба mvs-boot-check после того, как live-config создал
    пользователя mvs и LightDM поднял его сеанс XFCE.
    """
    started = time.time()
    presses = 0

    # Пока ядро не начало вывод, считаем, что мы в меню загрузчика.
    # Enter выбирает «Live system (amd64)»; в BIOS это ISOLINUX,
    # в UEFI — GRUB. Лишние нажатия после старта ядра безвредны.
    while time.time() - started < min(90, timeout):
        if process.poll() is not None:
            return False, "QEMU завершился с кодом %s" % process.returncode, read_text(serial_path)
        text = read_text(serial_path)
        if "Linux version" in text or "MVS_BOOT_" in text or "Kernel panic" in text:
            break
        if presses < 40:
            monitor_command(sock, "sendkey ret")
            presses += 1
        time.sleep(2)

    deadline = started + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False, "QEMU завершился с кодом %s" % process.returncode, read_text(serial_path)
        text = read_text(serial_path)
        if "MVS_BOOT_OK" in text:
            return True, "маркер сеанса mvs найден", text
        if "MVS_BOOT_FAIL" in text:
            line = [l for l in text.splitlines() if "MVS_BOOT_FAIL" in l]
            return False, (line[-1] if line else "маркер MVS_BOOT_FAIL"), text
        if "Kernel panic" in text:
            return False, "паника ядра", text
        time.sleep(2)

    return False, "маркер MVS_BOOT_OK не появился за %d с" % timeout, read_text(serial_path)


def main(argv):
    uefi = False
    secure_boot = False
    paths = []
    for arg in argv[1:]:
        if arg == "--uefi":
            uefi = True
        elif arg == "--secure-boot":
            uefi = True
            secure_boot = True
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

    if secure_boot:
        suffix = "-secureboot"
    elif uefi:
        suffix = "-uefi"
    else:
        suffix = ""
    monitor = "/tmp/mvs-qemu-monitor%s.sock" % suffix
    screenshot = "boot%s.ppm" % suffix
    serial = "serial%s.log" % suffix
    log = "qemu%s.log" % suffix
    vars_copy = "ovmf-vars%s.fd" % suffix

    # Старый serial.log с маркером прошлого запуска не должен
    # засчитать эту загрузку: чистим все файлы теста.
    for path in (monitor, screenshot, serial, log, vars_copy):
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

    if secure_boot:
        try:
            command.extend(secure_boot_arguments(vars_copy))
        except RuntimeError as exc:
            print("FAIL: %s" % exc, file=sys.stderr)
            return 2
    elif uefi:
        try:
            command.extend(uefi_arguments(vars_copy))
        except RuntimeError as exc:
            print("FAIL: %s" % exc, file=sys.stderr)
            return 2

    if secure_boot:
        mode_name = "UEFI + Secure Boot"
    elif uefi:
        mode_name = "UEFI (OVMF)"
    else:
        mode_name = "BIOS"
    print("Режим: %s" % mode_name)
    print("$ %s" % " ".join(command))
    with open(log, "wb") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)

    try:
        if not wait_for_socket(monitor):
            print("FAIL: монитор QEMU не поднялся")
            return 1

        ok = False
        detail = "тест не дошел до проверки"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(monitor)

            print("Загружаем ISO: Enter в меню, ждём MVS_BOOT_OK (до %d с)…" % BOOT_SECONDS)
            ok, detail, serial_text = wait_for_boot(sock, serial, BOOT_SECONDS, process)
            print("%s: %s" % ("OK" if ok else "FAIL", detail))

            # Снимок делаем в любом случае: при падении он нужен для разбора.
            try:
                monitor_command(sock, "screendump %s" % screenshot)
                time.sleep(2)
            finally:
                try:
                    monitor_command(sock, "quit")
                except OSError:
                    pass
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

    screen_ok, screen_detail = screen_state(screenshot)
    print("%s: %s" % ("OK" if screen_ok else "FAIL", screen_detail))

    if "Kernel panic" in serial_text:
        print("FAIL: в последовательном порту паника ядра")
        return 1
    if not ok:
        print("FAIL: система не подтвердила вход в сеанс mvs")
        print("      смотрите %s и %s" % (serial, screenshot))
        return 1
    if not screen_ok:
        print("FAIL: сеанс есть, но экран не похож на рабочий стол")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
