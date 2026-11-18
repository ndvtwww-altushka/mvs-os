#!/usr/bin/env python3
"""MVS Store — установка и удаление программ через apt.

Никакого фиктивного каталога: поиск идёт по индексам Debian, установка — через
подписанные репозитории и apt-get. Пакеты, которых нет в репозиториях,
честно пропускаются с пояснением. Наборы с отдельным репозиторием не
притворяются устанавливаемыми: Store объясняет, что источник нужно
подключить вручную.
"""

import json
import os
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

PRESETS = "/usr/share/mvs/store/presets.json"

_INSTALLED = None


def installed_packages(refresh=False):
    """Один вызов dpkg-query вместо сотни: список нужен и наборам, и поиску."""
    global _INSTALLED
    if _INSTALLED is not None and not refresh:
        return _INSTALLED
    names = set()
    code, text, _err = ui.run(
        ["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${Package}\n"], timeout=20
    )
    if code == 0:
        for line in text.splitlines():
            status, _, name = line.partition("\t")
            if status.startswith("ii") and name.strip():
                names.add(name.strip())
    _INSTALLED = names
    return _INSTALLED


def invalidate_installed():
    global _INSTALLED
    _INSTALLED = None


def package_installed(name):
    return name in installed_packages()


def package_available(name):
    return ui.run(["apt-cache", "show", name], timeout=15)[0] == 0


def indexes_ready():
    """Есть ли разобранные индексы apt.

    В bookworm apt хранит списки сжатыми: ..._Packages.lz4, а не просто
    Packages. Проверка только по имени «Packages» навсегда оставляла Store
    с сообщением «индексы не загружены» даже после apt-get update.
    """
    suffixes = (
        "_Packages",
        "_Packages.lz4",
        "_Packages.gz",
        "_Packages.xz",
        "_Packages.bz2",
    )
    try:
        for root, _dirs, files in os.walk("/var/lib/apt/lists"):
            if os.path.basename(root) == "partial":
                continue
            if any(entry.endswith(suffixes) for entry in files):
                return True
    except OSError:
        pass
    return False


