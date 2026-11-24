#!/usr/bin/env python3
"""Desktop icons for blxshell: what's in your desktop folder, on the wallpaper.

Click an icon for its actions: open it, open it with another app, show it in
its folder, copy its path, move it to the trash. Double-click opens it.
.desktop launchers show their app's name and icon and run it.

blxshell plugin protocol, api 2: JSON lines on stdin (from the shell) and
stdout (to the shell). Exits when stdin closes.
"""
import configparser
import json
import mimetypes
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime

AREA = "files"
lock = threading.Lock()
wake = threading.Event()
settings = {
    "folder": "",          # "" is the XDG desktop folder (~/Desktop)
    "show_hidden": False,
    "sort": "name",        # name, modified, type
    "folders_first": True,
    "other_apps": 4,       # "Open with" entries per file
}
# id -> what the actions need: path, mime, launcher.
current = {}

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/svg+xml", "image/avif"}
THUMBNAIL_LIMIT = 15 * 1024 * 1024


def send(**message):
    line = json.dumps(message, separators=(",", ":"))
    with lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(text):
    send(type="log", message=text)


# --- places -----------------------------------------------------------------------

def home():
    return os.path.expanduser("~")


def desktop_folder():
    if settings["folder"]:
        return os.path.expanduser(settings["folder"])
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config")
    try:
        with open(os.path.join(config, "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("XDG_DESKTOP_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    return value.replace("$HOME", home())
    except OSError:
        pass
    return os.path.join(home(), "Desktop")


def data_dirs():
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(home(), ".local", "share")
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [data_home] + [d for d in dirs.split(":") if d]


# --- applications -------------------------------------------------------------------

_apps_cache = None


def applications():
    """mime -> [desktop id], and desktop id -> (name, path), from the MIME caches."""
    global _apps_cache
    if _apps_cache is not None:
        return _apps_cache
    by_mime, entries = {}, {}
    for directory in data_dirs():
        apps = os.path.join(directory, "applications")
        try:
            with open(os.path.join(apps, "mimeinfo.cache"), encoding="utf-8") as f:
                for line in f:
                    if "=" not in line or line.startswith("["):
                        continue
                    mime, ids = line.strip().split("=", 1)
                    for app in filter(None, ids.split(";")):
                        if app not in by_mime.setdefault(mime, []):
                            by_mime[mime].append(app)
        except OSError:
            pass
        try:
            names = os.listdir(apps)
        except OSError:
            continue
        for name in names:
            if name.endswith(".desktop") and name not in entries:
                entry = read_desktop_entry(os.path.join(apps, name))
                if entry and not entry["hidden"]:
                    entries[name] = (entry["name"], os.path.join(apps, name))
    _apps_cache = (by_mime, entries)
    return _apps_cache


def read_desktop_entry(path):
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
        section = parser["Desktop Entry"]
    except (configparser.Error, KeyError, OSError, UnicodeDecodeError):
        return None
    return {
        "name": section.get("Name", os.path.basename(path)),
        "icon": section.get("Icon", ""),
        "exec": section.get("Exec", ""),
        "terminal": section.get("Terminal", "false").lower() == "true",
        "hidden": section.get("NoDisplay", "false").lower() == "true" or section.get("Hidden", "false").lower() == "true",
    }


# --- items --------------------------------------------------------------------------

def mime_of(path):
    if os.path.isdir(path):
        return "inode/directory"
    if path.endswith(".desktop"):
        return "application/x-desktop"
    return mimetypes.guess_type(path, strict=False)[0] or "application/octet-stream"


GLYPHS = {"image": "image", "video": "movie", "audio": "music_note", "text": "description", "font": "font_download"}
ARCHIVES = ("zip", "tar", "rar", "7z", "gzip", "bzip", "xz", "zstd", "compressed")


def look(mime):
    """(theme icon names, best first; Material Symbols fallback)"""
    if mime == "inode/directory":
        return ["folder"], "folder"
    top = mime.split("/", 1)[0]
    names = [mime.replace("/", "-")]
    if mime == "application/pdf":
        names.append("x-office-document")
        glyph = "picture_as_pdf"
    elif any(word in mime for word in ARCHIVES):
        names.append("package-x-generic")
        glyph = "folder_zip"
    else:
        glyph = GLYPHS.get(top, "draft")
    names += [f"{top}-x-generic", "text-x-generic"]
    return names, glyph


def make_item(name, path):
    mime = mime_of(path)
    icons, glyph = look(mime)
    label = name
    image = ""
    launcher = None
    actions = []
    if mime == "application/x-desktop":
        launcher = read_desktop_entry(path)
        if launcher:
            label = launcher["name"]
            icon = launcher["icon"]
            if icon.startswith("/"):
                image = icon
            elif icon:
                icons = [icon, "application-x-executable"]
            glyph = "apps"
            actions.append({"id": "run", "label": "Run", "glyph": "play_arrow"})
    elif mime in IMAGE_TYPES:
        try:
            if os.path.getsize(path) <= THUMBNAIL_LIMIT:
                image = path
        except OSError:
            pass
    if not launcher:
        actions.append({"id": "open", "label": "Open", "glyph": "open_in_new"})
        if mime != "inode/directory":
            by_mime, entries = applications()
            for app in by_mime.get(mime, [])[: settings["other_apps"]]:
                if app in entries:
                    actions.append({"id": "with:" + app, "label": f"Open with {entries[app][0]}", "glyph": "apps"})
    actions += [
        {"id": "reveal", "label": "Show in folder", "glyph": "folder_open"},
        {"id": "copy", "label": "Copy path", "glyph": "content_copy"},
        {"id": "trash", "label": "Move to trash", "glyph": "delete", "danger": True},
    ]
    item = {"id": name, "label": label, "icon": icons, "glyph": glyph, "actions": actions}
    if image:
        item["image"] = image
    return item, {"path": path, "mime": mime, "launcher": launcher}


def scan():
    folder = desktop_folder()
    try:
        names = os.listdir(folder)
    except OSError:
        return folder, []
    entries = []
    for name in names:
        if name.startswith(".") and not settings["show_hidden"]:
            continue
        path = os.path.join(folder, name)
        try:
            info = os.stat(path)
        except OSError:
            continue  # a dangling link
        entries.append((name, path, info))
    sort = settings["sort"]
    if sort == "modified":
        entries.sort(key=lambda e: -e[2].st_mtime)
    elif sort == "type":
        entries.sort(key=lambda e: (mime_of(e[1]), e[0].lower()))
    else:
        entries.sort(key=lambda e: e[0].lower())
    if settings["folders_first"]:
        entries.sort(key=lambda e: not os.path.isdir(e[1]))
    return folder, entries


def publish():
    folder, entries = scan()
    items, details = [], {}
    for name, path, _ in entries:
        item, detail = make_item(name, path)
        items.append(item)
        details[name] = detail
    with lock:
        current.clear()
        current.update(details)
    send(type="desktop", id=AREA, items=items)
    return folder


def signature():
    folder = desktop_folder()
    try:
        return (folder, settings["show_hidden"], settings["sort"], settings["folders_first"], settings["other_apps"],
                tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in os.scandir(folder))))
    except OSError:
        return (folder, None)


