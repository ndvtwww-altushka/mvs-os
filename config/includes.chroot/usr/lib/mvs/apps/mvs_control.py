#!/usr/bin/env python3
"""MVS Control Center — центр управления MVS OS.

Все переключатели и кнопки работают с настоящими системными инструментами:
nmcli, pactl, xrandr, brightnessctl, rfkill, lsblk, timedatectl, xfconf-query,
ufw, apt. Если инструмента нет, страница честно об этом сообщает.
"""

import glob
import json
import os
import re
import subprocess
import sys
import threading

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import mvsui as ui  # noqa: E402


# --------------------------------------------------------------------------- данные

def read_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def meminfo():
    data = {}
    for line in read_file("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        try:
            data[key] = float(rest.strip().split()[0]) * 1024.0
        except (ValueError, IndexError):
            pass
    return data


def cpu_model():
    for line in read_file("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "—"


def cpu_load():
    parts = read_file("/proc/loadavg").split()
    return parts[0] if parts else "—"


def uptime_text():
    try:
        seconds = float(read_file("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        return "—"
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    if hours:
        return "%d ч %d мин" % (hours, minutes)
    return "%d мин" % minutes


def disk_usage(path="/"):
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        return total, total - free
    except OSError:
        return 0, 0


def battery():
    for path in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            capacity = int(read_file(os.path.join(path, "capacity")).strip() or 0)
        except ValueError:
            continue
        status = read_file(os.path.join(path, "status")).strip()
        return capacity, status
    return None, ""


def xrandr_outputs():
    code, text, _ = ui.run(["xrandr", "--query"], timeout=10)
    if code != 0:
        return []
    outputs = []
    current = None
    for line in text.splitlines():
        if not line or line[0].isspace():
            if current is not None and line.strip():
                match = re.match(r"\s+(\d+x\d+)", line)
                if match and match.group(1) not in current["modes"]:
                    current["modes"].append(match.group(1))
            continue
        parts = line.split()
        if not parts:
            continue
        current = {
            "name": parts[0],
            "connected": "connected" in parts,
            "modes": [],
            "current": None,
        }
        match = re.search(r"(\d+x\d+)\+", line)
        if match:
            current["current"] = match.group(1)
        outputs.append(current)
    return [item for item in outputs if item["connected"]]


def wifi_networks():
    code, text, _ = ui.run(
        ["nmcli", "-m", "multiline", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        timeout=20,
    )
    if code != 0:
        return []
    networks = []
    current = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key == "SSID":
            if current.get("ssid"):
                networks.append(current)
            current = {"ssid": value, "signal": "0", "security": ""}
        elif key == "SIGNAL" and current:
            current["signal"] = value.strip()
        elif key == "SECURITY" and current:
            current["security"] = value.strip()
    if current.get("ssid"):
        networks.append(current)

    best = {}
    for item in networks:
        name = item["ssid"]
        try:
            signal = int(item["signal"])
        except ValueError:
            signal = 0
        if name not in best or signal > best[name]["signal"]:
            item["signal"] = signal
            best[name] = item
    return sorted(best.values(), key=lambda item: -item["signal"])


def list_users():
    users = []
    for line in read_file("/etc/passwd").splitlines():
        fields = line.split(":")
        if len(fields) < 7:
            continue
        try:
            uid = int(fields[2])
        except ValueError:
            continue
        if uid < 1000 or uid >= 65534:
            continue
        users.append({"name": fields[0], "uid": uid, "home": fields[5], "shell": fields[6]})
    return users


def autostart_entries():
    entries = []
    for path in sorted(glob.glob(os.path.expanduser("~/.config/autostart/*.desktop"))):
        text = read_file(path)
        name = ""
        enabled = True
        for line in text.splitlines():
            if line.startswith("Name=") and not name:
                name = line.split("=", 1)[1].strip()
            if line.startswith("Hidden=true"):
                enabled = False
            if line.startswith("X-GNOME-Autostart-enabled=false"):
                enabled = False
        entries.append({"path": path, "name": name or os.path.basename(path), "enabled": enabled})
    return entries


def set_autostart(path, enabled):
    text = read_file(path)
    if not text:
        return False
    lines = [line for line in text.splitlines() if not line.startswith(("Hidden=", "X-GNOME-Autostart-enabled="))]
    lines.append("X-GNOME-Autostart-enabled=%s" % ("true" if enabled else "false"))
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False


def wallpapers():
    found = sorted(glob.glob("/usr/share/backgrounds/mvs-*"))
    return [path for path in found if path.endswith((".svg", ".png", ".jpg"))]


# --------------------------------------------------------------------------- приложение

class ControlCenter(ui.MvsWindow):
    def __init__(self):
        super().__init__(
            "MVS Control Center",
            "Настройки и состояние системы",
            1060,
            720,
            "mvs-control",
        )
        self._build_pages()

    # -- утилиты ------------------------------------------------------------

    def spawn(self, command):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            ui.error(self, "Не удалось запустить %s: %s" % (command[0], exc))

    def async_run(self, command, done, timeout=90):
        def worker():
            result = ui.run(command, timeout=timeout)
            GLib.idle_add(done, *result)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_wallpaper(self):
        path = "/usr/share/backgrounds/mvs-os.svg"
        code, text, _ = ui.run(["xfconf-query", "-c", "xfce4-desktop", "-l"], timeout=10)
        if code == 0:
            for prop in text.splitlines():
                if prop.endswith("/last-image"):
                    ui.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", path])
                    return
        ui.run(
            [
                "xfconf-query", "-c", "xfce4-desktop", "-p",
                "/backdrop/screen0/monitor0/workspace0/last-image", "-s", path,
                "--create", "-t", "string",
            ]
        )

    # -- страницы -----------------------------------------------------------

    def _build_pages(self):
        self.add_page("overview", "Обзор", "preferences-system", self.page_overview())
        self.add_page("appearance", "Оформление", "preferences-desktop", self.page_appearance())
        self.add_page("display", "Экран", "video-display", self.page_display())
        self.add_page("sound", "Звук", "audio-volume-high", self.page_sound())
        self.add_page("network", "Сеть", "applications-internet", self.page_network())
        self.add_page("bluetooth", "Bluetooth", "bluetooth", self.page_bluetooth())
        self.add_page("devices", "Устройства", "drive-harddisk", self.page_devices())
        self.add_page("power", "Питание", "battery", self.page_power())
        self.add_page("language", "Язык и раскладки", "input-keyboard", self.page_language())
        self.add_page("datetime", "Дата и время", "preferences-system-time", self.page_datetime())
        self.add_page("users", "Пользователи", "system-users", self.page_users())
        self.add_page("autostart", "Автозапуск", "media-playback-start", self.page_autostart())
        self.add_page("security", "Безопасность", "security-high", self.page_security())
        self.add_page("updates", "Обновления", "software-update-available", self.page_updates())

    # -- обзор --------------------------------------------------------------

    def page_overview(self):
        mem = meminfo()
        total = mem.get("MemTotal", 0)
        used = total - mem.get("MemAvailable", 0)
        disk_total, disk_used = disk_usage("/")

        live = os.path.exists("/etc/sudoers.d/90-mvs-live")
        mode = "Live-система" if live else "Установленная система"
        hero = ui.card(
            ui.h1("MVS OS %s «%s»" % (ui.VERSION, ui.CODENAME)),
            ui.subtle(
                "%s · пользователь %s · ядро %s"
                % (mode, ui.out(["id", "-un"]) or "mvs", ui.out(["uname", "-r"]) or "—")
            ),
        )

        def meter(title, value, limit, text):
            bar = Gtk.ProgressBar()
            bar.set_fraction(min(1.0, value / limit) if limit else 0.0)
            box = ui.vbox(4)
            box.pack_start(ui.h2(title), False, False, 0)
            box.pack_start(bar, False, False, 0)
            box.pack_start(ui.subtle(text), False, False, 0)
            return box

        meters = ui.card(
            meter(
                "Память",
                used,
                total,
                "%s из %s" % (ui.human_bytes(used), ui.human_bytes(total)),
            ),
            meter(
                "Диск /",
                disk_used,
                disk_total,
                "%s из %s" % (ui.human_bytes(disk_used), ui.human_bytes(disk_total)),
            ),
        )

        system = ui.card(
            ui.h2("Оборудование"),
            ui.row("Процессор", cpu_model(), suffix=ui.label("нагрузка " + cpu_load(), "mvs-subtle")),
            ui.label("", "mvs-sep"),
            ui.row("Время работы", uptime_text()),
            ui.label("", "mvs-sep"),
            ui.row("Имя компьютера", ui.out(["hostname"]) or "mvs-os"),
        )

        actions_row = ui.hbox(10)
        for text, command in (
            ("Обновления", ["mvs-update"]),
            ("Магазин", ["mvs-store"]),
            ("Монитор", ["mvs-monitor"]),
            ("Doctor", ["mvs-doctor"]),
            ("Очистка", ["mvs-cleaner"]),
        ):
            actions_row.pack_start(
                ui.button(text, lambda _b, cmd=command: self.spawn(cmd)), False, False, 0
            )

        actions = ui.card(ui.h2("Быстрые действия"), actions_row)

        return ui.page(hero, meters, system, actions)

    # -- оформление ---------------------------------------------------------

    def page_appearance(self):
        current = ui.theme_mode()

        def on_theme(active):
            mode = ui.set_theme("light" if active else "dark")
            # Перекрашиваем открытое окно Control Center сразу; остальные
            # приложения MVS подхватят тему при следующем запуске.
            ui.apply_theme()
            ui.notify(
                "Тема: %s. Перезапустите приложения MVS."
                % ("светлая" if mode == "light" else "тёмная")
            )

        theme_card = ui.card(
            ui.h2("Тема интерфейса"),
            ui.switch_row(
                "Светлая тема",
                "Тёмная — основная тема MVS. Переключение применяется к системе и приложениям.",
                current == "light",
                on_theme,
            ),
        )

        picker = Gtk.ComboBoxText()
        images = wallpapers()
        for path in images:
            picker.append(path, os.path.basename(path))
        active = ui.settings().get("wallpaper", "")
        if active in images:
            picker.set_active_id(active)

        def on_wallpaper(widget):
            choice = widget.get_active_id()
            if not choice:
                return
            ui.save_settings(wallpaper=choice)
            code, text, _ = ui.run(["xfconf-query", "-c", "xfce4-desktop", "-l"], timeout=10)
            applied = False
            if code == 0:
                for prop in text.splitlines():
                    if prop.endswith("/last-image"):
                        ui.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", choice])
                        applied = True
            if not applied:
                ui.run([
                    "xfconf-query", "-c", "xfce4-desktop", "-p",
                    "/backdrop/screen0/monitor0/workspace0/last-image",
                    "-s", choice, "--create", "-t", "string",
                ])
            ui.notify("Обои изменены")

        picker.connect("changed", on_wallpaper)

        def choose_file(_button):
            dialog = Gtk.FileChooserDialog(
                title="Выберите обои",
                transient_for=self,
                action=Gtk.FileChooserAction.OPEN,
            )
            dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Выбрать", Gtk.ResponseType.OK)
            for name, pattern in (("Изображения", "*.svg"), ("Изображения", "*.png"), ("Все файлы", "*")):
                filter_ = Gtk.FileFilter()
                filter_.set_name(name)
                filter_.add_pattern(pattern)
                dialog.add_filter(filter_)
            if dialog.run() == Gtk.ResponseType.OK:
                choice = dialog.get_filename()
                ui.save_settings(wallpaper=choice)
                if choice:
                    code, text, _ = ui.run(["xfconf-query", "-c", "xfce4-desktop", "-l"], timeout=10)
                    if code == 0:
                        for prop in text.splitlines():
                            if prop.endswith("/last-image"):
                                ui.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", choice])
            dialog.destroy()

        wallpaper_card = ui.card(
            ui.h2("Обои рабочего стола"),
            ui.row("Готовые обои MVS", "Фирменные градиенты и сетка", picker),
            ui.button("Выбрать свой файл…", choose_file),
        )

        icons = ui.card(
            ui.h2("Иконки и курсоры"),
            ui.row("Иконки", "Тема MVS на базе Papirus-Dark", ui.label("MVS", "mvs-accent")),
            ui.label("", "mvs-sep"),
            ui.row("Курсоры", "Adwaita — стандартный набор X11", ui.label("Adwaita", "mvs-subtle")),
            ui.subtle(
                "Свой набор курсоров требует бинарных Xcursor-файлов; пока используется системный.",
                wrap=True,
            ),
        )

        return ui.page(ui.h1("Оформление"), ui.subtle("Тема, обои, иконки"), theme_card, wallpaper_card, icons)

    # -- экран --------------------------------------------------------------

    def page_display(self):
        outputs = xrandr_outputs()
        content = [ui.h1("Экран"), ui.subtle("Разрешение и яркость")]

        if not outputs:
            content.append(ui.card(ui.h2("Дисплеи"), ui.subtle("xrandr не отвечает или нет графической сессии.")))
        else:
            for output in outputs:
                picker = Gtk.ComboBoxText()
                for mode in output["modes"]:
                    picker.append(mode, mode)
                if output["current"]:
                    picker.set_active_id(output["current"])
                picker.connect(
                    "changed",
                    lambda widget, name=output["name"]: self._apply_mode(name, widget.get_active_id()),
                )
                content.append(
                    ui.card(
                        ui.h2("Монитор %s" % output["name"]),
                        ui.row("Разрешение", "Список режимов из xrandr", picker),
                    )
                )

        brightness_card = self._brightness_card()
        if brightness_card is not None:
            content.append(brightness_card)

        return ui.page(*content)

    def _apply_mode(self, output, mode):
        if not mode:
            return
        code, _, err = ui.run(["xrandr", "--output", output, "--mode", mode], timeout=20)
        if code != 0:
            ui.error(self, err.strip() or "xrandr не смог применить режим")
        else:
            ui.notify("Разрешение %s: %s" % (output, mode))

    def _brightness_card(self):
        if not ui.has("brightnessctl"):
            return ui.card(
                ui.h2("Яркость"),
                ui.subtle("Утилита brightnessctl не установлена — управление яркостью недоступно."),
            )
        code, text, _ = ui.run(["brightnessctl", "-m"], timeout=10)
        if code != 0 or "," not in text:
            return ui.card(ui.h2("Яркость"), ui.subtle("Подсветка экрана не найдена."))
        parts = text.strip().split(",")
        current = 100
        for part in parts:
            if part.endswith("%"):
                try:
                    current = int(part.rstrip("%"))
                except ValueError:
                    pass
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        scale.set_value(current)
        scale.set_hexpand(True)
        scale.set_draw_value(True)

        def on_change(widget):
            ui.run(["brightnessctl", "set", "%d%%" % int(widget.get_value())], timeout=5)

        scale.connect("value-changed", on_change)
        return ui.card(ui.h2("Яркость"), scale)

    # -- звук ---------------------------------------------------------------

    def page_sound(self):
        def volume(target, is_mute=False):
            if is_mute:
                text = ui.out(["pactl", "get-sink-mute", target])
                return "да" in text.lower() or "yes" in text.lower()
            text = ui.out(["pactl", "get-sink-volume", target])
            match = re.search(r"(\d+)%", text)
            return int(match.group(1)) if match else 50

        volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        volume_scale.set_value(volume("@DEFAULT_SINK@"))
        volume_scale.set_hexpand(True)
        volume_scale.connect(
            "value-changed",
            lambda widget: ui.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % int(widget.get_value())],
                timeout=5,
            ),
        )

        muted = volume("@DEFAULT_SINK@", is_mute=True)
        mute_switch = Gtk.Switch()
        mute_switch.set_active(muted)
        mute_switch.set_valign(Gtk.Align.CENTER)

        def on_mute(widget, _pspec):
            ui.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if widget.get_active() else "0"],
                timeout=5,
            )

        mute_switch.connect("notify::active", on_mute)

        mic_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        mic_scale.set_value(volume("@DEFAULT_SOURCE@"))
        mic_scale.set_hexpand(True)
        mic_scale.connect(
            "value-changed",
            lambda widget: ui.run(
                ["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "%d%%" % int(widget.get_value())],
                timeout=5,
            ),
        )

        outputs = []
        for line in ui.out(["pactl", "list", "short", "sinks"]).splitlines():
            fields = line.split("\t")
            if len(fields) >= 2:
                outputs.append(fields[1])

        devices = ui.card(ui.h2("Устройства вывода"))
        if outputs:
            for name in outputs:
                devices.pack_start(ui.row(name, "PulseAudio", ui.label("активно", "mvs-subtle")), False, False, 0)
        else:
            devices.pack_start(ui.subtle("PulseAudio не отвечает."), False, False, 0)

        return ui.page(
            ui.h1("Звук"),
            ui.subtle("Громкость, микрофон и устройства"),
            ui.card(ui.h2("Громкость"), volume_scale, ui.row("Без звука", None, mute_switch)),
            ui.card(ui.h2("Микрофон"), mic_scale),
            devices,
            ui.button("Открыть подробные настройки звука", lambda _b: self.spawn(["pavucontrol"])),
        )

    # -- сеть ---------------------------------------------------------------

    def page_network(self):
        state = ui.out(["nmcli", "-t", "-f", "STATE", "general"]) or "unknown"
        wifi_radio = ui.out(["nmcli", "radio", "wifi"]) or "unknown"
        active = ui.out(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])

        switch = Gtk.Switch()
        switch.set_active(wifi_radio == "enabled")
        switch.set_valign(Gtk.Align.CENTER)

        def toggle_wifi(widget, _pspec):
            ui.run(["nmcli", "radio", "wifi", "on" if widget.get_active() else "off"], timeout=15)

        switch.connect("notify::active", toggle_wifi)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        def reload_networks():
            for child in listbox.get_children():
                listbox.remove(child)
            networks = wifi_networks()
            if not networks:
                listbox.add(ui.subtle("Сети не найдены. Проверьте адаптер Wi-Fi."))
            for network in networks[:24]:
                title = network["ssid"]
                security = network["security"] or "открытая"
                connect = ui.button(
                    "Подключить",
                    lambda _b, ssid=network["ssid"], sec=network["security"]: self._connect_wifi(ssid, sec, reload_networks),
                )
                listbox.add(ui.row(title, "%s · сигнал %s%%" % (security, network["signal"]), connect))
            listbox.show_all()

        scroll = ui.scrolled(listbox, 300)
        reload_networks()

        conn_card = ui.card(
            ui.h2("Подключение"),
            ui.row("Состояние", state, ui.label("Wi-Fi: " + wifi_radio, "mvs-subtle")),
            ui.label("", "mvs-sep"),
            ui.row("Активные соединения", active.replace("\n", ", ") if active else "нет"),
        )

        return ui.page(
            ui.h1("Сеть"),
            ui.subtle("Wi-Fi и Ethernet через NetworkManager"),
            ui.card(ui.switch_row("Wi-Fi", "Включить беспроводной адаптер", wifi_radio == "enabled", lambda v: ui.run(["nmcli", "radio", "wifi", "on" if v else "off"], timeout=15))),
            conn_card,
            ui.card(
                ui.h2("Доступные сети"),
                scroll,
                ui.button("Обновить список", lambda _b: reload_networks()),
            ),
            ui.button("Открыть настройки сети", lambda _b: self.spawn(["nm-connection-editor"])),
        )

    def _connect_wifi(self, ssid, security, on_done):
        password = ""
        if security:
            dialog = Gtk.Dialog(title="Подключение к %s" % ssid, transient_for=self, modal=True)
            dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Подключить", Gtk.ResponseType.OK)
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_placeholder_text("Пароль Wi-Fi")
            entry.set_activates_default(True)
            box = dialog.get_content_area()
            box.set_margin_top(16)
            box.set_margin_bottom(16)
            box.set_margin_start(16)
            box.set_margin_end(16)
            box.add(ui.label("Пароль для «%s»" % ssid))
            box.add(entry)
            dialog.show_all()
            if dialog.run() != Gtk.ResponseType.OK:
                dialog.destroy()
                return
            password = entry.get_text()
            dialog.destroy()

        command = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            command += ["password", password]

        def done(code, _out, err):
            if code == 0:
                ui.notify("Подключено: %s" % ssid)
                on_done()
            else:
                ui.error(self, (err or "не удалось подключиться").strip())

        self.async_run(command, done, timeout=60)

    # -- bluetooth ----------------------------------------------------------

    def page_bluetooth(self):
        code, text, _ = ui.run(["bluetoothctl", "show"], timeout=10)
        powered = "Powered: yes" in text
        address = ""
        match = re.search(r"Controller\s+([0-9A-F:]{17})", text)
        if match:
            address = match.group(1)

        devices = []
        for line in ui.out(["bluetoothctl", "devices"]).splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                devices.append((parts[1], parts[2]))

        device_box = ui.card(ui.h2("Устройства"))
        if devices:
            for mac, name in devices:
                device_box.pack_start(ui.row(name, mac), False, False, 0)
        else:
            device_box.pack_start(ui.subtle("Сопряжённых устройств нет."), False, False, 0)

        toggle = Gtk.Switch()
        toggle.set_active(powered)
        toggle.set_valign(Gtk.Align.CENTER)

        def on_toggle(widget, _pspec):
            ui.priv(["bluetoothctl", "power", "on" if widget.get_active() else "off"], timeout=15)

        toggle.connect("notify::active", on_toggle)

        return ui.page(
            ui.h1("Bluetooth"),
            ui.subtle("Адаптер и сопряжённые устройства"),
            ui.card(
                ui.h2("Адаптер"),
                ui.row("Состояние", "включён" if powered else "выключен", toggle),
                ui.label("", "mvs-sep"),
                ui.row("Адрес", address or "адаптер не найден"),
            ),
            device_box,
            ui.button("Открыть bluetoothctl", lambda _b: self.spawn(["xfce4-terminal", "-e", "bluetoothctl"])),
            ui.button("Настройки Bluetooth", lambda _b: self.spawn(["blueman-manager"])),
        )

    # -- устройства ---------------------------------------------------------

    def page_devices(self):
        code, text, _ = ui.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"], timeout=10)
        box = ui.card(ui.h2("Диски и разделы"))
        if code != 0:
            box.pack_start(ui.subtle("lsblk недоступен."), False, False, 0)
        else:
            try:
                data = json.loads(text)
            except ValueError:
                data = {}
            for disk in data.get("blockdevices", []):
                title = "%s · %s" % (disk.get("name"), disk.get("size") or "")
                subtitle = (disk.get("model") or "").strip() or disk.get("type", "")
                box.pack_start(ui.row(title, subtitle), False, False, 0)
                for child in disk.get("children") or []:
                    mountpoint = child.get("mountpoint") or ""
                    device = "/dev/%s" % child.get("name")
                    action = (
                        ui.button(
                            "Отмонтировать",
                            lambda _b, dev=device: self._umount(dev),
                        )
                        if mountpoint
                        else ui.button(
                            "Смонтировать",
                            lambda _b, dev=device: self._mount(dev),
                        )
                    )
                    box.pack_start(
                        ui.row(
                            "  %s · %s" % (child.get("name"), child.get("size") or ""),
                            mountpoint or "не смонтирован",
                            action,
                        ),
                        False,
                        False,
                        0,
                    )

        return ui.page(
            ui.h1("Устройства"),
            ui.subtle("Флешки, диски, разделы"),
            box,
            ui.button("Открыть Проводник", lambda _b: self.spawn(["thunar"])),
        )

    def _mount(self, device):
        code, _out, err = ui.run(["udisksctl", "mount", "-b", device], timeout=30)
        if code != 0:
            ui.error(self, (err or "не удалось смонтировать").strip())
        else:
            ui.notify("Смонтировано: %s" % device)

    def _umount(self, device):
        code, _out, err = ui.run(["udisksctl", "unmount", "-b", device], timeout=30)
        if code != 0:
            ui.error(self, (err or "не удалось отмонтировать").strip())
        else:
            ui.notify("Отмонтировано: %s" % device)

    # -- питание ------------------------------------------------------------

    def page_power(self):
        capacity, status = battery()
        if capacity is None:
            battery_card = ui.card(ui.h2("Батарея"), ui.subtle("Батарея не обнаружена — стационарный ПК."))
        else:
            bar = Gtk.ProgressBar()
            bar.set_fraction(max(0.0, min(1.0, capacity / 100.0)))
            battery_card = ui.card(
                ui.h2("Батарея"),
                bar,
                ui.subtle("%d%% · %s" % (capacity, status or "—")),
            )

        blank = ui.out(["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/blank-on-ac"])

        def set_blank(active):
            ui.run([
                "xfconf-query", "-c", "xfce4-power-manager",
                "-p", "/xfce4-power-manager/blank-on-ac",
                "-s", "1" if active else "0",
                "--create", "-t", "int",
            ])

        profile = ui.out(["powerprofilesctl", "get"]) or "не управляется"

        return ui.page(
            ui.h1("Питание"),
            ui.subtle("Батарея, профиль и энергосбережение"),
            battery_card,
            ui.card(
                ui.h2("Энергосбережение"),
                ui.switch_row(
                    "Гасить экран при простое",
                    "Отключение подсветки в простое (на питании от сети)",
                    blank.strip() in ("1", "true"),
                    set_blank,
                ),
                ui.label("", "mvs-sep"),
                ui.row("Профиль производительности", profile),
            ),
            ui.button("Настройки питания XFCE", lambda _b: self.spawn(["xfce4-power-manager-settings"])),
        )

    # -- язык ---------------------------------------------------------------

    def page_language(self):
        locale = ui.out(["sh", "-c", "grep -h '^LANG=' /etc/default/locale ~/.config/locale 2>/dev/null | head -n 1"])
        layout = ui.out(["setxkbmap", "-query"])
        layout_line = ""
        for line in layout.splitlines():
            if line.startswith("layout"):
                layout_line = line.strip()

        def set_layout(value):
            code, _out, err = ui.run(["setxkbmap", "-layout", value, "-option", "grp:alt_shift_toggle"], timeout=10)
            if code != 0:
                ui.error(self, err.strip() or "не удалось применить раскладку")
                return
            ui.run([
                "xfconf-query", "-c", "keyboard-layout", "-p", "/Default/XkbLayout",
                "-s", value, "--create", "-t", "string",
            ])
            ui.run([
                "xfconf-query", "-c", "keyboard-layout", "-p", "/Default/XkbOptions/Group",
                "-s", "grp:alt_shift_toggle", "--create", "-t", "string",
            ])
            ui.notify("Раскладка: %s" % value)

        layout_buttons = ui.hbox(10)
        for text, value in (
            ("Русская", "ru"),
            ("Английская", "us"),
            ("Русская + английская", "ru,us"),
        ):
            layout_buttons.pack_start(
                ui.button(text, lambda _b, v=value: set_layout(v)), False, False, 0
            )

        return ui.page(
            ui.h1("Язык и раскладки"),
            ui.subtle("Локаль системы и клавиатура"),
            ui.card(
                ui.h2("Системный язык"),
                ui.row("Локаль", locale.replace("LANG=", "") or "ru_RU.UTF-8"),
                ui.row("Текущая раскладка", layout_line or "—"),
            ),
            ui.card(
                ui.h2("Быстрое переключение"),
                ui.subtle(
                    "Alt+Shift — смена раскладки. Выбор применяется сразу и сохраняется в XFCE.",
                    wrap=True,
                ),
                layout_buttons,
            ),
            ui.button(
                "Открыть настройки клавиатуры XFCE",
                lambda _b: self.spawn(["xfce4-keyboard-settings"]),
            ),
        )

    # -- дата и время -------------------------------------------------------

    def page_datetime(self):
        ntp = "yes" in ui.out(["timedatectl", "show", "-p", "NTP", "--value"]).lower()
        timezone = ui.out(["timedatectl", "show", "-p", "Timezone", "--value"]) or "—"

        def on_ntp(active):
            code, _out, err = ui.priv(["timedatectl", "set-ntp", "true" if active else "false"], timeout=20)
            if code != 0:
                ui.error(self, (err or "не удалось изменить синхронизацию").strip())
            else:
                ui.notify("Синхронизация времени: %s" % ("включена" if active else "выключена"))

        entry = Gtk.Entry()
        entry.set_placeholder_text("Например, Europe/Moscow")
        entry.set_text(timezone)

        def apply_timezone(_button):
            zone = entry.get_text().strip()
            if not zone:
                return
            code, _out, err = ui.priv(["timedatectl", "set-timezone", zone], timeout=20)
            if code != 0:
                ui.error(self, (err or "неизвестный часовой пояс").strip())
            else:
                ui.notify("Часовой пояс: %s" % zone)

        return ui.page(
            ui.h1("Дата и время"),
            ui.subtle("Часовой пояс и синхронизация"),
            ui.card(
                ui.h2("Время"),
                ui.row("Сейчас", ui.out(["date", "+%d.%m.%Y %H:%M"])),
                ui.label("", "mvs-sep"),
                ui.switch_row("Синхронизация по сети", "NTP через systemd-timesyncd", ntp, on_ntp),
            ),
            ui.card(
                ui.h2("Часовой пояс"),
                ui.row("Текущий", timezone),
                entry,
                ui.button("Применить", apply_timezone),
            ),
        )

    # -- пользователи -------------------------------------------------------

    def page_users(self):
        box = ui.card(ui.h2("Учётные записи"))
        for user in list_users():
            box.pack_start(
                ui.row(
                    user["name"],
                    "UID %d · %s" % (user["uid"], user["shell"]),
                    ui.button(
                        "Сменить пароль",
                        lambda _b, name=user["name"]: self.spawn(
                            ["xfce4-terminal", "-e", "sh -c 'sudo passwd %s; read -r _'" % name]
                        ),
                    ),
                ),
                False,
                False,
                0,
            )

        live_note = "Live-режим: пароль не требуется, изменения не сохраняются."
        if os.path.exists("/etc/sudoers.d/90-mvs-live"):
            live_note = (
                "Live-режим: пользователь mvs может выполнять административные команды без пароля. "
                "При установке на диск это правило удаляется, и создаётся обычная защищённая учётная запись."
            )

        return ui.page(
            ui.h1("Пользователи"),
            ui.subtle("Учётные записи и пароли"),
            box,
            ui.card(
                ui.h2("Добавить пользователя"),
                ui.subtle("Откроется терминал с интерактивной командой adduser.", wrap=True),
                ui.button(
                    "Создать учётную запись",
                    lambda _b: self.spawn(["xfce4-terminal", "-e", "sh -c 'sudo adduser; read -r _'"]),
                ),
            ),
            ui.card(ui.h2("Режим работы"), ui.subtle(live_note, wrap=True)),
        )

    # -- автозапуск ---------------------------------------------------------

    def page_autostart(self):
        box = ui.card(ui.h2("Программы при входе"))
        entries = autostart_entries()
        if not entries:
            box.pack_start(ui.subtle("Пользовательских автозапусков нет."), False, False, 0)
        for entry in entries:
            def on_toggle(active, path=entry["path"]):
                if set_autostart(path, active):
                    ui.notify("Автозапуск обновлён")
                else:
                    ui.error(self, "Не удалось изменить %s" % path)

            box.pack_start(ui.switch_row(entry["name"], os.path.basename(entry["path"]), entry["enabled"], on_toggle), False, False, 0)

        system_items = []
        for path in sorted(glob.glob("/etc/xdg/autostart/*.desktop")):
            for line in read_file(path).splitlines():
                if line.startswith("Name="):
                    system_items.append(line.split("=", 1)[1].strip())
                    break

        system_card = ui.card(ui.h2("Системные автозапуски"))
        if system_items:
            for name in system_items[:16]:
                system_card.pack_start(ui.row(name, "управляется системой"), False, False, 0)
        else:
            system_card.pack_start(ui.subtle("Нет системных автозапусков."), False, False, 0)

        return ui.page(
            ui.h1("Автозапуск"),
            ui.subtle("Что стартует вместе с рабочим столом"),
            box,
            system_card,
            ui.button("Открыть папку автозапуска", lambda _b: self.spawn(["thunar", os.path.expanduser("~/.config/autostart")])),
        )

    # -- безопасность -------------------------------------------------------

    def page_security(self):
        # Состояние ufw не запрашивается при открытии Control Center:
        # ui.priv() в установленной системе запускает pkexec, и запрос пароля
        # появлялся бы сразу при старте. Проверка — только по кнопке.
        state_label = ui.label("не проверено", "mvs-subtle")
        rules_label = ui.label("—")
        firewall_switch = Gtk.Switch()
        firewall_switch.set_active(False)
        firewall_switch.set_sensitive(False)
        firewall_switch.set_valign(Gtk.Align.CENTER)

        def toggle_firewall(widget, _pspec):
            # notify::active срабатывает и на программный set_active().
            # Без этого флага неудачная попытка откатывала переключатель,
            # откат снова вызывал toggle_firewall — и так по кругу.
            if getattr(widget, "_mvs_busy", False):
                return
            command = ["ufw", "--force", "enable"] if widget.get_active() else ["ufw", "--force", "disable"]
            widget._mvs_busy = True
            widget.set_sensitive(False)
            try:
                code_, _out, err = ui.priv(command, timeout=30)
            finally:
                widget._mvs_busy = False
                widget.set_sensitive(True)
            if code_ != 0:
                # Возвращаем переключатель в реальное состояние, не запуская
                # обработчик заново.
                widget.handler_block_by_func(toggle_firewall)
                widget.set_active(not widget.get_active())
                widget.handler_unblock_by_func(toggle_firewall)
                ui.error(self, (err or "ufw не смог изменить состояние").strip())
            else:
                state_label.set_text("включён" if widget.get_active() else "выключен")
                ui.notify("Межсетевой экран: %s" % ("включён" if widget.get_active() else "выключен"))

        firewall_switch.connect("notify::active", toggle_firewall)

        def apply_status(code_, text, _err):
            if code_ != 0:
                state_label.set_text("нет доступа к ufw")
                rules_label.set_text("—")
                firewall_switch.set_sensitive(False)
                return
            active = "Status: active" in text
            rules = len([line for line in text.splitlines() if "ALLOW" in line or "DENY" in line]) if active else 0
            state_label.set_text("включён" if active else "выключен")
            rules_label.set_text(str(rules))
            firewall_switch._mvs_busy = True
            firewall_switch.set_active(active)
            firewall_switch._mvs_busy = False
            firewall_switch.set_sensitive(True)

        def check_firewall(_button=None):
            state_label.set_text("проверяем…")
            firewall_switch.set_sensitive(False)
            self.async_run(ui.priv_prefix() + ["ufw", "status", "verbose"], apply_status, timeout=30)

        apparmor = "нет данных"
        if os.path.exists("/sys/module/apparmor/parameters/enabled"):
            apparmor = read_file("/sys/module/apparmor/parameters/enabled").strip()

        live_card = ui.card(ui.h2("Режим Live"))
        if os.path.exists("/etc/sudoers.d/90-mvs-live"):
            live_card.pack_start(
                ui.subtle(
                    "Live-сессия запускается без пароля администратора, чтобы можно было "
                    "подключать сеть, ставить пакеты и проверять систему. Установщик "
                    "удаляет это правило и создаёт защищённую учётную запись.",
                    wrap=True,
                ),
                False,
                False,
                0,
            )
        else:
            live_card.pack_start(ui.subtle("Система установлена на диск: администратор защищён паролем.", wrap=True), False, False, 0)

        return ui.page(
            ui.h1("Безопасность"),
            ui.subtle("Межсетевой экран, AppArmor, права"),
            ui.card(
                ui.h2("Межсетевой экран"),
                ui.row("Состояние", state_label, firewall_switch),
                ui.label("", "mvs-sep"),
                ui.row("Правил", "правила ALLOW/DENY", suffix=rules_label),
                ui.button("Проверить состояние", check_firewall),
                ui.subtle(
                    "Состояние читается через pkexec только по нажатию: приложение "
                    "не спрашивает пароль при каждом открытии.",
                    wrap=True,
                ),
            ),
            ui.card(
                ui.h2("AppArmor"),
                ui.row("Профили", "включён" if apparmor.startswith("Y") else apparmor),
                ui.subtle("Модуль ядра AppArmor ограничивает права программ.", wrap=True),
            ),
            live_card,
            ui.button("Показать правила ufw", lambda _b: self.spawn(["xfce4-terminal", "-e", "sh -c 'sudo ufw status verbose; read -r _'"])),
        )

    # -- обновления ---------------------------------------------------------

    def page_updates(self):
        code, text, _ = ui.run(["apt", "list", "--upgradable"], timeout=30)
        lines = [line for line in text.splitlines() if "upgradable" in line or "[" in line]
        box = ui.card(ui.h2("Доступные обновления"))
        if lines:
            box.pack_start(ui.subtle("Пакетов: %d" % len(lines)), False, False, 0)
            for line in lines[:14]:
                box.pack_start(ui.label(line.split("/")[0], "mvs-subtle"), False, False, 0)
        else:
            box.pack_start(ui.subtle("Нет данных. Откройте центр обновлений, чтобы проверить репозитории."), False, False, 0)

        return ui.page(
            ui.h1("Обновления"),
            ui.subtle("Пакеты Debian и приложения MVS"),
            box,
            ui.card(
                ui.h2("Безопасность обновлений"),
                ui.subtle(
                    "Обновления ставятся только из подписанных репозиториев Debian через apt. "
                    "Проверка подписей встроена в apt и не отключается.",
                    wrap=True,
                ),
            ),
            ui.button("Открыть MVS Update", lambda _b: self.spawn(["mvs-update"])),
            ui.button("Открыть MVS Store", lambda _b: self.spawn(["mvs-store"])),
        )


def main():
    app = ControlCenter()
    app.run()


if __name__ == "__main__":
    main()
