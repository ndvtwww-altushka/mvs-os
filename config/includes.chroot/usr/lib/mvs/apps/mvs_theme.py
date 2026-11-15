#!/usr/bin/env python3
"""mvs-theme — переключение темы MVS из командной строки.

    mvs-theme            показать текущую тему
    mvs-theme dark       тёмная Aurora Night
    mvs-theme light      светлая Aurora Day
    mvs-theme toggle     переключить

Тема применяется к XFCE (xsettings, xfwm4), GTK и приложениям MVS.
"""

import sys

sys.path.insert(0, "/usr/lib/mvs")

import mvsui as ui  # noqa: E402


def usage(code=0):
    print(__doc__.strip())
    return code


def main(argv):
    if len(argv) > 1 and argv[1] in ("-h", "--help", "help"):
        return usage(0)

    command = argv[1] if len(argv) > 1 else "status"
    current = ui.theme_mode()

    if command == "status":
        print("MVS OS %s — тема: %s" % (ui.VERSION, current))
        return 0

    if command == "toggle":
        command = "light" if current == "dark" else "dark"

    if command not in ("dark", "light"):
        print("Неизвестный аргумент: %s\n" % command, file=sys.stderr)
        return usage(2)

    mode = ui.set_theme(command)
    print("Тема: %s" % ("светлая Aurora Day" if mode == "light" else "тёмная Aurora Night"))
    print("Приложения MVS подхватят тему при следующем запуске.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