def load_sets():
    try:
        with open(PRESETS, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        sets = data.get("sets", [])
        return sets if isinstance(sets, list) else []
    except (OSError, ValueError):
        return []


class Store(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Store", "Программы для MVS OS", 1000, 720, "mvs-store")

        self.log = ui.LogView(460)
        self.status = ui.subtle("")
        self.sets_status = ui.subtle("")
        self.status_labels = [self.status, self.sets_status]

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Имя программы или описание, например firefox")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", lambda _w: self.search())

        self.results = Gtk.ListBox()
        self.results.set_selection_mode(Gtk.SelectionMode.NONE)
        self.results.add(ui.subtle("Введите название программы и нажмите «Найти»."))

        self.sets_box = Gtk.ListBox()
        self.sets_box.set_selection_mode(Gtk.SelectionMode.NONE)

        search_row = ui.hbox(10)
        search_row.pack_start(self.search_entry, True, True, 0)
        search_row.pack_start(
            ui.button("Найти", lambda _b: self.search(), "mvs-button accent"), False, False, 0
        )

        sets_row = ui.hbox(10)
        sets_row.pack_start(
            ui.button("Обновить индексы", lambda _b: self.update_indexes()), False, False, 0
        )

        search_actions = ui.hbox(10)
        search_actions.pack_start(
            ui.button("Обновить индексы", lambda _b: self.update_indexes()), False, False, 0
        )

        sets_page = ui.page(
            ui.h1("MVS Store"),
            ui.subtle(
                "Наборы связанных программ. Установка идёт из подписанных "
                "репозиториев Debian и требует интернета."
            ),
            ui.card(
                ui.h2("Наборы"),
                self.sets_status,
                sets_row,
                self.sets_box,
            ),
        )

        search_page = ui.page(
            ui.h1("Поиск программ"),
            ui.subtle("Поиск по именам пакетов в подключённых репозиториях."),
            ui.card(
                ui.h2("Что установить?"),
                search_row,
                search_actions,
                self.status,
            ),
            ui.card(
                ui.h2("Результаты"),
                ui.scrolled(self.results, 360),
            ),
        )

        log_page = ui.page(
            ui.h1("Журнал"),
            ui.subtle(
                "Здесь видно, что именно делает apt. Ошибки не скрываются."
            ),
            ui.card(self.log),
        )

        self.add_page("sets", "Наборы", "system-software-install", sets_page)
        self.add_page("search", "Поиск", "system-search", search_page)
        self.add_page("log", "Журнал", "text-x-generic", log_page)
        self.select("sets")

        self.set_status(self.indexes_text())
        self.load_installed()

    # -- статус -------------------------------------------------------------

    def indexes_text(self):
        if indexes_ready():
            return "Индексы пакетов готовы."
        return "Индексы пакетов не загружены. Нажмите «Обновить индексы»."

    def set_status(self, text):
        for label in self.status_labels:
            label.set_text(text)

    def load_installed(self, done_text=None):
        """dpkg-query в фоне: первый запуск не должен подвешивать окно."""
        self._installed_done_text = done_text
        self.set_status("Читаем список установленных программ…")
        ui.background(self.read_installed, on_done=self.after_installed)

    def read_installed(self):
        invalidate_installed()
        return installed_packages(refresh=True)

    def after_installed(self, result):
        if isinstance(result, Exception):
            self.set_status("Не удалось прочитать список программ: %s" % result)
            self.fill_sets()
            return
        self.set_status(getattr(self, "_installed_done_text", None)
                        or self.indexes_text())
        self.fill_sets()

    # -- данные -------------------------------------------------------------

    def fill_sets(self):
        for child in self.sets_box.get_children():
            self.sets_box.remove(child)

        for item in load_sets():
            packages = [name for name in item.get("packages", []) if isinstance(name, str)]
            if not packages:
                continue

            installed = [name for name in packages if package_installed(name)]
            repository = item.get("repository")

            if repository:
                if len(installed) == len(packages):
                    action = ui.button(
                        "Удалить",
                        lambda _b, group=item: self.remove_group(group),
                        "mvs-button danger",
                    )
                    suffix = ui.label("установлено", "mvs-subtle")
                else:
                    action = ui.button(
                        "Как подключить",
                        lambda _b, group=item: self.explain_repository(group),
                        "mvs-button",
                    )
                    suffix = ui.label("внешний репозиторий", "mvs-subtle")
            else:
                action = ui.button(
                    "Установить",
                    lambda _b, group=item: self.install_group(group),
                    "mvs-button accent",
                )
                suffix = ui.label(
                    "%d из %d" % (len(installed), len(packages)), "mvs-subtle"
                )

            self.sets_box.add(
                ui.row(
                    item.get("name", item.get("id", "набор")),
                    item.get("description", ""),
                    action,
                    suffix,
                )
            )
        self.sets_box.show_all()

    # -- наборы -------------------------------------------------------------

    def explain_repository(self, item):
        source = str(item.get("repository", ""))
        if source == "vscode":
            source = "репозиторий Microsoft для VS Code"
        else:
            source = "репозиторий «%s»" % source
        packages = [name for name in item.get("packages", []) if isinstance(name, str)]
        ui.info(
            self,
            "Набор «%s» ставится из отдельного источника: %s.\n\n"
            "MVS OS не подключает сторонние репозитории сама: это меняет "
            "список доверенных источников apt. Добавьте его вручную по "
            "инструкции производителя, обновите индексы — и пакет появится "
            "в поиске.\n\nПакеты: %s"
            % (item.get("name", ""), source, ", ".join(packages)),
        )

    def install_group(self, item):
        if item.get("repository"):
            self.explain_repository(item)
            return

        packages = [name for name in item.get("packages", []) if isinstance(name, str)]
        if not packages:
            ui.error(self, "В наборе нет пакетов.")
            return
        if not indexes_ready():
            ui.info(self, "Сначала загрузите индексы пакетов: кнопка «Обновить индексы».")
            return

        self.set_status("Проверяем пакеты набора «%s»…" % item.get("name", ""))
        ui.background(
            self.group_available,
            packages,
            on_done=lambda result: self.confirm_group(item, packages, result),
        )

    def group_available(self, packages):
        return [name for name in packages if package_available(name)]

    def confirm_group(self, item, packages, result):
        if isinstance(result, Exception):
            ui.error(self, "Не удалось проверить пакеты:\n%s" % result)
            self.set_status("Проверка не удалась.")
            return
        available = result
        missing = [name for name in packages if name not in available]
        if not available:
            ui.error(
                self,
                "Ни один пакет набора не найден в подключённых репозиториях:\n%s"
                % ", ".join(missing),
            )
            self.set_status("Пакеты набора не найдены.")
            return

        if missing:
            self.log.append("Нет в репозиториях: %s" % ", ".join(missing))
        if not ui.confirm(
            self,
            "Установить «%s»?\n\nПакеты: %s\n\nБудет скачано и установлено %d программ."
            % (item.get("name", ""), ", ".join(available), len(available)),
        ):
            self.set_status("Установка отменена.")
            return

        self.set_status("Установка набора «%s»…" % item.get("name", ""))
        self.select("log")
        ui.apt_stream(["install"] + available, self.log, self.after_change)

    def remove_group(self, item):
        packages = [name for name in item.get("packages", []) if isinstance(name, str)]
        if not packages:
            return
        if not ui.confirm(
            self,
            "Удалить набор «%s»?\n\nПакеты: %s\n\nВместе с ними могут "
            "удалиться зависимости."
            % (item.get("name", ""), ", ".join(packages)),
        ):
            return
        self.set_status("Удаление набора «%s»…" % item.get("name", ""))
        self.select("log")
        ui.apt_stream(["remove"] + packages, self.log, self.after_change)

    # -- поиск --------------------------------------------------------------

    def search(self):
        term = self.search_entry.get_text().strip()
        if not indexes_ready():
            ui.info(self, "Сначала загрузите индексы пакетов: кнопка «Обновить индексы».")
            return
        if len(term) < 2:
            self.show_results_hint("Введите хотя бы два символа.")
            return
        self.set_status("Ищем «%s»…" % term)
        ui.background(self.search_worker, term, on_done=self.apply_search)

    def search_worker(self, term):
        return ui.run(
            ["apt-cache", "search", "--names-only", term],
            timeout=90,
            env=dict(os.environ, **ui.APT_ENV),
        )

    def apply_search(self, result):
        if isinstance(result, Exception):
            self.show_results_hint("Поиск не удался: %s" % result)
            return
        code, text, _err = result
        for child in self.results.get_children():
            self.results.remove(child)

        if code != 0:
            self.results.add(ui.subtle("apt-cache не ответил. Обновите индексы."))
            self.results.show_all()
            self.set_status("Поиск не удался.")
            return

        count = 0
        for line in text.splitlines():
            name, _, description = line.partition(" - ")
            name = name.strip()
            if not name or " " in name:
                continue
            count += 1
            if count > 40:
                break
            installed = package_installed(name)
            if installed:
                action = ui.button(
                    "Удалить",
                    lambda _b, pkg=name: self.remove_package(pkg),
                    "mvs-button danger",
                )
                badge = ui.label("установлено", "mvs-subtle")
            else:
                action = ui.button(
                    "Установить",
                    lambda _b, pkg=name: self.install_package(pkg),
                    "mvs-button accent",
                )
                badge = None
            self.results.add(ui.row(name, description.strip()[:110], action, badge))

        if count == 0:
            self.results.add(ui.subtle("Ничего не найдено по запросу «%s»."
                                       % self.search_entry.get_text().strip()))
        self.results.show_all()
        self.set_status("Найдено: %d (показаны первые 40)." % count)

    def show_results_hint(self, text):
        for child in self.results.get_children():
            self.results.remove(child)
        self.results.add(ui.subtle(text))
        self.results.show_all()

    # -- действия -----------------------------------------------------------

    def update_indexes(self):
        self.set_status("Загрузка индексов пакетов…")
        self.select("log")
        ui.apt_stream(["update"], self.log, self.after_indexes)

    def after_indexes(self, code):
        if code == 0:
            self.set_status("Индексы обновлены.")
            self.fill_sets()
            if self.search_entry.get_text().strip():
                self.search()
        else:
            self.set_status("Не удалось обновить индексы. Проверьте интернет.")

    def install_package(self, name, auto=False):
        self.set_status("Установка %s…" % name)
        self.select("log")
        ui.apt_stream(["install", name], self.log, self.after_change)

    def remove_package(self, name):
        if not ui.confirm(
            self,
            "Удалить %s?\n\nВместе с программой могут удалиться её зависимости." % name,
        ):
            return
        self.set_status("Удаление %s…" % name)
        self.select("log")
        ui.apt_stream(["remove", name], self.log, self.after_change)

    def after_change(self, code):
        if code == 0:
            self.set_status("Готово.")
            ui.notify("MVS Store: изменения применены")
        else:
            self.set_status("Команда завершилась с ошибкой, смотрите журнал.")
        self.load_installed("Готово.")
        if self.search_entry.get_text().strip():
            self.search()


def main():
    Store().run()


if __name__ == "__main__":
    main()
