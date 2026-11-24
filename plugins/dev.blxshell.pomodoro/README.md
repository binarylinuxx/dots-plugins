## Controls

- **Click** to start or pause.
- **Right click** to skip to the next phase.
- **Middle click** to reset.
- **Scroll** while it's stopped to change the focus length.

## Keybinds

```sh
blxshell plugin call dev.blxshell.pomodoro toggle   # also start, pause, skip, reset
```

Its page in **Settings → Plugins** sets the lengths, the rounds before a long
break, auto-start and notifications.

The view is `plugin.facet`; `bin/pomodoro.py` keeps the time and notifies.
