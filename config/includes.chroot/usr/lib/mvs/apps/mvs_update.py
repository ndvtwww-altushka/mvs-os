#!/usr/bin/env python3
"""MVS Update — проверка и установка обновлений из репозиториев Debian.

Все длинные команды (apt-get update, apt list, снимок btrfs) выполняются
в фоне. apt запускается неинтерактивно и сохраняет уже изменённые
конфигурационные файлы: --force-confdef --force-confold.
"""

import os
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

SNAPSHOT = "/usr/local/sbin/mvs-snapshot"


def root_filesystem():
    """Тип файловой системы корня: btrfs включает снимки и откат."""
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "/":
                    return parts[2]
    except OSError:
        pass
    return ""


def snapshots_supported():
    return os.path.exists(SNAPSHOT) and root_filesystem() == "btrfs"


class Update(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Update", "Обновления MVS OS", 900, 700, "mvs-update")

        self.log = ui.LogView(300)
        self.count = ui.label("—", "mvs-big")
        self.state = ui.subtle("Проверяем список обновлений…")
        self.snapshot_state = ui.subtle("Проверяем снимки…")
        self.install_button = ui.button(
            "Установить обновления", self.upgrade, "mvs-button accent"
        )
        self.install_button.set_sensitive(False)
        self.snapshot_button = ui.button("Создать снимок сейчас", self.create_snapshot)

        buttons = ui.hbox(10)
        buttons.pack_start(ui.button("Проверить обновления", self.check), False, False, 0)
        buttons.pack_start(self.install_button, False, False, 0)

        snapshot_row = ui.hbox(10)
        snapshot_row.pack_start(self.snapshot_state, True, True, 0)
        snapshot_row.pack_start(self.snapshot_button, False, False, 0)

        page = ui.page(
            ui.h1("MVS Update"),
            ui.subtle(
                "Обновления ставятся из подписанных репозиториев Debian. "
                "Подписи проверяет apt, отключить их нельзя."
            ),
            ui.card(
                ui.row("Доступно обновлений", "Пакеты, готовые к обновлению", self.count),
                self.state,
                buttons,
            ),
            ui.card(
                ui.h2("Снимок перед обновлением"),
                ui.subtle(
                    "Если система установлена на btrfs, перед установкой "
                    "автоматически создаётся снимок. Его можно выбрать "
                    "в меню загрузчика GRUB, если обновление что-то сломает.",
                    wrap=True,
                ),
                snapshot_row,
            ),
            ui.card(ui.h2("Журнал"), self.log),
            ui.card(
                ui.h2("Что важно знать"),
                ui.subtle(
                    "В Live-режиме обновления живут до перезагрузки. После установки на диск "
                    "обновления сохраняются постоянно. Для обновления нужно ~1 ГБ свободного места.",
                    wrap=True,
                ),
            ),
        )
        self.add_page("update", "Обновления", "software-update-available", page)

        self.refresh_snapshots()
        self.check()

    # -- проверка обновлений ------------------------------------------------

    def check(self, _button=None):
        self.state.set_text("Загрузка индексов пакетов…")
        self.install_button.set_sensitive(False)
        ui.apt_stream(["update"], self.log, self.after_update)

    def after_update(self, code):
        # apt-get update мог не достучаться до зеркала. В этом случае нельзя
        # показывать «обновлений нет»: список просто остался старым.
        if code != 0:
            self.count.set_text("—")
            self.state.set_text(
                "Не удалось обновить индексы пакетов. Проверьте интернет и журнал."
            )
            self.install_button.set_sensitive(False)
            return
        self.state.set_text("Читаем список обновлений…")
        ui.background(self.read_upgradable, on_done=self.apply_upgradable)

    def read_upgradable(self):
        code, text, err = ui.run(
            ["apt", "list", "--upgradable"],
            timeout=180,
            env=dict(os.environ, **ui.APT_ENV),
        )
        return code, text, err

    def apply_upgradable(self, result):
        if isinstance(result, Exception):
            self.count.set_text("—")
            self.state.set_text("Не удалось получить список обновлений: %s" % result)
            self.install_button.set_sensitive(False)
            return
        code, text, _err = result
        if code != 0:
            self.count.set_text("—")
            self.state.set_text("Не удалось получить список обновлений.")
            self.install_button.set_sensitive(False)
            return
        packages = []
        for line in text.splitlines():
            if "upgradable" in line:
                packages.append(line.split("/")[0].strip())
        self.count.set_text(str(len(packages)))
        if packages:
            self.state.set_text("Готово к установке: %s" % ", ".join(packages[:6]))
            self.install_button.set_sensitive(True)
        else:
            self.state.set_text("Обновлений нет — система актуальна.")
            self.install_button.set_sensitive(False)

    # -- снимки btrfs -------------------------------------------------------

    def refresh_snapshots(self):
        ui.background(self.read_snapshots, on_done=self.apply_snapshots)

    def read_snapshots(self):
        if not os.path.exists(SNAPSHOT):
            return "missing", ""
        if root_filesystem() != "btrfs":
            return "not-btrfs", root_filesystem()
        code, text, err = ui.run(
            ui.priv_prefix() + [SNAPSHOT, "list", "--short"],
            timeout=60,
        )
        return ("ok" if code == 0 else "error"), (text or err).strip()

    def apply_snapshots(self, result):
        if isinstance(result, Exception):
            self.snapshot_state.set_text("Снимки: ошибка — %s" % result)
            self.snapshot_button.set_sensitive(False)
            return
        status, detail = result
        if status == "missing":
            self.snapshot_state.set_text(
                "Снимки недоступны: в этой сборке нет mvs-snapshot."
            )
            self.snapshot_button.set_sensitive(False)
        elif status == "not-btrfs":
            self.snapshot_state.set_text(
                "Снимки недоступны: корень на %s, нужен btrfs."
                % (detail or "другой файловой системе")
            )
            self.snapshot_button.set_sensitive(False)
        elif status == "ok":
            lines = [line for line in detail.splitlines() if line.strip()]
            if lines:
                # list --short отдаёт новые первыми.
                self.snapshot_state.set_text(
                    "Снимков: %d. Последний: %s" % (len(lines), lines[0])
                )
            else:
                self.snapshot_state.set_text("Снимков пока нет.")
            self.snapshot_button.set_sensitive(True)
        else:
            self.snapshot_state.set_text("Не удалось прочитать список снимков.")
            self.snapshot_button.set_sensitive(True)

    def create_snapshot(self, _button=None):
        if not snapshots_supported():
            ui.info(self, "Снимки работают только на btrfs после установки на диск.")
            return
        self.snapshot_button.set_sensitive(False)
        self.snapshot_state.set_text("Создаём снимок…")
        ui.background(self.make_snapshot, "manual", on_done=self.after_snapshot)

    def make_snapshot(self, reason):
        code, text, err = ui.run(
            ui.priv_prefix() + [SNAPSHOT, "create", reason],
            timeout=300,
        )
        return code, (text or err).strip()

    def after_snapshot(self, result):
        self.snapshot_button.set_sensitive(True)
        if isinstance(result, Exception):
            self.snapshot_state.set_text("Снимок не создан: %s" % result)
            return
        code, detail = result
        if code == 0:
            self.snapshot_state.set_text("Снимок создан: %s" % (detail or "готово"))
            self.log.append("Снимок btrfs: %s" % (detail or "готово"))
        else:
            self.snapshot_state.set_text("Снимок не создан, смотрите журнал.")
            self.log.append("Ошибка снимка: %s" % (detail or code))

    # -- установка ----------------------------------------------------------

    def upgrade(self, _button):
        if not ui.confirm(
            self,
            "Установить все обновления?\n\nВо время установки лучше не выключать компьютер.",
        ):
            return
        self.install_button.set_sensitive(False)
        self.state.set_text("Готовим снимок и установку…")
        ui.background(self.prepare_upgrade, on_done=self.after_prepare)

    def prepare_upgrade(self):
        """Снимок делается до apt. Ошибка снимка не блокирует обновление."""
        if not snapshots_supported():
            ui.idle_once(self.log.append, "Снимок не создан: корень не на btrfs.")
            return None
        ui.idle_once(self.log.append, "Создаём снимок перед обновлением…")
        code, text, err = ui.run(
            ui.priv_prefix() + [SNAPSHOT, "create", "before-update"],
            timeout=300,
        )
        detail = (text or err).strip()
        ui.idle_once(
            self.log.append,
            ("Снимок: %s" % detail) if code == 0 else ("Снимок не создан: %s" % detail),
        )
        return code, detail

    def after_prepare(self, result):
        if isinstance(result, Exception):
            self.log.append("Снимок не создан: %s" % result)
        self.state.set_text("Установка обновлений…")
        ui.apt_stream(["dist-upgrade"], self.log, self.after_upgrade)

    def after_upgrade(self, code):
        self.install_button.set_sensitive(True)
        if code == 0:
            self.state.set_text("Обновления установлены.")
            ui.notify("MVS Update: обновления установлены")
            self.check()
        else:
            self.state.set_text(
                "Ошибка установки. Смотрите журнал; при снимке btrfs "
                "можно загрузиться в него из меню GRUB."
            )
        self.refresh_snapshots()


def main():
    Update().run()


if __name__ == "__main__":
    main()
