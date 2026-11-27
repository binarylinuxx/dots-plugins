# Lock screen widgets

Five widgets for blxshell's lock screen. Place, size and fade them with the
layout editor: **Settings → Lock screen → Edit layout**, then **Add**.

| Widget | Shows |
|---|---|
| Greeting | "Good evening, Alex" by the time of day, and a line of your own under it |
| Message | A card with an icon, a title and a message: who to call if found, a reminder |
| Calendar | This month, today marked; weeks start on Monday or Sunday |
| Countdown | Days until a date (or since it, once it has passed) |
| System | The machine's name, its uptime and, if you like, the kernel |

**Settings → Plugins → Lock screen widgets** sets the name (empty takes the
first name from your account), the greeting's colour, the message and its
icon, the first day of the week, the countdown's date (`YYYY-MM-DD`) and what
it counts to, and whether to show uptime and the kernel.

The widgets are shown only. A locked session takes no clicks from a plugin.
They don't appear on the login screen, which runs no plugins.

`src/plugin.cpp` draws them in C++ (`lib/plugin.so`, built by `build.sh`), and
`plugin.facet` is the settings page. It needs a blxshell with the layout editor
and plugin ABI 4.
