#!/usr/bin/env python3
"""MVS Welcome — приветствие при первом запуске.

Мастер из пяти шагов. Каждый шаг делает что-то настоящее: меняет тему,
показывает состояние сети, открывает обновления. Ничего не «имитируется».
"""

import os
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

DONE_MARKER = os.path.join(ui.CONFIG_DIR, "welcome-done")


def already_done():
    return os.path.exists(DONE_MARKER)


def network_state():
    """Короткое описание сети для шага «Интернет»."""
    if not ui.has("nmcli"):
        return "NetworkManager не найден", False
    state = ui.out(["nmcli", "-t", "-f", "STATE", "general"]).lower()
    name = ui.out(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
    if "connected" in state and name:
        return "Подключено: %s" % name.splitlines()[0], True
    return "Подключения нет", False


class Welcome(Gtk.Window):
    def __init__(self):
        super().__init__(title="MVS Welcome")
        self.set_default_size(820, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("mvs-welcome")
        ui.apply_theme()

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("MVS OS")
        header.set_subtitle("Первое знакомство")
        self.set_titlebar(header)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(160)

        self.stack.add_named(self.page_hello(), "hello")
        self.stack.add_named(self.page_theme(), "theme")
        self.stack.add_named(self.page_network(), "network")
        self.stack.add_named(self.page_updates(), "updates")
        self.stack.add_named(self.page_done(), "done")

        self.back = ui.button("Назад", self.go_back)
        self.next = ui.button("Далее", self.go_next, "mvs-button accent")
        self.skip = ui.button("Пропустить", self.finish)

        footer = ui.hbox(10)
        footer.set_margin_start(20)
        footer.set_margin_end(20)
        footer.set_margin_top(10)
        footer.set_margin_bottom(14)
        footer.pack_start(self.skip, False, False, 0)
        footer.pack_end(self.next, False, False, 0)
        footer.pack_end(self.back, False, False, 0)

        body = ui.vbox(0)
        body.pack_start(self.stack, True, True, 0)
        body.pack_start(Gtk.Separator(), False, False, 0)
        body.pack_start(footer, False, False, 0)
        self.add(body)

        self.order = ["hello", "theme", "network", "updates", "done"]
        self.stack.connect("notify::visible-child", lambda *_: self.sync_buttons())
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        self.sync_buttons()

    # -- шаги ---------------------------------------------------------------

    def page_hello(self):
        logo = Gtk.Image.new_from_file("/usr/share/pixmaps/mvs-logo.svg")
        logo.set_pixel_size(112)

        live = os.path.exists("/etc/sudoers.d/90-mvs-live")
        mode = "Live-режим" if live else "Установленная система"

        content = ui.vbox(14)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)
        content.pack_start(logo, False, False, 0)
        content.pack_start(ui.label("MVS OS %s «%s»" % (ui.VERSION, ui.CODENAME), "mvs-h1", xalign=0.5), False, False, 0)
        content.pack_start(
            ui.label(
                "Своя система на базе Debian 12: фирменный рабочий стол, "
                "центр управления и пять игр из коробки.",
                "mvs-subtle",
                xalign=0.5,
            ),
            False,
            False,
            0,
        )
        content.pack_start(ui.label(mode, "mvs-accent", xalign=0.5), False, False, 0)
        return ui.page(content)

    def page_theme(self):
        current = ui.theme_mode()

        dark = Gtk.RadioButton.new_with_label_from_widget(None, "Тёмная — Aurora Night")
        light = Gtk.RadioButton.new_with_label_from_widget(dark, "Светлая — Aurora Day")
        (light if current == "light" else dark).set_active(True)

        def on_toggle(widget, _pspec=None):
            if not widget.get_active():
                return
            mode = "light" if widget is light else "dark"
            ui.set_theme(mode)
            self.status_theme.set_text(
                "Применено: %s" % ("светлая" if mode == "light" else "тёмная")
            )

        dark.connect("toggled", on_toggle)
        light.connect("toggled", on_toggle)
        self.status_theme = ui.subtle("Тему можно сменить позже в Control Center → Оформление.")

        return ui.page(
            ui.h1("Оформление"),
            ui.subtle("Выберите тему. Она применится сразу ко всей системе."),
            ui.card(
                ui.h2("Тема MVS"),
                dark,
                light,
                self.status_theme,
            ),
            ui.card(
                ui.h2("Что входит"),
                ui.row("Обои", "Три фирменных фона, выбор в Control Center"),
                ui.label("", "mvs-sep"),
                ui.row("Иконки", "Набор MVS на базе Papirus"),
                ui.label("", "mvs-sep"),
                ui.row("Панель", "Нижняя панель с меню «Пуск» и часами"),
            ),
        )

    def page_network(self):
        text, online = network_state()
        badge = ui.label("онлайн" if online else "офлайн", "mvs-accent" if online else "danger")

        return ui.page(
            ui.h1("Интернет"),
            ui.subtle("Wi-Fi и Ethernet настраиваются через NetworkManager."),
            ui.card(
                ui.h2("Состояние"),
                ui.row("Сейчас", text, badge),
                ui.label("", "mvs-sep"),
                ui.button("Открыть настройки сети", lambda _b: self.spawn("mvs-control")),
                ui.subtle(
                    "Без сети система работает полностью, но Store и Update не смогут "
                    "скачать пакеты.",
                    wrap=True,
                ),
            ),
        )

    def page_updates(self):
        cards = [
            ui.card(
                ui.h2("Проверка обновлений"),
                ui.subtle(
                    "Откройте MVS Update: там видно список пакетов и кнопка установки. "
                    "В Live-режиме обновления живут до перезагрузки.",
                    wrap=True,
                ),
                ui.button("Открыть MVS Update", lambda _b: self.spawn("mvs-update")),
            ),
        ]

        # Карточка установки честна только на флешке: в установленной системе
        # установщика уже нет, и ярлык ведёт в никуда.
        if os.path.exists("/etc/sudoers.d/90-mvs-live"):
            cards.append(
                ui.card(
                    ui.h2("Установка на диск"),
                    ui.subtle(
                        "Установщик запускается с рабочего стола («Установить MVS OS»). "
                        "Он спросит диск, имя пользователя и пароль — без подтверждения "
                        "диск не изменяется.",
                        wrap=True,
                    ),
                    ui.button("Запустить установщик", lambda _b: self.spawn("mvs-install")),
                )
            )

        return ui.page(
            ui.h1("Обновления"),
            ui.subtle("Обновления ставятся из подписанных репозиториев Debian."),
            *cards,
        )

    def page_done(self):
        self.open_about = Gtk.CheckButton(label="Показать сведения о системе после закрытия")
        self.open_about.set_active(False)

        return ui.page(
            ui.h1("Готово"),
            ui.subtle("Всё настроено. Мастер больше не появится при входе."),
            ui.card(
                ui.h2("Что дальше"),
                ui.row("Приложения", "MVS Hub в меню «Пуск» — там все программы"),
                ui.label("", "mvs-sep"),
                ui.row("Настройки", "Control Center: экран, звук, сеть, безопасность"),
                ui.label("", "mvs-sep"),
                ui.row("Помощь", "MVS About → сведения о системе"),
                self.open_about,
            ),
            ui.card(
                ui.h2("Права"),
                ui.subtle(
                    "В Live-режиме административные действия идут без пароля, чтобы "
                    "систему можно было попробовать. После установки на диск у "
                    "пользователя свой пароль и обычные правила sudo.",
                    wrap=True,
                ),
            ),
        )

    # -- навигация ----------------------------------------------------------

    def current_key(self):
        return self.stack.get_visible_child_name()

    def index(self):
        try:
            return self.order.index(self.current_key())
        except ValueError:
            return 0

    def sync_buttons(self):
        position = self.index()
        self.back.set_sensitive(position > 0)
        self.next.set_label("Завершить" if position >= len(self.order) - 1 else "Далее")
        self.skip.set_visible(position < len(self.order) - 1)

    def go_back(self, _button=None):
        position = self.index()
        if position > 0:
            self.stack.set_visible_child_name(self.order[position - 1])

    def go_next(self, _button=None):
        position = self.index()
        if position >= len(self.order) - 1:
            self.finish()
            return
        self.stack.set_visible_child_name(self.order[position + 1])

    def finish(self, _button=None):
        try:
            os.makedirs(ui.CONFIG_DIR, exist_ok=True)
            with open(DONE_MARKER, "w", encoding="utf-8") as handle:
                handle.write("%s\n" % ui.VERSION)
        except OSError as exc:
            ui.error(self, "Не удалось сохранить отметку о завершении: %s" % exc)
        should_open = bool(getattr(self, "open_about", None) and self.open_about.get_active())
        self.destroy()
        if should_open:
            self.spawn("mvs-about")

    def spawn(self, command):
        try:
            import subprocess

            subprocess.Popen([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            ui.error(self, "Не удалось запустить %s: %s" % (command, exc))


def main():
    Welcome()
    Gtk.main()


if __name__ == "__main__":
    main()
