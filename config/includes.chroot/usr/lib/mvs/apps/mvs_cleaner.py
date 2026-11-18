#!/usr/bin/env python3
"""MVS Cleaner — безопасная очистка кэшей, журналов и корзины.

Размеры считаются в фоне (os.walk, без внешнего du), очистка тоже идёт
в отдельном потоке: окно не замирает и показывает журнал по шагам.
"""

import os
import shutil
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


def dir_size(path):
    """Размер папки без du: не блокирует интерфейс и терпит ошибки чтения."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _exc: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def clear_directory(path):
    """Удаляет содержимое папки, саму папку оставляет. Возвращает байты."""
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
        self.busy = False

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

        self.refresh_button = ui.button("Оценить заново", self.refresh)
        self.clean_button = ui.button(
            "Очистить выбранное", self.clean, "mvs-button accent"
        )
        action_row = ui.hbox(10)
        action_row.pack_start(self.refresh_button, False, False, 0)
        action_row.pack_start(self.clean_button, False, False, 0)

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

    def set_busy(self, busy):
        self.busy = busy
        self.clean_button.set_sensitive(not busy)
        self.refresh_button.set_sensitive(not busy)

    def refresh(self, _button=None):
        if self.busy:
            return
        for target in self.rows:
            target["size_label"].set_text("…")
        self.total.set_text("…")
        paths = {target["id"]: target["path"] for target in self.rows}
        ui.background(self.measure, paths, on_done=self.apply_sizes)

    def measure(self, paths):
        result = {}
        for key, path in paths.items():
            result[key] = dir_size(path) if os.path.exists(path) else 0
        return result

    def apply_sizes(self, result):
        if isinstance(result, Exception):
            self.total.set_text("—")
            self.log.append("Не удалось посчитать размеры: %s" % result)
            return
        for target in self.rows:
            size = result.get(target["id"], 0)
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
        if self.busy:
            return
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

        self.set_busy(True)
        self.log.clear()
        ui.background(self.clean_worker, selected, on_done=self.after_clean)

    def clean_worker(self, selected):
        freed = 0
        errors = []
        for target in selected:
            ui.idle_once(self.log.append, "▸ %s" % target["name"])
            if target["command"] is not None:
                command = target["command"]
                if target["privileged"]:
                    command = ui.priv_prefix() + command
                code, out_text, err = ui.run(command, timeout=300)
                message = (out_text or err or "").strip()
                if message:
                    ui.idle_once(self.log.append, message[:500])
                if code != 0:
                    errors.append("%s: код %d" % (target["name"], code))
                    ui.idle_once(self.log.append, "  ошибка, код %d" % code)
            elif os.path.exists(target["path"]):
                freed += clear_directory(target["path"])
            ui.idle_once(self.log.append, "  готово")
        return freed, errors

    def after_clean(self, result):
        self.set_busy(False)
        if isinstance(result, Exception):
            self.log.append("Очистка прервана: %s" % result)
            ui.error(self, "Очистка прервана:\n%s" % result)
            return
        freed, errors = result
        self.log.append("Освобождено вручную: %s" % ui.human_bytes(freed))
        if errors:
            self.log.append("Не всё удалось: %s" % "; ".join(errors))
        else:
            ui.notify("MVS Cleaner: очистка завершена")
        self.refresh()


def main():
    Cleaner().run()


if __name__ == "__main__":
    main()
