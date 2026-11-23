#!/usr/bin/env python3
"""Network speed for the blxshell bar: download and upload rates.

blxshell plugin protocol, api 1: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import json
import sys
import threading
import time

MODES = ["both", "down", "up"]

lock = threading.Lock()
wake = threading.Event()
state = {
    "interface": "",  # "" follows the default route
    "interval": 1.0,
    "units": "bytes",  # or "bits"
    "mode": "both",
    "hide_idle": False,
    "idle_below": 1024.0,  # bytes per second, both directions
}


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    print(f"netspeed: {text}", file=sys.stderr, flush=True)


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


def read_counters():
    """{interface: (received bytes, sent bytes)}"""
    result = {}
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, data = line.split(":", 1)
            fields = data.split()
            result[name.strip()] = (int(fields[0]), int(fields[8]))
    return result


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


def ticker():
    previous = None
    while True:
        with lock:
            wanted = state["interface"]
            interval, units, mode = state["interval"], state["units"], state["mode"]
            hide_idle, idle_below = state["hide_idle"], state["idle_below"]
        try:
            interface = wanted or default_interface()
            counters = read_counters().get(interface)
            now = time.monotonic()
            if counters is None:
                send(type="module", id="speed", icon="signal_disconnected", text="offline", tone="textMuted", visible=True)
                previous = None
            else:
                if previous and previous[0] == interface and now > previous[1]:
                    elapsed = now - previous[1]
                    down = max(0, counters[0] - previous[2][0]) / elapsed
                    up = max(0, counters[1] - previous[2][1]) / elapsed
                    if mode == "down":
                        icon, text = "download", human(down, units)
                    elif mode == "up":
                        icon, text = "upload", human(up, units)
                    else:
                        icon, text = "swap_vert", f"{human(down, units)} ↓ {human(up, units)} ↑"
                    idle = down + up < idle_below
                    send(type="module", id="speed", icon=icon, text=text,
                         tone="textMuted" if idle else "", visible=not (hide_idle and idle))
                previous = (interface, now, counters)
        except Exception as error:
            log(f"reading failed: {error}")
        wake.wait(interval)
        wake.clear()


def apply_settings(settings):
    with lock:
        if isinstance(settings.get("interface"), str):
            state["interface"] = settings["interface"].strip()
        if isinstance(settings.get("interval"), (int, float)):
            state["interval"] = float(min(max(settings["interval"], 0.5), 30))
        if settings.get("units") in ("bytes", "bits"):
            state["units"] = settings["units"]
        if isinstance(settings.get("hide_idle"), bool):
            state["hide_idle"] = settings["hide_idle"]


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
        elif kind == "event" and message.get("module") == "speed":
            with lock:
                if message.get("event") == "scroll":
                    step = 1 if message.get("delta", 0) > 0 else -1
                    state["mode"] = MODES[(MODES.index(state["mode"]) + step) % len(MODES)]
                elif message.get("button") == "right":
                    state["units"] = "bits" if state["units"] == "bytes" else "bytes"
                else:
                    state["mode"] = MODES[(MODES.index(state["mode"]) + 1) % len(MODES)]
        # No wake here: a rate needs a full interval of counting to mean anything.


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
