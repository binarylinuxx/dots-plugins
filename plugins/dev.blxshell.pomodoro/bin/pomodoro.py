#!/usr/bin/env python3
"""Pomodoro backend: keeps the time for the plugin's Facet views
(plugin.facet), which draw it, and sends a notification when a phase ends.

Actions from the views: "toggle", "skip", "reset", "longer", "shorter".
The same are commands, for binds: blxshell plugin call dev.blxshell.pomodoro toggle

blxshell plugin protocol, api 2: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import json
import sys
import threading
import time

lock = threading.RLock()  # send() runs inside locked sections too
wake = threading.Event()
store = {}

NAMES = {"focus": "Focus", "short_break": "Short break", "long_break": "Long break"}

timer = {
    "phase": "focus",
    "running": False,
    "started": False,   # this phase has run at all (paused counts)
    "remaining": None,  # seconds left; None until the first hello
    "deadline": None,   # monotonic end time while running
    "round": 1,         # which focus round of the cycle
}


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def setting(key, fallback, low, high):
    value = store.get(key)
    return int(min(max(value, low), high)) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def flag(key, fallback):
    value = store.get(key)
    return value if isinstance(value, bool) else fallback


def length(phase):
    return {
        "focus": setting("focus", 25, 1, 180),
        "short_break": setting("short_break", 5, 1, 60),
        "long_break": setting("long_break", 15, 1, 120),
    }[phase] * 60.0


def remaining():
    if timer["running"] and timer["deadline"] is not None:
        return max(0.0, timer["deadline"] - time.monotonic())
    return timer["remaining"]


def report():
    left = remaining()
    seconds = int(round(left))
    send(type="state", state={
        "phase": timer["phase"],
        "name": NAMES[timer["phase"]],
        "running": timer["running"],
        "started": timer["started"],
        "text": f"{seconds // 60:02d}:{seconds % 60:02d}",
        "progress": left / length(timer["phase"]),
        "round": timer["round"],
        "rounds": setting("rounds", 4, 1, 12),
    })


def next_phase(notify):
    """Moves to the phase after this one; called with the lock held."""
    if timer["phase"] == "focus":
        timer["phase"] = "long_break" if timer["round"] >= setting("rounds", 4, 1, 12) else "short_break"
    else:
        timer["round"] = 1 if timer["phase"] == "long_break" else timer["round"] + 1
        timer["phase"] = "focus"
    timer["remaining"] = length(timer["phase"])
    timer["running"] = timer["started"] = flag("auto_start", False)
    timer["deadline"] = time.monotonic() + timer["remaining"] if timer["running"] else None
    if notify and flag("notify", True):
        rounds = setting("rounds", 4, 1, 12)
        body = {
            "focus": f"Round {timer['round']} of {rounds}.",
            "short_break": f"{setting('short_break', 5, 1, 60)} minutes. Stand up, look away from the screen.",
            "long_break": f"{setting('long_break', 15, 1, 120)} minutes. You finished {rounds} rounds.",
        }[timer["phase"]]
        if not timer["running"]:
            body += " Click the timer to start."
        threading.Thread(target=send, kwargs={"type": "notify", "summary": NAMES[timer["phase"]], "body": body},
                         daemon=True).start()


def toggle():
    if timer["running"]:
        timer["remaining"] = remaining()
        timer["running"], timer["deadline"] = False, None
    else:
        timer["running"] = timer["started"] = True
        timer["deadline"] = time.monotonic() + timer["remaining"]


def reset():
    timer.update(phase="focus", running=False, started=False, remaining=length("focus"), deadline=None, round=1)


def act(name):
    if name == "toggle":
        toggle()
    elif name == "start" and not timer["running"]:
        toggle()
    elif name == "pause" and timer["running"]:
        toggle()
    elif name == "skip":
        next_phase(notify=False)
    elif name == "reset":
        reset()
    elif name in ("longer", "shorter") and not timer["started"] and timer["phase"] == "focus":
        # Scrolling the idle timer changes the focus length, kept in the store.
        minutes = setting("focus", 25, 1, 180) + (5 if name == "longer" else -5)
        minutes = min(max(minutes, 5), 180)
        store["focus"] = minutes
        send(type="set", key="focus", value=minutes)
        timer["remaining"] = length("focus")


def ticker():
    while True:
        with lock:
            if timer["running"] and remaining() <= 0:
                next_phase(notify=True)
            running = timer["running"]
        report()
        wake.wait(1.0 if running else 3600)
        wake.clear()


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        with lock:
            if kind in ("hello", "store"):
                store.clear()
                store.update(message.get("store") or {})
                # A phase not started yet shows the current length.
                if timer["remaining"] is None or not timer["started"]:
                    timer["remaining"] = length(timer["phase"])
            elif kind == "action" and isinstance(message.get("data"), str):
                act(message["data"])
            elif kind == "command":
                act(message.get("name", ""))
        if kind == "hello" and not started:
            started = True
            threading.Thread(target=ticker, daemon=True).start()
        wake.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
