#!/usr/bin/env python3
"""MVS Backup — резервное копирование и восстановление папок пользователя.

Архив собирается стандартным tarfile, а не внешним tar: код возврата не
путается с предупреждениями, а восстановление проходит через
tarfile.data_filter и не может выйти за пределы выбранной папки.
"""

import datetime
import os
import stat
import sys
import tarfile

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

HOME = os.path.expanduser("~")

# key, XDG-имя, английское имя по умолчанию, подпись
SOURCE_SPECS = [
    ("documents", "DOCUMENTS", "Documents", "Документы"),
    ("pictures", "PICTURES", "Pictures", "Изображения"),
    ("downloads", "DOWNLOAD", "Downloads", "Загрузки"),
    ("desktop", "DESKTOP", "Desktop", "Рабочий стол"),
    ("videos", "VIDEOS", "Videos", "Видео"),
    ("music", "MUSIC", "Music", "Музыка"),
    ("mvs", None, ".config/mvs", "Настройки MVS"),
]


def resolve_source(key, xdg_key, fallback):
    """Настоящий путь папки с учётом локали.

    xdg-user-dir читает ~/.config/user-dirs.dirs, где у русской учётной
    записи записано «$HOME/Документы», а не «$HOME/Documents». Английские
    имена из старой версии на такой системе просто не находились.
    """
    if key == "mvs":
        return ui.CONFIG_DIR
    if xdg_key and ui.has("xdg-user-dir"):
        path = ui.out(["xdg-user-dir", xdg_key]).strip()
        if path and path != HOME and os.path.isdir(path):
            return path
    return os.path.join(HOME, fallback)


