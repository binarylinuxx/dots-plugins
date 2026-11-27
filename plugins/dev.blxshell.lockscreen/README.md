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

Select a widget in the layout editor to set what it shows. The greeting has
your name (empty takes it from your account), a line under it and its colour.
The message has a title, text and icon. The calendar has the first day of the
week, the countdown its date (`YYYY-MM-DD`) and what it counts to, and the
system line has uptime and the kernel. Add a widget twice, or duplicate it
(Ctrl+D), for two with different settings.

Their **Background** slider in the editor sets how solid the card behind them is (100% hides the wallpaper). They take the backdrop colour picked in the editor or in Settings → Lock screen. With a lock material installed (such as Glassify), the cards are drawn in it too. The widgets are shown only. A locked session takes no clicks from a plugin.
They don't appear on the login screen, which runs no plugins.

`src/plugin.cpp` draws them in C++ (`lib/plugin.so`, built by `build.sh`), and
`plugin.facet` is the settings page. It needs a blxshell with the layout editor
and plugin ABI 4.