def watcher():
    last = None
    while True:
        current_signature = signature()
        if current_signature != last:
            last = current_signature
            try:
                publish()
            except Exception as error:
                log(f"scan failed: {error}")
        wake.wait(2)
        wake.clear()


# --- actions --------------------------------------------------------------------------

def detach(argv):
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        return True
    except OSError as error:
        log(f"can't run {argv[0]}: {error}")
        return False


def exec_line(command, files=()):
    """A desktop entry's Exec, with file field codes filled in and the rest dropped."""
    argv = []
    for word in shlex.split(command):
        if word in ("%f", "%u"):
            argv += list(files[:1])
        elif word in ("%F", "%U"):
            argv += list(files)
        elif len(word) == 2 and word.startswith("%"):
            continue
        else:
            argv.append(word.replace("%%", "%"))
    return argv


def launch(entry_path, entry, files=()):
    if shutil.which("gio"):
        return detach(["gio", "launch", entry_path, *files])
    argv = exec_line(entry["exec"], list(files))
    return bool(argv) and detach(argv)


def trash(path):
    if shutil.which("gio"):
        result = subprocess.run(["gio", "trash", path], capture_output=True, text=True)
        if result.returncode == 0:
            return
        log(f"gio trash failed: {result.stderr.strip()}")
    # The freedesktop.org trash in the home folder.
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(home(), ".local", "share")
    files = os.path.join(data_home, "Trash", "files")
    info = os.path.join(data_home, "Trash", "info")
    os.makedirs(files, exist_ok=True)
    os.makedirs(info, exist_ok=True)
    base = name = os.path.basename(path)
    counter = 1
    while os.path.exists(os.path.join(files, name)) or os.path.exists(os.path.join(info, name + ".trashinfo")):
        counter += 1
        stem, dot, extension = base.partition(".")
        name = f"{stem}.{counter}{dot}{extension}" if dot else f"{base}.{counter}"
    with open(os.path.join(info, name + ".trashinfo"), "w", encoding="utf-8") as f:
        f.write("[Trash Info]\n")
        f.write(f"Path={urllib.parse.quote(os.path.abspath(path))}\n")
        f.write(f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    shutil.move(path, os.path.join(files, name))


def reveal(path):
    uri = "file://" + urllib.parse.quote(os.path.abspath(path))
    if shutil.which("gdbus"):
        result = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
             "--object-path", "/org/freedesktop/FileManager1",
             "--method", "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", ""],
            capture_output=True, timeout=5)
        if result.returncode == 0:
            return
    detach(["xdg-open", os.path.dirname(os.path.abspath(path))])


