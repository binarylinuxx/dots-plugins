#!/usr/bin/env python3
"""System monitor for the blxshell bar: CPU, memory or temperature.

blxshell plugin protocol, api 1: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import glob
import json
import os
import sys
import threading
import time

METRICS = ["cpu", "memory", "temperature"]
ICONS = {"cpu": "developer_board", "memory": "memory_alt", "temperature": "device_thermostat"}

lock = threading.Lock()
wake = threading.Event()
state = {
    "metric": "cpu",
    "detail": False,  # click: percent <-> detail (load average, GiB used, degrees)
    "interval": 2.0,
    "warn": 85.0,
    "warn_temp": 85.0,
    "ring": True,
}


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    print(f"sysmon: {text}", file=sys.stderr, flush=True)


# --- readings -------------------------------------------------------------------

_last_cpu = None
_last_percent = 0.0


def cpu_percent():
    """Busy share of all CPU time since the last real sample, 0..100.

    Calls closer together than a few clock ticks (a click right after a
    reading) return the last value instead of a noisy one."""
    global _last_cpu, _last_percent
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    total = sum(fields[:8])
    if _last_cpu is not None and total - _last_cpu[1] < 5 * (os.cpu_count() or 1):
        return _last_percent
    previous, _last_cpu = _last_cpu, (idle, total)
    if previous is None:
        return _last_percent
    _last_percent = 100.0 * (1 - (idle - previous[0]) / (total - previous[1]))
    return _last_percent


def memory():
    """(used GiB, total GiB, percent): used is what MemAvailable doesn't cover."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0])  # kB
    total = info["MemTotal"]
    used = total - info.get("MemAvailable", info.get("MemFree", 0))
    return used / 1048576, total / 1048576, 100.0 * used / total


def _read_milli(path):
    try:
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _temperature_source():
    """The CPU package sensor: a known hwmon driver, else the hottest thermal zone."""
    preferred = ["coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal"]
    found = {}
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hwmon, "name")) as f:
                found[f.read().strip()] = hwmon
        except OSError:
            continue
    for name in preferred:
        if name in found:
            # temp1 is the package / Tctl reading on these drivers.
            path = os.path.join(found[name], "temp1_input")
            if os.path.exists(path):
                return [path]
    return glob.glob("/sys/class/thermal/thermal_zone*/temp")


_temp_paths = None


def temperature():
    global _temp_paths
    if _temp_paths is None:
        _temp_paths = _temperature_source()
    readings = [t for t in (_read_milli(p) for p in _temp_paths) if t is not None]
    return max(readings) if readings else None


def load_average():
    with open("/proc/loadavg") as f:
        return f.read().split()[0]


# --- module ---------------------------------------------------------------------

def report():
    with lock:
        metric, detail = state["metric"], state["detail"]
        warn, warn_temp, ring = state["warn"], state["warn_temp"], state["ring"]
    cpu = cpu_percent()  # sampled every tick so the next delta is fresh
    progress = None
    if metric == "cpu":
        text = f"{load_average()}" if detail else f"{cpu:.0f}%"
        progress, hot = cpu / 100, cpu >= warn
    elif metric == "memory":
        used, total, percent = memory()
        text = f"{used:.1f}/{total:.0f}G" if detail else f"{percent:.0f}%"
        progress, hot = percent / 100, percent >= warn
    else:
        degrees = temperature()
        if degrees is None:
            send(type="module", id="monitor", icon=ICONS[metric], text="n/a", tone="", progress=None)
            return
        text = f"{degrees * 9 / 5 + 32:.0f}°F" if detail else f"{degrees:.0f}°C"
        progress, hot = min(degrees / 100, 1.0), degrees >= warn_temp
    send(type="module", id="monitor", icon=ICONS[metric], text=text,
         tone="error" if hot else "", progress=progress if ring else None, visible=True)


def ticker():
    # A first CPU sample, so the first reading isn't a meaningless 0 %.
    cpu_percent()
    time.sleep(0.5)
    while True:
        try:
            report()
        except Exception as error:  # a sensor going away must not end the plugin
            log(f"reading failed: {error}")
        wake.wait(state["interval"])
        wake.clear()


def apply_settings(settings):
    with lock:
        if settings.get("metric") in METRICS:
            state["metric"] = settings["metric"]
        for key, low, high in (("interval", 0.5, 60), ("warn", 1, 100), ("warn_temp", 30, 120)):
            value = settings.get(key)
            if isinstance(value, (int, float)):
                state[key] = float(min(max(value, low), high))
        if isinstance(settings.get("ring"), bool):
            state["ring"] = settings["ring"]


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        if kind in ("hello", "settings"):
            apply_settings(message.get("settings") or {})
            if not started:
                started = True
                threading.Thread(target=ticker, daemon=True).start()
        elif kind == "event" and message.get("module") == "monitor":
            if message.get("event") == "scroll":
                step = 1 if message.get("delta", 0) > 0 else -1
                with lock:
                    index = METRICS.index(state["metric"])
                    state["metric"] = METRICS[(index + step) % len(METRICS)]
                    state["detail"] = False
            elif message.get("button") == "right":
                send(type="shell", command=["dashboard", "toggle"])
                continue
            else:
                with lock:
                    state["detail"] = not state["detail"]
        elif kind == "command":
            name = message.get("name")
            with lock:
                if name in METRICS:
                    state["metric"], state["detail"] = name, False
                elif name == "next":
                    state["metric"] = METRICS[(METRICS.index(state["metric"]) + 1) % len(METRICS)]
        wake.set()  # show the change now, not at the next tick


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
