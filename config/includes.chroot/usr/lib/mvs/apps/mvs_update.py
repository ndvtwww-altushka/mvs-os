#!/usr/bin/env python3
"""MVS Update — проверка и установка обновлений из репозиториев Debian."""

import re
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


class Update(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Update", "Обновления MVS OS", 900, 640, "mvs-update")

        self.log = ui.LogView(300)
        self.count = ui.label("—", "mvs-big")
        self.state = ui.subtle("Проверяем список обновлений…")
        self.install_button = ui.button(
            "Установить обновления", self.upgrade, "mvs-button accent"
        )
        self.install_button.set_sensitive(False)

        buttons = ui.hbox(10)
        buttons.pack_start(ui.button("Проверить обновления", self.check), False, False, 0)
        buttons.pack_start(self.install_button, False, False, 0)

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

        self.check()

    def check(self, _button=None):
        self.state.set_text("Загрузка индексов пакетов…")
        self.install_button.set_sensitive(False)
        ui.stream(ui.priv_prefix() + ["apt-get", "update"], self.log, self.after_update)

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
        code, text, _err = ui.run(["apt", "list", "--upgradable"], timeout=60)
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

    def upgrade(self, _button):
        if not ui.confirm(
            self,
            "Установить все обновления?\n\nВо время установки лучше не выключать компьютер.",
        ):
            return
        self.state.set_text("Установка обновлений…")
        ui.stream(
            ui.priv_prefix() + ["apt-get", "dist-upgrade", "-y"],
            self.log,
            self.after_upgrade,
        )

    def after_upgrade(self, code):
        if code == 0:
            self.state.set_text("Обновления установлены.")
            ui.notify("MVS Update: обновления установлены")
            self.check()
        else:
            self.state.set_text("Ошибка установки. Смотрите журнал.")


def main():
    Update().run()


if __name__ == "__main__":
    main()
