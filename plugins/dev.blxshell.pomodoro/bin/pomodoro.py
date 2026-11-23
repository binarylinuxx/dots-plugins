#!/usr/bin/env python3
"""Pomodoro timer for the blxshell bar.

Focus, then a short break; every few rounds a long break. Click starts and
pauses, right click skips to the next phase, middle click resets, and
scrolling while stopped changes the focus length.

blxshell plugin protocol, api 1: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import json
import sys
import threading
import time

lock = threading.Lock()
wake = threading.Event()

settings = {
    "focus": 25,         # minutes
    "short_break": 5,
    "long_break": 15,
    "rounds": 4,         # focus rounds before a long break
    "auto_start": False, # start the next phase without a click
    "notify": True,
}

PHASES = {
    "focus": ("Focus", "timer", "primary"),
    "short_break": ("Short break", "coffee", "tertiary"),
    "long_break": ("Long break", "self_improvement", "tertiary"),
}

timer = {
    "phase": "focus",
    "running": False,
    "remaining": 25 * 60.0,  # seconds left in the phase
    "deadline": None,        # monotonic end time while running
    "round": 1,              # which focus round of the cycle
    "started": False,        # this phase has run at all (paused counts)
}


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def length(phase):
    return settings[phase] * 60.0


def remaining():
    if timer["running"] and timer["deadline"] is not None:
        return max(0.0, timer["deadline"] - time.monotonic())
    return timer["remaining"]


def clock(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def report():
    with lock:
        phase, running, left = timer["phase"], timer["running"], remaining()
        total = length(phase)
        fresh = not timer["started"] and phase == "focus" and timer["round"] == 1
    _, icon, tone = PHASES[phase]
    if fresh:
        # Stopped at the start: a quiet idle state.
        send(type="module", id="timer", icon="timer", text=clock(left), tone="textMuted", progress=None, visible=True)
        return
    send(type="module", id="timer", icon=icon if running else "pause_circle",
         text=clock(left), tone=tone if running else "textMuted",
         progress=(left / total) if total > 0 else None, visible=True)


def next_phase(notify):
    """Moves to the phase after this one; called with the lock held."""
    finished = timer["phase"]
    if finished == "focus":
        long_due = timer["round"] >= settings["rounds"]
        timer["phase"] = "long_break" if long_due else "short_break"
    else:
        if finished == "long_break":
            timer["round"] = 1
        else:
            timer["round"] += 1
        timer["phase"] = "focus"
    timer["remaining"] = length(timer["phase"])
    timer["running"] = settings["auto_start"]
    timer["started"] = timer["running"]
    timer["deadline"] = time.monotonic() + timer["remaining"] if timer["running"] else None
    if notify and settings["notify"]:
        name = PHASES[timer["phase"]][0]
        body = {
            "focus": f"Round {timer['round']} of {settings['rounds']}.",
            "short_break": f"{settings['short_break']} minutes. Stand up, look away from the screen.",
            "long_break": f"{settings['long_break']} minutes. You finished {settings['rounds']} rounds.",
        }[timer["phase"]]
        if not timer["running"]:
            body += " Click the timer to start."
        threading.Thread(target=send, kwargs={"type": "notify", "summary": f"{name}", "body": body}, daemon=True).start()


def ticker():
    while True:
        with lock:
            if timer["running"] and remaining() <= 0:
                next_phase(notify=True)
        report()
        with lock:
            running = timer["running"]
        # Once a second while running; idle otherwise until something happens.
        wake.wait(1.0 if running else 3600)
        wake.clear()


def toggle():
    if timer["running"]:
        timer["remaining"] = remaining()
        timer["running"], timer["deadline"] = False, None
    else:
        timer["running"] = timer["started"] = True
        timer["deadline"] = time.monotonic() + timer["remaining"]


def reset():
    timer.update(phase="focus", running=False, remaining=length("focus"), deadline=None, round=1, started=False)


def apply_settings(values):
    for key, low, high in (("focus", 1, 180), ("short_break", 1, 60), ("long_break", 1, 120), ("rounds", 1, 12)):
        value = values.get(key)
        if isinstance(value, (int, float)):
            settings[key] = int(min(max(value, low), high))
    for key in ("auto_start", "notify"):
        if isinstance(values.get(key), bool):
            settings[key] = values[key]
    # A phase not started yet shows the new length; a paused one keeps its time.
    if not timer["started"]:
        timer["remaining"] = length(timer["phase"])


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        with lock:
            if kind in ("hello", "settings"):
                apply_settings(message.get("settings") or {})
            elif kind == "event" and message.get("module") == "timer":
                if message.get("event") == "scroll":
                    if not timer["started"] and timer["phase"] == "focus":
                        step = -1 if message.get("delta", 0) > 0 else 1
                        settings["focus"] = int(min(max(settings["focus"] + step, 1), 180))
                        timer["remaining"] = length("focus")
                elif message.get("button") == "right":
                    next_phase(notify=False)
                elif message.get("button") == "middle":
                    reset()
                else:
                    toggle()
            elif kind == "command":
                name = message.get("name")
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
        if kind == "hello" and not started:
            started = True
            threading.Thread(target=ticker, daemon=True).start()
        wake.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
