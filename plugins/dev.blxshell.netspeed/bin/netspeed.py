#!/usr/bin/env python3
"""Network speed backend: counts download and upload rates for the plugin's
Facet views (plugin.facet), which draw them.

blxshell plugin protocol, api 2: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import json
import sys
import threading
import time

lock = threading.Lock()
wake = threading.Event()
store = {}
IDLE_BELOW = 1024.0  # bytes per second, both directions


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    send(type="log", message=text)


def read_counters():
    """{interface: (received bytes, sent bytes)}"""
    result = {}
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, data = line.split(":", 1)
            fields = data.split()
            result[name.strip()] = (int(fields[0]), int(fields[8]))
    return result


def default_interface():
    """The interface of the default IPv4 route, else the busiest non-loopback one."""
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return fields[0]
    except OSError:
        pass
    counters = read_counters()
    counters.pop("lo", None)
    return max(counters, key=lambda name: sum(counters[name]), default="")


def human(rate, units):
    """A short rate: "812k", "1.4M", "12M"; bits per second when units is bits."""
    value = rate * 8 if units == "bits" else rate
    suffix = "b" if units == "bits" else "B"
    for unit in ("", "k", "M", "G"):
        if value < 1000 or unit == "G":
            if unit == "":
                return f"{value:.0f}{suffix}"
            return f"{value:.1f}{unit}" if value < 10 else f"{value:.0f}{unit}"
        value /= 1000
    return f"{value:.0f}G"


def setting(key, fallback):
    value = store.get(key)
    return fallback if value is None else value


def ticker():
    previous = None
    while True:
        wanted = str(setting("interface", "")).strip()
        units = "bits" if setting("units", "bytes") == "bits" else "bytes"
        interval = setting("interval", 1)
        interval = min(max(interval, 0.5), 30) if isinstance(interval, (int, float)) else 1
        try:
            interface = wanted or default_interface()
            counters = read_counters().get(interface)
            now = time.monotonic()
            if counters is None:
                send(type="state", state={"offline": True, "idle": True, "down": "", "up": "", "interface": interface})
                previous = None
            else:
                if previous and previous[0] == interface and now > previous[1]:
                    elapsed = now - previous[1]
                    down = max(0, counters[0] - previous[2][0]) / elapsed
                    up = max(0, counters[1] - previous[2][1]) / elapsed
                    send(type="state", state={"offline": False, "idle": down + up < IDLE_BELOW,
                                              "down": human(down, units), "up": human(up, units), "interface": interface})
                previous = (interface, now, counters)
        except Exception as error:
            log(f"reading failed: {error}")
        wake.wait(interval)
        wake.clear()


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("type") in ("hello", "store"):
            store.clear()
            store.update(message.get("store") or {})
            if not started:
                started = True
                threading.Thread(target=ticker, daemon=True).start()
            # No wake: a rate needs a full interval of counting to mean anything.


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
