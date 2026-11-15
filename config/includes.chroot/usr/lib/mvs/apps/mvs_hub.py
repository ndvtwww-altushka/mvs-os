#!/usr/bin/env python3
"""MVS Hub — центр приложений и быстрый запуск."""

import os
import subprocess
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

MVS_APPS = [
    ("Control Center", "Все настройки системы", "mvs-control", "mvs-control"),
    ("Store", "Установка программ", "mvs-store", "mvs-store"),
    ("Update", "Обновления", "mvs-update", "mvs-update"),
    ("Monitor", "Процессы и ресурсы", "mvs-monitor", "mvs-monitor"),
    ("Doctor", "Проверка системы", "mvs-doctor", "mvs-doctor"),
    ("Cleaner", "Очистка кэша", "mvs-cleaner", "mvs-cleaner"),
    ("Backup", "Резервные копии", "mvs-backup", "mvs-backup"),
    ("Games", "Мини-игры", "mvs-games", "mvs-games"),
    ("Files", "Проводник", "mvs-files", "system-file-manager"),
    ("Terminal", "Терминал", "mvs-terminal", "utilities-terminal"),
    ("Welcome", "Знакомство с системой", "mvs-welcome", "mvs-welcome"),
    ("About", "О системе", "mvs-about", "mvs-about"),
    ("Settings", "Настройки", "mvs-settings", "preferences-system"),
]


def launch(command):
    try:
        subprocess.Popen(
            [command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except OSError:
        return False


class Hub(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Hub", "Все приложения системы", 1000, 720, "mvs-hub")

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Поиск приложений…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _w: self.apply_filter())

        self.mvs_flow = Gtk.FlowBox()
        self.mvs_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.mvs_flow.set_max_children_per_line(6)
        self.mvs_flow.set_row_spacing(10)
        self.mvs_flow.set_column_spacing(10)

        for title, subtitle, command, icon in MVS_APPS:
            self.mvs_flow.add(self.tile(title, subtitle, icon, lambda _b, cmd=command: launch(cmd)))

        self.all_flow = Gtk.FlowBox()
        self.all_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.all_flow.set_max_children_per_line(7)
        self.all_flow.set_row_spacing(8)
        self.all_flow.set_column_spacing(8)
        for app_info in Gio.AppInfo.get_all():
            name = app_info.get_name() or ""
            if not name or not app_info.should_show():
                continue
            icon = app_info.get_icon()
            self.all_flow.add(self.tile(name, "", icon, self.launcher(app_info)))
            if len(self.all_flow.get_children()) >= 240:
                break

        self.mvs_flow.set_filter_func(self.filter_func)
        self.all_flow.set_filter_func(self.filter_func)

        page = ui.page(
            ui.h1("MVS Hub"),
            ui.subtle("Фирменные приложения MVS и установленные программы"),
            self.search,
            ui.card(ui.h2("Приложения MVS"), self.mvs_flow),
            ui.card(ui.h2("Все программы"), ui.scrolled(self.all_flow, 320)),
        )
        self.add_page("hub", "Приложения", "view-app-grid", page)

    def tile(self, title, subtitle, icon, callback):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("mvs-tile")
        box = ui.vbox(6)

        if isinstance(icon, str):
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
        elif icon is not None:
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.DIALOG)
        else:
            image = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)

        image.set_pixel_size(40)
        box.pack_start(image, False, False, 0)
        box.pack_start(ui.label(title, "mvs-h2", xalign=0.5), False, False, 0)
        if subtitle:
            box.pack_start(ui.subtle(subtitle), False, False, 0)
        button.add(box)
        button.set_tooltip_text(title)
        button.connect("clicked", callback)
        button.search_text = title.lower()
        button.show_all()
        return button

    def launcher(self, app_info):
        def start(_button):
            try:
                app_info.launch([], None)
            except Exception:
                ui.error(self, "Не удалось запустить %s" % (app_info.get_name() or "программу"))
        return start

    def filter_func(self, child):
        text = self.search.get_text().strip().lower()
        if not text:
            return True
        widget = child.get_child() if hasattr(child, "get_child") else child
        target = getattr(widget, "search_text", None)
        if target is None:
            target = (widget.get_tooltip_text() or "").lower() if widget is not None else ""
        return text in target

    def apply_filter(self):
        self.mvs_flow.invalidate_filter()
        self.all_flow.invalidate_filter()


def main():
    Hub().run()


if __name__ == "__main__":
    main()
