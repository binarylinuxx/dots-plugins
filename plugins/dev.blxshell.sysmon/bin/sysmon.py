#!/usr/bin/env python3
"""System monitor backend: measures CPU, memory and temperature for the
plugin's Facet views (plugin.facet), which draw them.

blxshell plugin protocol, api 2: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import glob
import json
import os
import sys
import threading
import time

lock = threading.Lock()
wake = threading.Event()
store = {}


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    send(type="log", message=text)


_last_cpu = None
_last_percent = 0.0


def cpu_percent():
    """Busy share of all CPU time since the last real sample, 0..100."""
    global _last_cpu, _last_percent
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    total = sum(fields[:8])
    if _last_cpu is not None and total - _last_cpu[1] < 5 * (os.cpu_count() or 1):
        return _last_percent
    previous, _last_cpu = _last_cpu, (idle, total)
    if previous is not None:
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


def _temperature_paths():
    """The CPU package sensor: a known hwmon driver, else every thermal zone."""
    found = {}
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hwmon, "name")) as f:
                found[f.read().strip()] = hwmon
        except OSError:
            continue
    for name in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal"):
        if name in found and os.path.exists(os.path.join(found[name], "temp1_input")):
            return [os.path.join(found[name], "temp1_input")]
    return glob.glob("/sys/class/thermal/thermal_zone*/temp")


_temp_paths = None


def temperature():
    global _temp_paths
    if _temp_paths is None:
        _temp_paths = _temperature_paths()
    readings = [t for t in (_read_milli(p) for p in _temp_paths) if t is not None]
    return max(readings) if readings else None


def report():
    cpu = cpu_percent()
    used, total, percent = memory()
    degrees = temperature()
    with open("/proc/loadavg") as f:
        load = f.read().split()[0]
    send(type="state", state={
        "cpu": round(cpu, 1),
        "cpu_text": f"{cpu:.0f}%",
        "load": load,
        "memory": round(percent, 1),
        "memory_text": f"{percent:.0f}%",
        "memory_detail": f"{used:.1f}/{total:.0f}G",
        "temperature": round(degrees, 1) if degrees is not None else 0,
        "temperature_text": f"{degrees:.0f}°C" if degrees is not None else "n/a",
        "temperature_detail": f"{degrees * 9 / 5 + 32:.0f}°F" if degrees is not None else "n/a",
    })


def interval():
    value = store.get("interval", 2)
    return min(max(value, 0.5), 60) if isinstance(value, (int, float)) else 2


def ticker():
    cpu_percent()
    time.sleep(0.5)  # a first sample, so the first reading means something
    while True:
        try:
            report()
        except Exception as error:  # a sensor going away must not end it
            log(f"reading failed: {error}")
        wake.wait(interval())
        wake.clear()


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        if kind in ("hello", "store"):
            store.clear()
            store.update(message.get("store") or {})
            if not started:
                started = True
                threading.Thread(target=ticker, daemon=True).start()
            wake.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
