#!/usr/bin/env python3
"""MVS Doctor — проверка состояния системы без выдуманных «оценок».

Проверяет то, что действительно можно прочитать без root: место на диске,
память, сбойные службы systemd, состояние ufw и AppArmor, доступные
обновления, маршрут по умолчанию и синхронизацию времени.

Красная строка не означает «система сломана»: это повод открыть
подробности. Отчёт сохраняется в домашнюю папку обычным текстом.
"""

import datetime
import os
import platform
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

FIELDS = [
    ("disk", "Диск"),
    ("memory", "Память"),
    ("services", "Службы"),
    ("firewall", "Межсетевой экран"),
    ("apparmor", "AppArmor"),
    ("updates", "Обновления"),
    ("network", "Сеть"),
    ("time", "Время"),
]

STATUS_CLASSES = ("mvs-ok", "mvs-warn", "mvs-bad", "mvs-dim")


def read(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def meminfo():
    data = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        try:
            data[key] = float(rest.strip().split()[0]) * 1024.0
        except (ValueError, IndexError):
            pass
    return data


def os_pretty():
    for line in read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return "MVS OS"


def cpu_model():
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "неизвестно"


def uptime_text():
    try:
        seconds = int(float(read("/proc/uptime").split()[0]))
    except (ValueError, IndexError):
        return "неизвестно"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append("%d д" % days)
    if hours:
        parts.append("%d ч" % hours)
    parts.append("%d мин" % minutes)
    return " ".join(parts)


def apt_indexes_ready():
    try:
        return any(
            entry.endswith("Packages")
            for _root, _dirs, files in os.walk("/var/lib/apt/lists")
            for entry in files
        )
    except OSError:
        return False


def check_disk():
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
    except OSError as exc:
        return "bad", "недоступно", str(exc)
    if total <= 0:
        return "dim", "недоступно", "statvfs вернул нулевой размер"
    used = max(0, total - free)
    percent = used * 100.0 / total
    if percent >= 95:
        level = "bad"
    elif percent >= 85:
        level = "warn"
    else:
        level = "ok"
    return (
        level,
        "%d%% занято" % percent,
        "свободно %s из %s" % (ui.human_bytes(free), ui.human_bytes(total)),
    )


def check_memory():
    mem = meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    if total <= 0:
        return "dim", "недоступно", "нет данных /proc/meminfo"
    used = max(0, total - available)
    percent = used * 100.0 / total
    if percent >= 95:
        level = "bad"
    elif percent >= 85:
        level = "warn"
    else:
        level = "ok"
    return (
        level,
        "%d%% занято" % percent,
        "доступно %s из %s" % (ui.human_bytes(available), ui.human_bytes(total)),
    )


def check_services():
    code, out, err = ui.run(
        ["systemctl", "--failed", "--no-legend", "--no-pager"], timeout=10
    )
    if code == 127:
        return "dim", "недоступно", "systemctl не найден"
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if code != 0 and not lines:
        return "warn", "нет ответа", (err or "systemctl завершился с ошибкой").strip()
    if not lines:
        return "ok", "сбоев нет", "systemd не сообщает об ошибках"
    detail = "; ".join(lines[:3])
    if len(lines) > 3:
        detail += " и ещё %d" % (len(lines) - 3)
    return "bad", "%d с ошибкой" % len(lines), detail


def check_firewall():
    active = ui.run(["systemctl", "is-active", "ufw"], timeout=5)[1].strip()
    policy = ""
    for line in read("/etc/default/ufw").splitlines():
        if line.startswith("DEFAULT_INPUT_POLICY="):
            policy = line.split("=", 1)[1].strip().strip('"')
    detail = "входящие: %s" % (policy or "политика неизвестна")
    if active == "active":
        return "ok", "включён", detail
    if active == "inactive":
        return "warn", "выключен", detail
    return "dim", active or "недоступно", detail


def check_apparmor():
    enabled = read("/sys/module/apparmor/parameters/enabled").strip()
    service = ui.run(["systemctl", "is-active", "apparmor"], timeout=5)[1].strip()
    if enabled == "Y" and service == "active":
        return "ok", "активен", "модуль ядра и служба работают"
    if enabled == "Y":
        return "warn", "служба не активна", "модуль ядра загружен, профили не применяются"
    if enabled == "N":
        return "warn", "выключен", "модуль ядра сообщает enabled=N"
    return "dim", "недоступно", "нет /sys/module/apparmor/parameters/enabled"


def check_updates():
    if not apt_indexes_ready():
        return "warn", "индексы не загружены", "откройте MVS Store и обновите индексы"
    code, out, err = ui.run(["apt", "list", "--upgradable"], timeout=60)
    if code == 127:
        return "dim", "недоступно", "apt не найден"
    count = 0
    for line in out.splitlines():
        name = line.split("/", 1)[0]
        if "/" in line and " " not in name:
            count += 1
    if count:
        return "warn", "%d доступно" % count, "обновления ставятся через MVS Update"
    if code != 0 and err.strip():
        return "warn", "нет ответа", err.strip().splitlines()[0][:160]
    return "ok", "нет обновлений", "подключённые репозитории не предлагают обновлений"


def check_network():
    interface = ""
    for line in read("/proc/net/route").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            interface = parts[0]
            break
    if interface:
        return "ok", "подключено", "маршрут по умолчанию: %s" % interface
    return "warn", "нет маршрута", "проверьте Wi-Fi или кабель"


def check_time():
    code, out, err = ui.run(
        ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=5
    )
    if code == 127:
        return "dim", "недоступно", "timedatectl не найден"
    value = out.strip()
    if value == "yes":
        return "ok", "синхронизировано", "системные часы синхронизированы по NTP"
    if value == "no":
        return "warn", "не синхронизировано", "проверьте сеть и службу времени"
    return "dim", "неизвестно", (err or out).strip()[:160] or "timedatectl не ответил"


CHECKS = {
    "disk": check_disk,
    "memory": check_memory,
    "services": check_services,
    "firewall": check_firewall,
    "apparmor": check_apparmor,
    "updates": check_updates,
    "network": check_network,
    "time": check_time,
}


class Doctor(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Doctor", "Проверка системы", 980, 720, "mvs-doctor")

        self.results = {}
        self.status_labels = {}
        self.detail_labels = {}
        self.report_dir = os.path.expanduser("~")

        self.summary = ui.label("Проверка ещё не запускалась", "mvs-subtle")
        self.report_hint = ui.subtle("Отчёт ещё не создан.")

        rows = ui.vbox(10)
        for key, title in FIELDS:
            status = ui.label("—", "mvs-dim")
            detail = ui.subtle("ещё не проверялось")
            self.status_labels[key] = status
            self.detail_labels[key] = detail
            rows.pack_start(ui.row(title, detail, status), False, False, 0)

        actions = ui.hbox(10)
        actions.pack_start(
            ui.button("Проверить всё", self.check_all, "mvs-button accent"),
            False,
            False,
            0,
        )
        actions.pack_start(ui.button("Создать отчёт", self.make_report), False, False, 0)

        check_page = ui.page(
            ui.h1("MVS Doctor"),
            ui.subtle(
                "Реальные проверки без root: диск, память, службы, защита, "
                "обновления и сеть."
            ),
            ui.card(
                ui.h2("Система"),
                ui.label(os_pretty(), "mvs-h2"),
                ui.subtle(
                    "ядро %s · %s · процессор: %s"
                    % (platform.release(), uptime_text(), cpu_model())
                ),
            ),
            ui.card(ui.h2("Состояние"), self.summary, rows),
            ui.card(ui.h2("Действия"), actions, self.report_hint),
        )

        self.log = ui.LogView(420)
        report_page = ui.page(
            ui.h1("Отчёт"),
            ui.subtle("Текстовая копия проверки: её можно сохранить или отправить."),
            ui.card(self.log),
        )

        self.add_page("check", "Проверка", "dialog-information", check_page)
        self.add_page("report", "Отчёт", "text-x-generic", report_page)
        self.select("check")

    # -- вывод --------------------------------------------------------------

    def set_result(self, key, level, status, detail):
        label = self.status_labels[key]
        for name in STATUS_CLASSES:
            label.get_style_context().remove_class(name)
        label.get_style_context().add_class("mvs-%s" % level)
        label.set_text(status)
        self.detail_labels[key].set_text(detail)

    def check_all(self, _button=None):
        self.summary.set_text("Проверка…")
        for name in STATUS_CLASSES + ("mvs-subtle",):
            self.summary.get_style_context().remove_class(name)
        self.summary.get_style_context().add_class("mvs-subtle")
        self.log.clear()
        self.log.append("MVS Doctor — %s" % datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))
        self.log.append("")

        levels = []
        for key, title in FIELDS:
            try:
                level, status, detail = CHECKS[key]()
            except Exception as exc:  # проверка не должна ронять приложение
                level, status, detail = "bad", "ошибка", str(exc)
            self.results[key] = (title, status, detail, level)
            self.set_result(key, level, status, detail)
            levels.append(level)
            self.log.append("%s: %s — %s" % (title, status, detail))

        if "bad" in levels:
            summary, level = "Нужно внимание", "bad"
        elif "warn" in levels:
            summary, level = "Есть замечания", "warn"
        else:
            summary, level = "Всё в порядке", "ok"

        self.summary.set_text(summary)
        for name in STATUS_CLASSES + ("mvs-subtle",):
            self.summary.get_style_context().remove_class(name)
        self.summary.get_style_context().add_class("mvs-%s" % level)
        self.log.append("")
        self.log.append("Итог: %s" % summary)

    # -- отчёт --------------------------------------------------------------

    def report_text(self):
        lines = [
            "MVS OS — отчёт MVS Doctor",
            "Дата: %s" % datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "Система: %s" % os_pretty(),
            "Ядро: %s" % platform.release(),
            "Процессор: %s" % cpu_model(),
            "Время работы: %s" % uptime_text(),
            "",
        ]
        for key, title in FIELDS:
            _title, status, detail, _level = self.results.get(
                key, (title, "не проверялось", "—", "dim")
            )
            lines.append("%s: %s — %s" % (title, status, detail))
        lines.append("")
        lines.append("Отчёт создан MVS Doctor. Красная строка — повод проверить")
        lines.append("подробности, а не приговор системе.")
        return "\n".join(lines) + "\n"

    def make_report(self, _button=None):
        if not self.results:
            self.check_all()
        name = "MVS-report-%s.txt" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self.report_dir, name)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.report_text())
        except OSError as exc:
            ui.error(self, "Не удалось сохранить отчёт:\n%s" % exc)
            return
        self.report_hint.set_text("Отчёт: %s" % path)
        self.log.append("")
        self.log.append("Отчёт сохранён: %s" % path)
        ui.info(self, "Отчёт сохранён:\n%s" % path)


def main():
    Doctor().run()


if __name__ == "__main__":
    main()
