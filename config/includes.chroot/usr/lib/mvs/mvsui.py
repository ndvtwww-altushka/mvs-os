#!/usr/bin/env python3
"""MVS OS — общие компоненты интерфейса и системные помощники.

Единая точка для всех приложений MVS: цвета, шрифты, окно с боковым меню,
карточки, журнал вывода команд, запуск системных утилит.
"""

import json
import os
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

def _identity(path, fallback):
    """Версия и кодовое имя живут в /etc/mvs-version и /etc/mvs-codename.

    Так номер версии меняется в одном файле VERSION при сборке, а не
    в шести местах исходников. Если файла нет — честный запасной вариант.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        return value or fallback
    except OSError:
        return fallback


VERSION = _identity("/etc/mvs-version", "1.4")
CODENAME = _identity("/etc/mvs-codename", "Aurora Nova")

CONFIG_DIR = os.path.expanduser("~/.config/mvs")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

THEME_DIR = "/usr/share/mvs/theme"
THEME_DARK = os.path.join(THEME_DIR, "mvs-dark.css")
THEME_LIGHT = os.path.join(THEME_DIR, "mvs-light.css")

APP_ICON = "mvs-hub"


# --------------------------------------------------------------------------- настройки

def settings():
    """Настройки MVS. Битый файл не должен ломать приложения."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_settings(**values):
    data = settings()
    data.update(values)
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        return True
    except OSError:
        return False


def theme_mode():
    mode = settings().get("theme", "dark")
    return mode if mode in ("dark", "light") else "dark"


