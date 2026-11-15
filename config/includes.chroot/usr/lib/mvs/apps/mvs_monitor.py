#!/usr/bin/env python3
"""MVS Monitor — процессор, память, диски, сеть и процессы в реальном времени."""

import os
import re
import sys
from collections import deque

sys.path.insert(0, "/usr/lib/mvs")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import cairo  # noqa: E402,F401
import mvsui as ui  # noqa: E402

HISTORY = 120


def read(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def meminfo():
    data = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        try:
            data[key] = float(rest.strip().split()[0]) * 1024.0
        except (ValueError, IndexError):
            pass
    return data


class Graph(Gtk.DrawingArea):
    def __init__(self, color, height=110):
        super().__init__()
        self.set_size_request(-1, height)
        self.values = deque(maxlen=HISTORY)
        self.color = color
        self.connect("draw", self.on_draw)

    def push(self, value):
        self.values.append(max(0.0, min(100.0, float(value))))
        self.queue_draw()

    def on_draw(self, _widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        dark = ui.theme_mode() == "dark"

        cr.set_source_rgba(0.0, 0.0, 0.0, 0.35 if dark else 0.05)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        cr.set_line_width(1)
        cr.set_source_rgba(0.6, 0.65, 0.75, 0.18 if dark else 0.25)
        for index in range(1, 4):
            y = height * index / 4.0
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

        if len(self.values) < 2:
            return

        red, green, blue = self.color
        step = width / float(HISTORY - 1)
        offset = HISTORY - len(self.values)
        points = [
            ((offset + index) * step, height - (value / 100.0) * height)
            for index, value in enumerate(self.values)
        ]

        # Заливка под графиком. Путь строится заново: stroke() очищает
        # текущий путь, и line_to после него начинал бы треугольник от (0,0).
        cr.move_to(points[0][0], height)
        for point in points:
            cr.line_to(point[0], point[1])
        cr.line_to(points[-1][0], height)
        cr.close_path()
        cr.set_source_rgba(red, green, blue, 0.16)
        cr.fill()

        # Сама линия — поверх заливки.
        cr.set_line_width(2.0)
        cr.set_source_rgb(red, green, blue)
        cr.move_to(points[0][0], points[0][1])
        for point in points[1:]:
            cr.line_to(point[0], point[1])
        cr.stroke()


class Monitor(ui.MvsWindow):
    def __init__(self):
        super().__init__("MVS Monitor", "Ресурсы и процессы", 960, 700, "mvs-monitor")

        self.prev_cpu = self.cpu_sample()
        self.prev_net = self.net_sample()
        self.graph_cpu = Graph((0.478, 0.635, 0.968))
        self.graph_ram = Graph((0.619, 0.807, 0.415))
        self.graph_net = Graph((0.878, 0.686, 0.407))

        self.stat_cpu = ui.label("—", "mvs-big")
        self.stat_ram = ui.label("—", "mvs-big")
        self.stat_net = ui.label("—", "mvs-big")
        self.stat_load = ui.label("—", "mvs-subtle")

        res_cpu = ui.label("—", "mvs-subtle")
        res_ram = ui.label("—", "mvs-subtle")
        self.res_cpu = res_cpu
        self.res_ram = res_ram

        self.disk_label = ui.subtle("—")
        self.cpu_model_label = ui.subtle("—")

        self.store = Gtk.ListStore(int, float, float, str)
        self.tree = Gtk.TreeView(model=self.store)
        for index, (title, width) in enumerate(
            (("PID", 90), ("CPU %", 90), ("MEM %", 90), ("Процесс", 320))
        ):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_resizable(True)
            column.set_min_width(width)
            self.tree.append_column(column)
        self.tree.set_hexpand(True)
        self.tree.set_vexpand(True)

        kill_button = ui.button("Завершить процесс", self.kill_selected, "mvs-button danger")

        page = ui.page(
            ui.h1("MVS Monitor"),
            ui.subtle("Данные берутся из /proc каждую секунду"),
            ui.card(
                ui.row("Процессор", self.cpu_model_label, self.stat_cpu),
                self.graph_cpu,
                ui.row("Нагрузка", self.stat_load, res_cpu),
            ),
            ui.card(
                ui.row("Память", None, self.stat_ram),
                self.graph_ram,
                res_ram,
            ),
            ui.card(
                ui.row("Сеть", None, self.stat_net),
                self.graph_net,
                self.disk_label,
            ),
            ui.card(
                ui.h2("Процессы"),
                ui.scrolled(self.tree, 260),
                kill_button,
            ),
        )
        self.add_page("monitor", "Монитор", "utilities-system-monitor", page)

        self.refresh()
        GLib.timeout_add(1000, self.tick)

    # -- замеры -------------------------------------------------------------

    def cpu_sample(self):
        fields = read("/proc/stat").splitlines()
        if not fields:
            return (0, 0)
        values = []
        for part in fields[0].split()[1:]:
            try:
                values.append(int(part))
            except ValueError:
                values.append(0)
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def cpu_model(self):
        for line in read("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
        return "—"

    def net_sample(self):
        received = sent = 0
        for line in read("/proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() == "lo":
                continue
            parts = rest.split()
            if len(parts) >= 9:
                received += int(parts[0])
                sent += int(parts[8])
        return received, sent

    def tick(self):
        self.refresh()
        return True

    def refresh(self):
        total, idle = self.cpu_sample()
        prev_total, prev_idle = self.prev_cpu
        delta_total = total - prev_total
        delta_idle = idle - prev_idle
        cpu = 0.0
        if delta_total > 0:
            cpu = 100.0 * (delta_total - delta_idle) / delta_total
        self.prev_cpu = (total, idle)

        mem = meminfo()
        mem_total = mem.get("MemTotal", 0)
        mem_used = mem_total - mem.get("MemAvailable", 0)
        ram = (mem_used / mem_total * 100.0) if mem_total else 0.0

        received, sent = self.net_sample()
        prev_rx, prev_tx = self.prev_net
        self.prev_net = (received, sent)
        rate = (received - prev_rx) + (sent - prev_tx)

        self.graph_cpu.push(cpu)
        self.graph_ram.push(ram)
        self.graph_net.push(min(100.0, rate / 1024.0 / 1024.0))  # МБ/с как шкала

        self.stat_cpu.set_text("%.0f%%" % cpu)
        self.stat_ram.set_text("%.0f%%" % ram)
        self.stat_net.set_text("%s/с" % ui.human_bytes(rate))
        load = read("/proc/loadavg").split()
        self.stat_load.set_text("средняя: %s" % (load[0] if load else "—"))

        cores = os.cpu_count() or 1
        self.res_cpu.set_text("ядер: %d" % cores)
        self.cpu_model_label.set_text(self.cpu_model())
        self.res_ram.set_text(
            "%s из %s · swap %s"
            % (
                ui.human_bytes(mem_used),
                ui.human_bytes(mem_total),
                ui.human_bytes(mem.get("SwapTotal", 0)),
            )
        )

        try:
            stat = os.statvfs("/")
            total_disk = stat.f_blocks * stat.f_frsize
            free_disk = stat.f_bavail * stat.f_frsize
            self.disk_label.set_text(
                "Диск /: %s свободно из %s" % (ui.human_bytes(free_disk), ui.human_bytes(total_disk))
            )
        except OSError:
            self.disk_label.set_text("Диск: нет данных")

        self.refresh_processes()

    def refresh_processes(self):
        selected = None
        model, row = self.tree.get_selection().get_selected()
        if row is not None:
            selected = model[row][0]

        code, text, _ = ui.run(
            ["ps", "-eo", "pid=,pcpu=,pmem=,comm=", "--sort=-pcpu"], timeout=8
        )
        rows = []
        if code == 0:
            for line in text.splitlines()[:60]:
                parts = line.split(None, 3)
                if len(parts) < 4:
                    continue
                try:
                    rows.append((int(parts[0]), float(parts[1]), float(parts[2]), parts[3][:60]))
                except ValueError:
                    continue

        self.store.clear()
        for row_data in rows:
            self.store.append(list(row_data))

        if selected is not None:
            for index, row_data in enumerate(self.store):
                if row_data[0] == selected:
                    self.tree.get_selection().select_path(Gtk.TreePath.new_from_indices([index]))
                    break

    def kill_selected(self, _button):
        model, row = self.tree.get_selection().get_selected()
        if row is None:
            ui.info(self, "Сначала выберите процесс в списке.")
            return
        pid = model[row][0]
        name = model[row][3]
        if pid <= 1:
            ui.error(self, "Нельзя завершить системный процесс с PID %d." % pid)
            return
        if not ui.confirm(self, "Завершить процесс %s (PID %d)?" % (name, pid)):
            return
        code, _out, err = ui.priv(["kill", "-TERM", str(pid)], timeout=10)
        if code != 0:
            ui.error(self, (err or "не удалось завершить процесс").strip())
        else:
            ui.notify("Процесс %s завершён" % name)


def main():
    Monitor().run()


if __name__ == "__main__":
    main()
