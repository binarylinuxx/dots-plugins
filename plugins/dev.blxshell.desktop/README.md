## Controls

- **Click** an icon for its actions: Open, Open with another app, Show in
  folder, Copy path, Move to trash (Run for app launchers).
- **Double-click** opens it.
- **Drag** to move it; dropping on another icon swaps them.

Put apps on the desktop by linking their launchers:
`ln -s /usr/share/applications/firefox.desktop ~/Desktop/`

Its page in **Settings → Plugins** sets the folder, the sort order, folders
first, hidden files, how many "Open with" apps to offer, and how icons look:

- **Icon shape**: a Material shape each icon sits on, like Android's
  adaptive icons (cookies, clovers, sunny, gem, heart, …). Photos fill the
  shape. Changing it morphs the icons to the new one.
- **Icon colours**: their own, tinted toward the theme's accent, or themed:
  one colour, the accent on its container, like Android's themed icons.

It's a native plugin: `src/plugin.cpp`, built by `build.sh` into
`lib/plugin.so`. Apps (names, icons, launching, "Open with") come from vw's
applications service through the shell, and the folder is watched with
inotify, so changes show at once. `plugin.facet` is its settings page.
