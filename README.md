# blxshell plugins

The official pool of plugins and themes for [blxshell](https://github.com/binarylinuxx/dots).
Everything here is reviewed before it's merged.

![The three plugins in the bar](docs/bar.png)

| | Plugin | |
|---|---|---|
| ![](plugins/dev.blxshell.sysmon/screenshot.png) | [System monitor](plugins/dev.blxshell.sysmon) | CPU, memory or temperature, with a usage ring that turns red past a threshold |
| ![](plugins/dev.blxshell.netspeed/screenshot.png) | [Network speed](plugins/dev.blxshell.netspeed) | Live download and upload rates of the active connection |
| ![](plugins/dev.blxshell.pomodoro/screenshot.png) | [Pomodoro](plugins/dev.blxshell.pomodoro) | A focus timer with breaks, a countdown ring and notifications |

## Installing

Until blxshell reads this repository by itself, make a package from a folder
and install it:

```sh
git clone https://github.com/binarylinuxx/dots-plugins
blxshell pack dots-plugins/plugins/dev.blxshell.pomodoro -o pomodoro.blx
blxshell install pomodoro.blx
```

Then turn it on in **Settings → Plugins**, and place its module in the bar
from the same page.

## Using them

**System monitor**: scroll to switch between CPU, memory and temperature; click
for the detail (load average, GiB used, °F); right click opens the dashboard.
`blxshell plugin call dev.blxshell.sysmon memory` switches from a keybind.

**Network speed**: click or scroll to show both directions, download only or
upload only; right click switches between bytes and bits. Leave the interface
empty to follow the default route.

**Pomodoro**: click to start or pause, right click to skip to the next phase,
middle click to reset, scroll while stopped to change the focus length. For a
keybind: `blxshell plugin call dev.blxshell.pomodoro toggle` (also `start`,
`pause`, `skip`, `reset`).

All three are Python 3 with nothing but the standard library.

## Layout

```text
list.json                        what this repository offers
plugins/<id>/                    one folder per plugin: what its .blx holds
  manifest.json
  screenshot.png
  bin/…
themes/<id>/                     one folder per theme
schema/manifest.schema.json      the manifest format (from blxshell)
tools/validate.py                the checks CI runs
```

`list.json` lists each package's `id` and `path`. Everything else comes from
the package's own `manifest.json`. The format is described on the
[wiki](https://bshell.zapzig.org/plugins/discover/).

## Submitting a plugin or theme

1. Fork, then add your folder under `plugins/` or `themes/`, named after its id
   (reverse-DNS, e.g. `io.github.you.weather`).
2. Add it to `list.json`.
3. For a plugin, include a `screenshot.png` of it in the bar and list it in
   `previews`.
4. Run the checks, and pack it once to be sure blxshell reads it:

   ```sh
   python3 tools/validate.py
   blxshell pack plugins/io.github.you.weather
   ```

5. Open a pull request.

Reviewers look at:

- **Permissions**: does it ask only for what it uses? `shell` and
  `notifications` are enforced by blxshell; the rest are declarations users rely
  on, so they must be truthful.
- **The code**: a plugin runs as the user. No obfuscated or minified code, no
  downloading and running code at runtime, and no network access unless
  declared and needed.
- **Behaviour**: it exits when stdin closes, doesn't spin the CPU, and survives
  a missing sensor, file or connection without crashing.
- **Compositors**: `"any"` only if it really works everywhere.

Updates go through a pull request too: change the folder and bump `version`.

## Custom repositories

Anyone can publish a repository with this layout. Packages from repositories
other than this one aren't reviewed by the blxshell maintainers.

## License

Each package states its own license in its manifest. The three plugins here
are MIT.
