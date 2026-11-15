#!/usr/bin/env python3
"""MVS Games — игровой центр MVS OS.

Игры — обычные терминальные скрипты из /usr/local/share/mvs-os/games.
Центр проверяет, что файл игры на месте, и запускает её в терминале MVS.
"""

import os
import subprocess
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import mvsui as ui  # noqa: E402

GAMES_DIR = "/usr/local/share/mvs-os/games"

GAMES = [
    ("2048.sh", "2048", "Складывай числа стрелками, дойди до 2048", "2048"),
    ("snake.sh", "Змейка", "Собирай еду и не врезайся в себя", "snake"),
    ("saper.sh", "Сапёр", "Открой поле, не попав на мину", "mines"),
    ("xo.sh", "Крестики-нолики", "Против компьютера или вдвоём", "xo"),
    ("tetris.sh", "Тетрис", "Классические фигуры и ускорение", "tetris"),
]


def terminal_command(script, title):
    """Команда запуска игры в терминале. Возвращает список или None."""
    if not os.path.isfile(script):
        return None
    inner = "bash %s" % script
    for candidate in ("xfce4-terminal", "x-terminal-emulator"):
        if ui.has(candidate):
            if candidate == "xfce4-terminal":
                return [
                    "xfce4-terminal",
                    "--title=MVS · %s" % title,
                    "--geometry=90x28",
                    "--command=%s" % inner,
                ]
            return [candidate, "-e", "bash", script]
    # Совсем без терминала играть нельзя: это curses-программы.
    return None


class Games(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Games", "Мини-игры MVS OS", 900, 660, "mvs-games")

        self.status = ui.subtle("Выберите игру. Выход из игры — клавиша q.")

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        flow.set_row_spacing(12)
        flow.set_column_spacing(12)
        flow.set_homogeneous(True)

        for filename, title, description, icon in GAMES:
            path = os.path.join(GAMES_DIR, filename)
            flow.add(self.tile(title, description, icon, path))

        flow.show_all()

        page = ui.page(
            ui.h1("MVS Games"),
            ui.subtle(
                "Пять игр входят в систему и не требуют интернета. "
                "Все они работают в терминале — так они остаются лёгкими."
            ),
            ui.card(ui.h2("Игры"), flow),
            ui.card(
                ui.h2("Управление"),
                ui.row("Выход", "q или Esc — вернуться в систему"),
                ui.label("", "mvs-sep"),
                ui.row("Стрелки", "движение, выбор, поворот"),
                ui.label("", "mvs-sep"),
                ui.row("Пробел", "пауза, подтверждение, сброс"),
            ),
            self.status,
        )
        self.add_page("games", "Игры", "applications-games", page)

    def tile(self, title, description, icon, script):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("mvs-tile")

        box = ui.vbox(6)
        image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
        image.set_pixel_size(44)
        box.pack_start(image, False, False, 0)
        box.pack_start(ui.label(title, "mvs-h2", xalign=0.5), False, False, 0)
        box.pack_start(ui.subtle(description), False, False, 0)

        button.add(box)
        button.connect("clicked", lambda _b: self.launch(title, script))
        return button

    def launch(self, title, script):
        command = terminal_command(script, title)
        if command is None:
            ui.error(
                self,
                "Не найден файл игры или терминал:\n%s\n\n"
                "Проверьте, что установлен пакет xfce4-terminal." % script,
            )
            return
        try:
            subprocess.Popen(command)
        except OSError as exc:
            ui.error(self, "Не удалось запустить игру: %s" % exc)
            return
        self.status.set_text("Запущено: %s" % title)


def main():
    Games().run()


if __name__ == "__main__":
    main()
