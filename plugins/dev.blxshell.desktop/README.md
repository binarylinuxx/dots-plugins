## Controls

- **Click** an icon for its actions: Open, Open with another app, Show in
  folder, Copy path, Move to trash (Run for app launchers).
- **Double-click** opens it.
- **Drag** to move it; dropping on another icon swaps them.

Put apps on the desktop by linking their launchers:
`ln -s /usr/share/applications/firefox.desktop ~/Desktop/`

Its page in **Settings → Plugins** sets the folder, the sort order, folders
first, hidden files and how many "Open with" apps to offer.

`bin/desktop.py` reads the folder and runs the actions; `plugin.facet` is its
settings page.