def dir_size(path):
    """Размер папки без внешнего du: не блокирует интерфейс."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _exc: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def archive_name(path):
    """Путь элемента внутри архива — относительно дома, без ведущего /."""
    relative = os.path.relpath(path, HOME)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return os.path.basename(path)
    return relative


def add_to_archive(archive, path, arcname, skip, stats):
    """Добавляет папку по одному элементу и не рвётся на нечитаемом файле.

    tarfile.add(recursive=True) останавливается на первом же файле без прав
    чтения и оставляет недописанный архив. Здесь такой файл пропускается
    с записью в журнал, остальные копируются.
    """
    if os.path.abspath(path) in skip:
        return
    try:
        info = os.lstat(path)
    except OSError as exc:
        stats["skipped"] += 1
        stats["notes"].append("%s: %s" % (arcname, exc.strerror or exc))
        return

    try:
        if stat.S_ISDIR(info.st_mode):
            archive.add(path, arcname=arcname, recursive=False)
            try:
                names = sorted(os.listdir(path))
            except OSError as exc:
                stats["skipped"] += 1
                stats["notes"].append("%s: %s" % (arcname, exc.strerror or exc))
                return
            for name in names:
                add_to_archive(
                    archive, os.path.join(path, name), arcname + "/" + name, skip, stats
                )
        elif stat.S_ISREG(info.st_mode):
            archive.add(path, arcname=arcname, recursive=False)
            stats["files"] += 1
        elif stat.S_ISLNK(info.st_mode):
            # Ссылка сохраняется как ссылка: её цель не читается.
            archive.add(path, arcname=arcname, recursive=False)
            stats["links"] += 1
        else:
            stats["skipped"] += 1
            stats["notes"].append("%s: не обычный файл" % arcname)
    except (OSError, tarfile.TarError) as exc:
        stats["skipped"] += 1
        stats["notes"].append("%s: %s" % (arcname, exc))


def restore_problem(member, root):
    """Почему элемент архива нельзя распаковывать. None — можно."""
    name = member.name.replace("\\", "/")
    if (
        not name
        or name.startswith("/")
        or name == ".."
        or name.startswith("../")
        or "/../" in name
    ):
        return "путь вне выбранной папки"

    target = os.path.realpath(os.path.join(root, name))
    if target != root and not target.startswith(root + os.sep):
        return "путь вне выбранной папки"

    if member.issym() or member.islnk():
        link = member.linkname.replace("\\", "/")
        if not link:
            return "пустая ссылка"
        if os.path.isabs(link):
            return "абсолютная ссылка"
        base = root if member.islnk() else os.path.dirname(target)
        resolved = os.path.realpath(os.path.join(base, link))
        if resolved != root and not resolved.startswith(root + os.sep):
            return "ссылка ведёт за пределы папки"
    elif member.isdev():
        return "устройство"
    elif member.isfifo():
        return "именованный канал"
    return None


class Backup(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Backup", "Копии и восстановление", 900, 700, "mvs-backup")

        self.log = ui.LogView(200)
        self.paths = {}
        self.checks = {}
        self.sizes = {}
        self.size_bytes = {}
        self.total = ui.label("—", "mvs-big")

        sources_box = Gtk.ListBox()
        sources_box.set_selection_mode(Gtk.SelectionMode.NONE)
        for key, xdg_key, fallback, title in SOURCE_SPECS:
            path = resolve_source(key, xdg_key, fallback)
            check = Gtk.CheckButton()
            check.set_active(key in ("documents", "pictures", "desktop", "mvs"))
            size = ui.label("…", "mvs-subtle")
            self.paths[key] = path
            self.checks[key] = check
            self.sizes[key] = size
            subtitle = os.path.relpath(path, HOME)
            sources_box.add(ui.row(title, subtitle, size, check))
            check.connect("toggled", lambda _c: self.update_total())

        stamp = datetime.date.today().isoformat()
        self.target = Gtk.Entry()
        self.target.set_text(os.path.join(HOME, "MVS-Backups", "mvs-backup-%s.tar.gz" % stamp))
        self.target.set_hexpand(True)

        target_row = ui.hbox(10)
        target_row.pack_start(self.target, True, True, 0)
        target_row.pack_start(ui.button("Обзор…", self.choose_target), False, False, 0)

        self.create_button = ui.button("Создать копию", self.create_backup, "mvs-button accent")
        self.restore_button = ui.button("Восстановить из архива…", self.restore_backup)

        page = ui.page(
            ui.h1("MVS Backup"),
            ui.subtle("Создаёт tar.gz с выбранными папками. Личные файлы не изменяются."),
            ui.card(
                ui.h2("Что копировать"),
                sources_box,
                ui.label("", "mvs-sep"),
                ui.row("Общий размер", None, self.total),
            ),
            ui.card(
                ui.h2("Куда сохранить"),
                target_row,
                self.create_button,
            ),
            ui.card(
                ui.h2("Восстановление"),
                ui.subtle(
                    "Архив распаковывается в выбранную папку. Существующие файлы могут быть заменены.",
                    wrap=True,
                ),
                self.restore_button,
            ),
            ui.card(ui.h2("Журнал"), self.log),
        )
        self.add_page("backup", "Резервные копии", "document-save", page)

        self.refresh()

    # -- размеры ------------------------------------------------------------

    def refresh(self):
        paths = dict(self.paths)
        self.total.set_text("…")

        def measure():
            return {
                key: (dir_size(path), os.path.isdir(path))
                for key, path in paths.items()
            }

        # du/os.walk по большой домашней папке не должен подвешивать окно.
        ui.background(measure, on_done=self.apply_sizes)

    def apply_sizes(self, result):
        if isinstance(result, Exception):
            self.total.set_text("—")
            self.log.append("Не удалось посчитать размеры: %s" % result)
            return
        self.size_bytes = {key: size for key, (size, _exists) in result.items()}
        for key, (size, exists) in result.items():
            self.sizes[key].set_text(ui.human_bytes(size) if exists else "нет папки")
        self.update_total()

    def update_total(self):
        total = sum(
            self.size_bytes.get(key, 0)
            for key, check in self.checks.items()
            if check.get_active()
        )
        self.total.set_text(ui.human_bytes(total))

    def selected_sources(self):
        return [self.paths[key] for key, check in self.checks.items() if check.get_active()]

    def set_busy(self, busy):
        self.create_button.set_sensitive(not busy)
        self.restore_button.set_sensitive(not busy)

    # -- создание -----------------------------------------------------------

    def choose_target(self, _button):
        dialog = Gtk.FileChooserDialog(
            title="Куда сохранить копию",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Сохранить", Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(os.path.basename(self.target.get_text() or "mvs-backup.tar.gz"))
        directory = os.path.dirname(self.target.get_text())
        if directory and os.path.isdir(directory):
            dialog.set_current_folder(directory)
        if dialog.run() == Gtk.ResponseType.OK:
            self.target.set_text(dialog.get_filename())
        dialog.destroy()

    def create_backup(self, _button):
        sources = self.selected_sources()
        if not sources:
            ui.info(self, "Отметьте хотя бы одну папку.")
            return
        raw = self.target.get_text().strip()
        if not raw:
            ui.info(self, "Укажите файл для копии.")
            return
        destination = os.path.abspath(os.path.expanduser(raw))
        if not destination.endswith((".tar.gz", ".tgz")):
            destination += ".tar.gz"
            self.target.set_text(destination)

        directory = os.path.dirname(destination)
        if directory:
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as exc:
                ui.error(self, "Не удалось создать папку: %s" % exc)
                return
        if os.path.exists(destination) and not ui.confirm(
            self, "Файл уже существует:\n%s\n\nЗаменить его?" % destination
        ):
            return

        temporary = destination + ".part"
        self.log.append("Создаём копию: %s" % ", ".join(archive_name(path) for path in sources))
        self.log.append("Файл: %s" % destination)
        self.set_busy(True)

        def worker():
            stats = {"files": 0, "links": 0, "skipped": 0, "notes": []}
            # Сам архив и его .part не должны попасть внутрь: иначе копия
            # растёт на глазах и в пределе забивает диск.
            skip = {os.path.abspath(destination), os.path.abspath(temporary)}
            try:
                with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                    for path in sources:
                        if os.path.isdir(path) or os.path.isfile(path):
                            add_to_archive(archive, path, archive_name(path), skip, stats)
                        else:
                            stats["skipped"] += 1
                            stats["notes"].append("%s: нет такого файла" % path)
                os.replace(temporary, destination)
                return stats
            except Exception as exc:  # noqa: BLE001 — ошибку покажет after_create
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                return {"error": exc}

        ui.background(worker, on_done=self.after_create)

    def after_create(self, result):
        self.set_busy(False)
        if isinstance(result, Exception):
            result = {"error": result}
        if result.get("error") is not None:
            error = result["error"]
            self.log.append("Ошибка создания копии: %s" % error)
            ui.error(self, "Не удалось создать копию:\n%s" % error)
            return

        self.log.append(
            "Копия готова: файлов %d, ссылок %d."
            % (result["files"], result["links"])
        )
        if result["skipped"]:
            self.log.append("Пропущено (нет прав чтения или особый файл): %d" % result["skipped"])
            for note in result["notes"][:12]:
                self.log.append("  %s" % note)
            ui.info(
                self,
                "Копия создана, но %d объектов пропущено — в журнале видно, какие.\n\n"
                "Обычно это чужие файлы без прав чтения или сокеты." % result["skipped"],
            )
        else:
            ui.notify("MVS Backup: копия создана")

    # -- восстановление -----------------------------------------------------

    def restore_backup(self, _button):
        dialog = Gtk.FileChooserDialog(
            title="Выберите архив",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Далее", Gtk.ResponseType.OK)
        filter_ = Gtk.FileFilter()
        filter_.set_name("Архивы MVS")
        for pattern in ("*.tar.gz", "*.tgz", "*.tar"):
            filter_.add_pattern(pattern)
        dialog.add_filter(filter_)
        if dialog.run() != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        archive = dialog.get_filename()
        dialog.destroy()

        chooser = Gtk.FileChooserDialog(
            title="Куда восстановить",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Восстановить", Gtk.ResponseType.OK)
        chooser.set_current_folder(HOME)
        if chooser.run() != Gtk.ResponseType.OK:
            chooser.destroy()
            return
        destination = chooser.get_filename()
        chooser.destroy()

        if not ui.confirm(
            self,
            "Распаковать архив\n%s\n\nв папку\n%s ?\n\nФайлы с теми же именами будут заменены."
            % (archive, destination),
        ):
            return

        try:
            os.makedirs(destination, exist_ok=True)
        except OSError as exc:
            ui.error(self, "Не удалось создать папку: %s" % exc)
            return

        self.log.append("Восстановление: %s" % archive)
        self.set_busy(True)

        def worker():
            root = os.path.realpath(destination)
            restored = 0
            skipped = []
            try:
                with tarfile.open(archive, "r:*") as source:
                    for member in source.getmembers():
                        # Симлинк на /etc/shadow или ../../ — это уже не
                        # «резервная копия», а попытка записи вне папки.
                        reason = restore_problem(member, root)
                        if reason:
                            skipped.append("%s — %s" % (member.name, reason))
                            continue
                        try:
                            if hasattr(tarfile, "data_filter"):
                                source.extract(member, destination, filter="data")
                            else:
                                source.extract(member, destination)
                            restored += 1
                        except (OSError, tarfile.TarError) as exc:
                            skipped.append("%s — %s" % (member.name, exc))
                return {"restored": restored, "skipped": skipped}
            except Exception as exc:  # noqa: BLE001 — ошибку покажет after_restore
                return {"error": exc, "restored": restored, "skipped": skipped}

        ui.background(worker, on_done=self.after_restore)

    def after_restore(self, result):
        self.set_busy(False)
        if isinstance(result, Exception):
            result = {"error": result, "restored": 0, "skipped": []}
        skipped = result.get("skipped") or []
        if result.get("error") is not None:
            self.log.append("Ошибка восстановления: %s" % result["error"])
            ui.error(self, "Не удалось восстановить архив:\n%s" % result["error"])
            return

        self.log.append("Распаковано элементов: %d." % result["restored"])
        if skipped:
            self.log.append("Пропущено из соображений безопасности: %d" % len(skipped))
            for note in skipped[:20]:
                self.log.append("  %s" % note)
            ui.info(
                self,
                "Архив распакован, но %d элементов пропущено:\n\n%s\n\n"
                "Так MVS Backup не даёт архиву записать файлы или ссылки "
                "за пределы выбранной папки." % (len(skipped), "\n".join(skipped[:8])),
            )
        else:
            ui.notify("MVS Backup: архив распакован")


def main():
    Backup().run()


if __name__ == "__main__":
    main()
