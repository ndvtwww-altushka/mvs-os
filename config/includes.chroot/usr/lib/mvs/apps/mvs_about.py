#!/usr/bin/env python3
"""MVS About — сведения о системе MVS OS."""

import os
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


def read(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def cpu_model():
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "—"


def memory_total():
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal"):
            try:
                return ui.human_bytes(float(line.split()[1]) * 1024)
            except (ValueError, IndexError):
                return "—"
    return "—"


def uptime():
    try:
        seconds = float(read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        return "—"
    return "%d ч %d мин" % (int(seconds // 3600), int(seconds % 3600 // 60))


def disk_total():
    try:
        stat = os.statvfs("/")
        return ui.human_bytes(stat.f_blocks * stat.f_frsize)
    except OSError:
        return "—"


class About(ui.MvsWindow):
    def __init__(self):
        super().__init__(
            "О системе MVS OS", "Версия, оборудование, лицензии", 860, 660, "mvs-about"
        )

        logo = Gtk.Image.new_from_file("/usr/share/pixmaps/mvs-logo.svg")
        logo.set_pixel_size(96)

        hero = ui.card(
            logo,
            ui.h1("MVS OS %s «%s»" % (ui.VERSION, ui.CODENAME)),
            ui.subtle(
                "Собственная операционная система на базе Debian GNU/Linux 12 bookworm. "
                "Рабочий стол XFCE, фирменная тема и приложения MVS.",
                wrap=True,
            ),
        )

        system = ui.card(
            ui.h2("Система"),
            ui.row("Ядро Linux", ui.out(["uname", "-r"]) or "—"),
            ui.label("", "mvs-sep"),
            ui.row("Сборка Debian", "12 bookworm"),
            ui.label("", "mvs-sep"),
            ui.row("Время работы", uptime()),
            ui.label("", "mvs-sep"),
            ui.row("Пользователь", ui.out(["id", "-un"]) or "mvs"),
        )

        hardware = ui.card(
            ui.h2("Оборудование"),
            ui.row("Процессор", cpu_model(), suffix=ui.label("%d ядер" % (os.cpu_count() or 1), "mvs-subtle")),
            ui.label("", "mvs-sep"),
            ui.row("Память", memory_total()),
            ui.label("", "mvs-sep"),
            ui.row("Диск", "корневая файловая система: " + disk_total()),
        )

        apps = ui.card(
            ui.h2("Приложения MVS"),
            ui.subtle(
                "Control Center, Store, Update, Monitor, Cleaner, Backup, Hub, Games, "
                "Terminal, Files, Welcome, About.",
                wrap=True,
            ),
        )

        licenses = ui.card(
            ui.h2("Лицензии и данные"),
            ui.subtle(
                "MVS OS распространяется как свободное ПО на условиях лицензий Debian "
                "и входящих пакетов. Торговые марки принадлежат их владельцам. "
                "Система не собирает и не отправляет данные о пользователе.",
                wrap=True,
            ),
            ui.button("Показать лицензии Debian", self.show_licenses),
        )

        page = ui.page(hero, system, hardware, apps, licenses)
        self.add_page("about", "О системе", "help-about", page)

    def show_licenses(self, _button):
        text = read("/usr/share/common-licenses/GPL-3", "")
        dialog = Gtk.Dialog(title="Лицензии", transient_for=self, modal=True)
        dialog.set_default_size(760, 560)
        dialog.add_buttons("Закрыть", Gtk.ResponseType.CLOSE)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.get_buffer().set_text(text[:20000] or "Файл лицензий не найден.")
        area = Gtk.ScrolledWindow()
        area.add(view)
        dialog.get_content_area().pack_start(area, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()


def main():
    About().run()


if __name__ == "__main__":
    main()
