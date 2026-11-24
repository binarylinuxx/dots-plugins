#!/usr/bin/env python3
"""Dynamic wallpaper backend: reads the folder and sends the layers for the
plugin's Wallpaper view (plugin.facet) to draw.

  parallax  images named 0.png, 1.png, 2.png… (any image type): 0 at the back
            stays put, the front one slides the most as you change workspace
  time      images named morning, day, evening and night (any image type),
            crossfading over the half hour before each one begins

blxshell plugin protocol, api 2: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta

lock = threading.Lock()
wake = threading.Event()
store = {}

IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".gif")
# When each image begins; the crossfade into it starts FADE before.
PERIODS = [("morning", 6), ("day", 10), ("evening", 17), ("night", 20)]
FADE = timedelta(minutes=30)


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    send(type="log", message=text)


def folder():
    value = store.get("folder") or "~/.local/wallpapers/layers"
    return os.path.abspath(os.path.expanduser(str(value).strip()))


def images(path):
    try:
        names = os.listdir(path)
    except OSError:
        return []
    return [name for name in names if name.lower().endswith(IMAGES) and not name.startswith(".")]


def parallax_layers(path):
    """Numbered images, back to front, with depths from 0 (still) to 1."""
    def order(name):
        match = re.match(r"(\d+)", name)
        return (int(match.group(1)) if match else 1 << 30, name.lower())
    names = sorted(images(path), key=order)
    count = len(names)
    return [{"path": os.path.join(path, name), "depth": (index / (count - 1)) if count > 1 else 0, "opacity": 1}
            for index, name in enumerate(names)]


def time_layers(path, now):
    """The current period's image, and the next fading in near its start."""
    found = {}
    for name in images(path):
        stem = os.path.splitext(name)[0].lower()
        if stem in dict(PERIODS) and stem not in found:
            found[stem] = os.path.join(path, name)
    periods = [(name, hour) for name, hour in PERIODS if name in found]
    if not periods:
        return []
    if len(periods) == 1:
        return [{"path": found[periods[0][0]], "depth": 0, "opacity": 1}]
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Every start from yesterday to tomorrow, so midnight needs no special case.
    starts = sorted((today + timedelta(days=day, hours=hour), name)
                    for day in (-1, 0, 1) for name, hour in periods)
    current = max((start, name) for start, name in starts if start <= now)
    upcoming = min((start, name) for start, name in starts if start > now)
    layers = [{"path": found[current[1]], "depth": 0, "opacity": 1}]
    left = upcoming[0] - now
    if left < FADE:
        layers.append({"path": found[upcoming[1]], "depth": 0, "opacity": round(1 - left / FADE, 3)})
    return layers


def report():
    path = folder()
    mode = "time" if store.get("mode") == "time" else "parallax"
    layers = time_layers(path, datetime.now()) if mode == "time" else parallax_layers(path)
    if not layers:
        log(f"nothing to show in {path} ({'morning/day/evening/night images' if mode == 'time' else '0.png, 1.png…'})")
    send(type="state", state={"mode": mode, "folder": path, "layers": layers})


def signature():
    path = folder()
    try:
        return (path, store.get("mode"), os.stat(path).st_mtime_ns)
    except OSError:
        return (path, store.get("mode"), None)


def ticker():
    last = None
    last_minute = None
    while True:
        current = signature()
        minute = datetime.now().replace(second=0, microsecond=0)
        # On a change of folder, mode or contents; in time mode also every
        # minute, which moves the crossfade along.
        if current != last or (store.get("mode") == "time" and minute != last_minute):
            last, last_minute = current, minute
            try:
                report()
            except Exception as error:
                log(f"reading {current[0]} failed: {error}")
        wake.wait(5)
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
            wake.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