def set_theme(mode):
    """Переключает тему MVS в настройках, XFCE и GTK. Возвращает итоговый режим."""
    mode = "light" if mode == "light" else "dark"
    save_settings(theme=mode)

    gtk_theme = "MVS-Light" if mode == "light" else "MVS-Dark"
    wm_theme = "Arc" if mode == "light" else "Arc-Dark"
    run(["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName", "-s", gtk_theme], timeout=10)
    run(["xfconf-query", "-c", "xsettings", "-p", "/Net/IconThemeName", "-s", "MVS"], timeout=10)
    run(["xfconf-query", "-c", "xfwm4", "-p", "/general/theme", "-s", wm_theme], timeout=10)

    ini_path = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
    try:
        lines = []
        if os.path.exists(ini_path):
            with open(ini_path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith("gtk-theme-name="):
                lines[index] = "gtk-theme-name=%s" % gtk_theme
                replaced = True
        if not replaced:
            lines.append("gtk-theme-name=%s" % gtk_theme)
        os.makedirs(os.path.dirname(ini_path), exist_ok=True)
        with open(ini_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass

    apply_theme()
    return mode


# --------------------------------------------------------------------------- команды

def run(cmd, timeout=20, shell=False, env=None):
    """Запуск команды. Возвращает (код, stdout, stderr) и никогда не бросает."""
    if isinstance(cmd, (list, tuple)):
        cmd = list(cmd)
    try:
        done = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return done.returncode, done.stdout or "", done.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "таймаут команды"
    except FileNotFoundError:
        return 127, "", "команда не найдена"
    except Exception as exc:  # защита от любых неожиданностей
        return 1, "", str(exc)


def out(cmd, **kwargs):
    return run(cmd, **kwargs)[1].strip()


def has(command):
    return subprocess.call(
        ["sh", "-c", 'command -v "$1" >/dev/null 2>&1', "sh", command]
    ) == 0


def priv_prefix():
    """В Live-режиме sudo без пароля; в установленной системе — pkexec.

    Раньше здесь был вызов `sudo -n true`: он мог подвесить окно на пять
    секунд ещё до показа диалога. Теперь режим определяется по файлу,
    который Calamares удаляет при установке, — мгновенно и без команд.
    """
    if os.geteuid() == 0:
        return []
    if os.path.exists("/etc/sudoers.d/90-mvs-live"):
        return ["sudo", "-n"]
    return ["pkexec"]


def priv(cmd, **kwargs):
    return run(priv_prefix() + list(cmd), **kwargs)


# apt в графическом приложении не должен задавать вопросы и не должен
# затирать конфиги, которые пользователь уже менял. Иначе dist-upgrade
# останавливается на «What do you want to do about modified
# configuration file ...?» и окно выглядит зависшим.
APT_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "APT_LISTCHANGES_FRONTEND": "none",
    "NEEDRESTART_MODE": "a",
    "LC_ALL": "C.UTF-8",
}
APT_OPTS = [
    "-y",
    "-o", "Dpkg::Options::=--force-confdef",
    "-o", "Dpkg::Options::=--force-confold",
    "-o", "DPkg::Lock::Timeout=120",
]


def apt_command(args, privileged=True):
    """Команда apt-get с неинтерактивными ответами и сохранением конфигов."""
    command = ["apt-get"] + APT_OPTS + [str(arg) for arg in args]
    prefix = priv_prefix() if privileged else []
    return prefix + ["env"] + ["%s=%s" % item for item in APT_ENV.items()] + command


def apt_stream(args, log, on_done=None, privileged=True):
    """apt-get в фоне: интерфейс не замирает, вывод идёт в журнал."""
    stream(apt_command(args, privileged), log, on_done, env=dict(os.environ, **APT_ENV))


def notify(text, title="MVS OS"):
    run(["notify-send", "-a", "MVS OS", "-i", APP_ICON, title, text], timeout=5)


def human_bytes(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(size) < 1024 or unit == "ТБ":
            return ("%.0f %s" if unit == "Б" else "%.1f %s") % (size, unit)
        size /= 1024.0
    return "—"


# --------------------------------------------------------------------------- стиль

_PROVIDER = None


def apply_theme():
    """Подключает нашу тему MVS поверх системной.

    Повторный вызов (смена темы в Quick Settings или Control Center) снимает
    предыдущий провайдер: иначе в одном окне накапливались бы тёмный и
    светлый CSS, и старый перекрывал бы новый.
    """
    global _PROVIDER
    path = THEME_DARK if theme_mode() == "dark" else THEME_LIGHT
    if not os.path.exists(path):
        path = THEME_DARK
    if not os.path.exists(path):
        return None
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(path)
    except Exception:
        return None
    screen = Gdk.Screen.get_default()
    if screen is None:
        return None
    if _PROVIDER is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _PROVIDER)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _PROVIDER = provider
    return provider


# --------------------------------------------------------------------------- виджеты

def label(text, css=None, xalign=0.0, wrap=False, selectable=False):
    widget = Gtk.Label(label=text)
    widget.set_xalign(xalign)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_max_width_chars(64)
        widget.set_hexpand(True)
    if selectable:
        widget.set_selectable(True)
        widget.set_can_focus(False)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def h1(text):
    return label(text, "mvs-h1")


def h2(text):
    return label(text, "mvs-h2")


def subtle(text, wrap=False):
    return label(text, "mvs-subtle", wrap=wrap)


def hbox(spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def vbox(spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def card(*children):
    box = vbox(10)
    box.get_style_context().add_class("card")
    for child in children:
        box.pack_start(child, False, False, 0)
    return box


def scrolled(child, height=-1):
    area = Gtk.ScrolledWindow()
    area.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    area.set_hexpand(True)
    area.set_vexpand(True)
    if height > 0:
        area.set_size_request(-1, height)
    area.add(child)
    return area


def page(*children, spacing=16):
    """Прокручиваемая страница: заголовок + карточки."""
    inner = vbox(spacing)
    inner.set_margin_start(26)
    inner.set_margin_end(26)
    inner.set_margin_top(22)
    inner.set_margin_bottom(26)
    for child in children:
        inner.pack_start(child, False, False, 0)
    return scrolled(inner)


def row(title, subtitle=None, widget=None, suffix=None):
    box = hbox(12)
    texts = vbox(2)
    texts.pack_start(label(title), False, False, 0)
    if subtitle is not None:
        # Подзаголовком может быть строка или готовый виджет (например,
        # обновляемая подпись в мониторе). Виджет не заворачиваем в label.
        if isinstance(subtitle, Gtk.Widget):
            texts.pack_start(subtitle, False, False, 0)
        elif subtitle:
            texts.pack_start(subtle(str(subtitle), wrap=True), False, False, 0)
    texts.set_hexpand(True)
    box.pack_start(texts, True, True, 0)
    if suffix is not None:
        box.pack_start(suffix, False, False, 0)
    if widget is not None:
        box.pack_start(widget, False, False, 0)
    return box


def button(text, callback=None, css="mvs-button"):
    widget = Gtk.Button(label=text)
    if css:
        widget.get_style_context().add_class(css)
    if callback:
        widget.connect("clicked", callback)
    return widget


def switch_row(title, subtitle, active, callback):
    widget = Gtk.Switch()
    widget.set_active(bool(active))
    widget.set_valign(Gtk.Align.CENTER)
    widget.connect("notify::active", lambda sw, _pspec: callback(sw.get_active()))
    return row(title, subtitle, widget)


class LogView(Gtk.ScrolledWindow):
    """Журнал вывода системных команд."""

    def __init__(self, height=240):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.set_size_request(-1, height)
        self.set_shadow_type(Gtk.ShadowType.NONE)
        self.view = Gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_monospace(True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.get_style_context().add_class("mvs-log")
        self.buffer = self.view.get_buffer()
        self.add(self.view)
        self.get_style_context().add_class("mvs-log-wrap")

    def append(self, line):
        self.buffer.insert(self.buffer.get_end_iter(), "%s\n" % line)
        mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.view.scroll_mark_onscreen(mark)
        return False

    def clear(self):
        self.buffer.set_text("")


def idle_once(callback, *args):
    """Вызывает callback в главном потоке ровно один раз.

    GLib.idle_add убирает источник только тогда, когда обработчик вернул
    False. Обычная функция возвращает None — а это не False, поэтому
    источник повторялся бы бесконечно. Обёртка всегда возвращает False.
    """
    def invoke():
        callback(*args)
        return False

    GLib.idle_add(invoke)


def stream(cmd, log, on_done=None, shell=False, env=None):
    """Выполняет команду и построчно пишет вывод в LogView (в отдельном потоке)."""
    shown = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)

    def worker():
        idle_once(log.append, "$ %s" % shown)
        try:
            proc = subprocess.Popen(
                cmd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            if proc.stdout is not None:
                for line in proc.stdout:
                    idle_once(log.append, line.rstrip("\n"))
            code = proc.wait()
        except Exception as exc:
            idle_once(log.append, "Ошибка запуска: %s" % exc)
            code = 127
        idle_once(log.append, "— код выхода: %d" % code)
        if on_done is not None:
            idle_once(on_done, code)

    threading.Thread(target=worker, daemon=True).start()


def background(func, *args, on_done=None):
    """Выполняет функцию в потоке, результат отдаёт в главный поток.

    on_done получает результат func или исключение — так приложение может
    показать ошибку, а не молча оставить интерфейс в состоянии «…».
    """
    def worker():
        try:
            result = func(*args)
        except Exception as exc:  # noqa: BLE001 — ошибку покажет on_done
            result = exc
        if on_done is not None:
            idle_once(on_done, result)

    threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- диалоги

def info(parent, text, title="MVS OS"):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=title,
    )
    dialog.format_secondary_text(text)
    dialog.run()
    dialog.destroy()


def error(parent, text, title="Ошибка MVS OS"):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
    )
    dialog.format_secondary_text(text)
    dialog.run()
    dialog.destroy()


def confirm(parent, text, title="Подтверждение"):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.OK_CANCEL,
        text=title,
    )
    dialog.format_secondary_text(text)
    ok_button = dialog.get_widget_for_response(Gtk.ResponseType.OK)
    if ok_button is not None:
        ok_button.get_style_context().add_class("danger")
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.OK


# --------------------------------------------------------------------------- окно

class MvsWindow(Gtk.Window):
    """Окно MVS: шапка, боковое меню, страницы."""

    def __init__(self, title, subtitle="", width=1020, height=700, icon=APP_ICON):
        super().__init__(title=title)
        self.set_default_size(width, height)
        self.set_icon_name(icon)
        self.set_position(Gtk.WindowPosition.CENTER)
        apply_theme()

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(title)
        if subtitle:
            header.set_subtitle(subtitle)
        self.set_titlebar(header)
        self.header = header

        self.body = hbox(0)
        self.sidebar = Gtk.ListBox()
        self.sidebar.get_style_context().add_class("mvs-sidebar")
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)

        side_scroll = Gtk.ScrolledWindow()
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_scroll.set_size_request(236, -1)
        side_scroll.add(self.sidebar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)

        self.body.pack_start(side_scroll, False, False, 0)
        self.body.pack_start(self.stack, True, True, 0)
        self.add(self.body)

        self.sidebar.connect("row-selected", self._on_select)
        self._first_row = None
        self._rows = {}

    def add_page(self, key, title, icon=None, widget=None, group=None):
        item = Gtk.ListBoxRow()
        item.key = key
        inner = hbox(12)
        inner.set_margin_start(14)
        inner.set_margin_end(12)
        inner.set_margin_top(9)
        inner.set_margin_bottom(9)
        if icon:
            inner.pack_start(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0
            )
        inner.pack_start(label(title, "mvs-nav"), True, True, 0)
        item.add(inner)
        item.show_all()
        self.sidebar.add(item)
        self._rows[key] = item

        if widget is None:
            widget = Gtk.Label(label=title)
        self.stack.add_named(widget, key)
        if self._first_row is None:
            self._first_row = item
        return item

    def _on_select(self, _listbox, item):
        if item is not None:
            self.stack.set_visible_child_name(item.key)

    def select(self, key):
        item = self._rows.get(key)
        if item is not None:
            self.sidebar.select_row(item)

    def run(self):
        if self._first_row is not None:
            self.sidebar.select_row(self._first_row)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        Gtk.main()


def open_path(target):
    run(["xdg-open", target], timeout=5)
