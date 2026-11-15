#!/usr/bin/env python3
"""MVS Cleaner — безопасная очистка кэшей, журналов и корзины."""

import os
import shutil
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


def dir_size(path):
    code, text, _err = ui.run(["du", "-sb", path], timeout=30)
    if code != 0 or not text:
        return 0
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return 0


def clear_directory(path):
    """Удаляет содержимое папки, саму папку оставляет."""
    removed = 0
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                removed += dir_size(entry.path)
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                removed += entry.stat(follow_symlinks=False).st_size
                os.unlink(entry.path)
        except OSError:
            continue
    return removed


TARGETS = [
    {
        "id": "apt",
        "name": "Кэш пакетов APT",
        "path": "/var/cache/apt/archives",
        "description": "Скачанные .deb, которые уже установлены",
        "command": ["apt-get", "clean"],
        "privileged": True,
    },
    {
        "id": "journal",
        "name": "Журналы systemd",
        "path": "/var/log/journal",
        "description": "Оставляем последние 7 дней",
        "command": ["journalctl", "--vacuum-time=7d"],
        "privileged": True,
    },
    {
        "id": "cache",
        "name": "Кэш пользователя",
        "path": os.path.expanduser("~/.cache"),
        "description": "Кэш браузеров и приложений",
        "command": None,
        "privileged": False,
    },
    {
        "id": "thumb",
        "name": "Миниатюры",
        "path": os.path.expanduser("~/.cache/thumbnails"),
        "description": "Превью изображений и видео",
        "command": None,
        "privileged": False,
    },
    {
        "id": "trash",
        "name": "Корзина",
        "path": os.path.expanduser("~/.local/share/Trash"),
        "description": "Удалённые файлы, которые ещё занимают место",
        "command": None,
        "privileged": False,
    },
]


class Cleaner(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Cleaner", "Очистка системы", 880, 680, "mvs-cleaner")

        self.log = ui.LogView(180)
        self.total = ui.label("—", "mvs-big")
        self.rows = []

        box = Gtk.ListBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)

        for target in TARGETS:
            check = Gtk.CheckButton()
            check.set_active(target["id"] in ("cache", "thumb", "trash"))
            size = ui.label("…", "mvs-subtle")
            target["size_label"] = size
            target["check"] = check
            self.rows.append(target)

            line = ui.row(target["name"], target["description"], size, check)
            box.add(line)

        action_row = ui.hbox(10)
        action_row.pack_start(ui.button("Оценить заново", self.refresh), False, False, 0)
        action_row.pack_start(
            ui.button("Очистить выбранное", self.clean, "mvs-button accent"), False, False, 0
        )

        page = ui.page(
            ui.h1("MVS Cleaner"),
            ui.subtle("Удаляет только кэш, журналы и корзину. Личные файлы не затрагиваются."),
            ui.card(
                ui.h2("Что можно очистить"),
                box,
                ui.label("", "mvs-sep"),
                ui.row("Всего выбрано", None, self.total),
            ),
            ui.card(ui.h2("Действия"), action_row),
            ui.card(ui.h2("Журнал"), self.log),
        )
        self.add_page("cleaner", "Очистка", "user-trash-full", page)

        for target in self.rows:
            target["check"].connect("toggled", lambda _c: self.update_total())

        self.refresh()

    def refresh(self, _button=None):
        for target in self.rows:
            size = dir_size(target["path"]) if os.path.exists(target["path"]) else 0
            target["size"] = size
            target["size_label"].set_text(ui.human_bytes(size) if size else "пусто")
        self.update_total()

    def update_total(self):
        total = 0
        for target in self.rows:
            if target["check"].get_active():
                total += target.get("size", 0)
        self.total.set_text(ui.human_bytes(total))

    def clean(self, _button):
        selected = [t for t in self.rows if t["check"].get_active()]
        if not selected:
            ui.info(self, "Отметьте, что нужно очистить.")
            return
        if not ui.confirm(
            self,
            "Очистить %d категорий? Это необратимо.\n\nЛичные документы не пострадают."
            % len(selected),
        ):
            return

        freed = 0
        for target in selected:
            self.log.append("▸ %s" % target["name"])
            if target["command"] is not None:
                command = (
                    ui.priv_prefix() + target["command"]
                    if target["privileged"]
                    else target["command"]
                )
                code, out_text, err = ui.run(command, timeout=120)
                self.log.append((out_text or err or "").strip()[:500])
                if code != 0:
                    self.log.append("  ошибка, код %d" % code)
            else:
                if os.path.exists(target["path"]):
                    freed += clear_directory(target["path"])
            self.log.append("  готово")

        self.log.append("Освобождено вручную: %s" % ui.human_bytes(freed))
        self.refresh()
        ui.notify("MVS Cleaner: очистка завершена")


def main():
    Cleaner().run()


if __name__ == "__main__":
    main()
