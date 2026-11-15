#!/usr/bin/env python3
"""MVS Quick — панель быстрых настроек.

Открывается по Super+S или из панели. Всё, что нажимается, вызывает настоящие
системные утилиты (nmcli, pactl, brightnessctl, xfce4-session-logout, xflock4).
"""

import glob
import os
import re
import subprocess
import sys

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


def battery():
    for path in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(path, "capacity"), "r", encoding="utf-8") as handle:
                capacity = int(handle.read().strip())
        except (OSError, ValueError):
            continue
        try:
            with open(os.path.join(path, "status"), "r", encoding="utf-8") as handle:
                status = handle.read().strip()
        except OSError:
            status = ""
        return capacity, status
    return None, ""


def sink_volume():
    if not ui.has("pactl"):
        return None
    text = ui.out(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=5)
    match = re.search(r"(\d+)%", text)
    return int(match.group(1)) if match else None


def sink_muted():
    if not ui.has("pactl"):
        return False
    text = ui.out(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=5).lower()
    return "yes" in text


def brightness_percent():
    if not ui.has("brightnessctl"):
        return None
    text = ui.out(["brightnessctl", "-m"], timeout=5)
    for part in text.split(","):
        if part.endswith("%"):
            try:
                return int(part.rstrip("%"))
            except ValueError:
                return None
    return None


def wifi_on():
    if not ui.has("nmcli"):
        return None
    return ui.out(["nmcli", "radio", "wifi"]) == "enabled"


class Quick(Gtk.Window):
    """Компактное окно без бокового меню."""

    def __init__(self):
        super().__init__(title="Быстрые настройки")
        self.set_default_size(400, 620)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("mvs-quick")
        self.set_keep_above(True)
        ui.apply_theme()

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("Быстрые настройки")
        header.set_subtitle("MVS OS %s" % ui.VERSION)
        self.set_titlebar(header)

        self.theme_label = ui.subtle("")

        self.theme_switch = Gtk.Switch()
        self.theme_switch.set_valign(Gtk.Align.CENTER)
        self.theme_switch.set_active(ui.theme_mode() == "light")
        self.theme_switch.connect("notify::active", self.on_theme)

        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_hexpand(True)
        self.volume.set_draw_value(True)
        self.volume.connect("value-changed", self.on_volume)

        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.brightness.set_hexpand(True)
        self.brightness.set_draw_value(True)
        self.brightness.connect("value-changed", self.on_brightness)

        self.network_label = ui.subtle("—")
        self.battery_label = ui.subtle("Батарея не обнаружена")

        buttons = ui.hbox(8)
        for title, command in (
            ("Монитор", ["mvs-monitor"]),
            ("Настройки", ["mvs-control"]),
        ):
            buttons.pack_start(
                ui.button(title, lambda _b, cmd=command: self.launch(cmd)), True, True, 0
            )
        session = ui.hbox(8)
        for title, command in (
            ("Заблокировать", ["xflock4"]),
            ("Выйти", ["xfce4-session-logout", "--logout"]),
            ("Выключить", ["xfce4-session-logout", "--halt"]),
        ):
            session.pack_start(
                ui.button(title, lambda _b, cmd=command: self.launch(cmd)), True, True, 0
            )

        content = ui.page(
            ui.card(
                ui.h2("Сеть"),
                self.network_label,
                ui.switch_row(
                    "Wi-Fi",
                    "Беспроводной адаптер (nmcli)",
                    bool(wifi_on()),
                    self.set_wifi,
                ),
                ui.button("Открыть настройки сети", lambda _b: self.launch(["mvs-control"])),
            ),
            ui.card(
                ui.h2("Звук"),
                self.volume,
                ui.switch_row("Без звука", "PulseAudio", sink_muted(), self.set_mute),
            ),
            ui.card(
                ui.h2("Экран"),
                ui.row(
                    "Светлая тема",
                    "Тёмная Aurora Night / светлая Aurora Day",
                    self.theme_switch,
                ),
                self.theme_label,
                ui.label("Яркость", "mvs-subtle"),
                self.brightness,
            ),
            ui.card(ui.h2("Питание"), self.battery_label),
            ui.card(ui.h2("Быстрые действия"), buttons, session),
        )
        self.add(content)

        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        self.refresh()
        GLib.timeout_add(2000, self.tick)

    # -- обновление данных ---------------------------------------------------

    def refresh(self):
        level = sink_volume()
        if level is not None:
            self.volume.handler_block_by_func(self.on_volume)
            self.volume.set_value(level)
            self.volume.handler_unblock_by_func(self.on_volume)

        percent = brightness_percent()
        if percent is not None:
            self.brightness.handler_block_by_func(self.on_brightness)
            self.brightness.set_value(percent)
            self.brightness.handler_unblock_by_func(self.on_brightness)
        self.brightness.set_sensitive(percent is not None)

        state = ui.out(["nmcli", "-t", "-f", "STATE", "general"]) if ui.has("nmcli") else ""
        name = ""
        if ui.has("nmcli"):
            name = ui.out(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
        if "connected" in state.lower():
            self.network_label.set_text("подключено: %s" % (name.splitlines()[0] if name else "—"))
        else:
            self.network_label.set_text("нет подключения")

        capacity, status = battery()
        if capacity is None:
            self.battery_label.set_text("Батарея не обнаружена — питание от сети")
        else:
            self.battery_label.set_text("%d%% · %s" % (capacity, status or "—"))

        light = ui.theme_mode() == "light"
        if self.theme_switch.get_active() != light:
            # Тему могли сменить в Control Center — подтягиваем переключатель
            # без повторного вызова on_theme.
            self.theme_switch.handler_block_by_func(self.on_theme)
            self.theme_switch.set_active(light)
            self.theme_switch.handler_unblock_by_func(self.on_theme)

        self.theme_label.set_text("сейчас: %s" % ("светлая" if light else "тёмная"))
        return False

    def tick(self):
        self.refresh()
        return True

    # -- действия ------------------------------------------------------------

    def on_theme(self, widget, _pspec):
        mode = ui.set_theme("light" if widget.get_active() else "dark")
        # set_theme меняет файлы и XFCE, но уже открытое окно красит CSS,
        # загруженный при старте. Перезагружаем его, иначе переключатель
        # менял бы тему только для следующих запусков.
        ui.apply_theme()
        self.refresh()
        ui.notify("Тема: %s" % ("светлая" if mode == "light" else "тёмная"))

    def on_volume(self, widget):
        ui.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % int(widget.get_value())],
            timeout=5,
        )

    def set_mute(self, active):
        ui.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if active else "0"],
            timeout=5,
        )

    def set_wifi(self, active):
        if not ui.has("nmcli"):
            ui.error(self, "NetworkManager не установлен.")
            return
        code, _out, err = ui.run(
            ["nmcli", "radio", "wifi", "on" if active else "off"], timeout=15
        )
        if code != 0:
            ui.error(self, (err or "не удалось переключить Wi-Fi").strip())
        self.refresh()

    def on_brightness(self, widget):
        if ui.has("brightnessctl"):
            ui.run(["brightnessctl", "set", "%d%%" % int(widget.get_value())], timeout=5)

    def launch(self, command):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            ui.error(self, "Не удалось запустить %s: %s" % (command[0], exc))
        return False


def main():
    Quick()
    Gtk.main()


if __name__ == "__main__":
    main()