def act(item, action):
    with lock:
        detail = current.get(item)
    if not detail:
        return
    path = detail["path"]
    try:
        if action == "open":
            detach(["xdg-open", path])
        elif action == "run" and detail["launcher"]:
            launch(path, detail["launcher"])
        elif action.startswith("with:"):
            entries = applications()[1]
            app = action[5:]
            if app in entries:
                launch(entries[app][1], read_desktop_entry(entries[app][1]) or {"exec": ""}, [path])
        elif action == "reveal":
            reveal(path)
        elif action == "copy":
            if shutil.which("wl-copy"):
                subprocess.run(["wl-copy", "--", path], timeout=5)
            else:
                log("wl-copy isn't installed: can't copy")
        elif action == "trash":
            trash(path)
            wake.set()  # gone from the desktop now, not in two seconds
    except Exception as error:
        log(f"{action} on {item} failed: {error}")


# --- protocol ---------------------------------------------------------------------------

def apply_settings(values):
    if isinstance(values.get("folder"), str):
        settings["folder"] = values["folder"].strip()
    for key in ("show_hidden", "folders_first"):
        if isinstance(values.get(key), bool):
            settings[key] = values[key]
    if values.get("sort") in ("name", "modified", "type"):
        settings["sort"] = values["sort"]
    if isinstance(values.get("other_apps"), (int, float)):
        settings["other_apps"] = int(min(max(values["other_apps"], 0), 8))


def main():
    started = False
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        if kind in ("hello", "store"):
            apply_settings(message.get("store") or {})
            if not started:
                started = True
                threading.Thread(target=watcher, daemon=True).start()
            wake.set()
        elif kind == "event" and message.get("desktop") == AREA and message.get("event") == "action":
            threading.Thread(target=act, args=(message.get("item", ""), message.get("action", "")), daemon=True).start()
        elif kind == "command":
            if message.get("name") == "refresh":
                global _apps_cache
                _apps_cache = None
                wake.set()
            elif message.get("name") == "open-folder":
                detach(["xdg-open", desktop_folder()])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
