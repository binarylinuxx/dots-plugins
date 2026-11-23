#!/usr/bin/env python3
"""Checks the repository the way blxshell and the reviewers need it.

    python3 tools/validate.py

- list.json is well formed, ids are unique, and each path is a folder with a
  manifest.json whose id matches;
- each manifest passes schema/manifest.schema.json (when the jsonschema
  module is installed; CI installs it);
- every file a manifest names exists, and a plugin's program is executable;
- packages hold only regular files and folders (no links), under 64 MiB;
- no folder in plugins/ or themes/ is missing from list.json.

Exits 1 with a list of problems, 0 when everything passes.
"""
import json
import os
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems = []


def problem(where, text):
    problems.append(f"{where}: {text}")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as error:
        problem(os.path.relpath(path, ROOT), f"can't read: {error}")
        return None


def schema_validator():
    try:
        import jsonschema
    except ImportError:
        print("note: jsonschema not installed, skipping schema checks (pip install jsonschema)")
        return None
    schema = load(os.path.join(ROOT, "schema", "manifest.schema.json"))
    return jsonschema.Draft202012Validator(schema) if schema else None


def check_package(entry, validator):
    path = entry.get("path", "")
    where = path or "?"
    folder = os.path.normpath(os.path.join(ROOT, path))
    if not path or path.startswith("/") or ".." in path.split("/") or not folder.startswith(ROOT + os.sep):
        problem("list.json", f"bad path {path!r}")
        return
    if not os.path.isdir(folder):
        problem("list.json", f"{path} is not a folder")
        return
    total = 0
    for directory, folders, files in os.walk(folder):
        for name in folders + files:
            full = os.path.join(directory, name)
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode):
                problem(where, f"{os.path.relpath(full, folder)} is a symlink; packages hold only files and folders")
            elif stat.S_ISREG(mode):
                total += os.path.getsize(full)
    if total > 64 << 20:
        problem(where, "larger than 64 MiB")
    manifest = load(os.path.join(folder, "manifest.json"))
    if manifest is None:
        return
    if validator:
        for error in validator.iter_errors(manifest):
            location = "/".join(str(part) for part in error.absolute_path) or "manifest"
            problem(where, f"{location}: {error.message}")
    if manifest.get("id") != entry.get("id"):
        problem(where, f"manifest id {manifest.get('id')!r} doesn't match list.json's {entry.get('id')!r}")
    if os.path.basename(folder) != manifest.get("id"):
        problem(where, "the folder should be named after the id")
    named = list(manifest.get("previews", []))
    if manifest.get("icon"):
        named.append(manifest["icon"])
    program = (manifest.get("plugin") or {}).get("exec") or []
    if program:
        named.append(program[0])
    for relative in named:
        target = os.path.join(folder, relative)
        if not os.path.isfile(target):
            problem(where, f"{relative} is named in the manifest but missing")
    if program and os.path.isfile(os.path.join(folder, program[0])):
        if not os.access(os.path.join(folder, program[0]), os.X_OK):
            problem(where, f"{program[0]} is not executable (git update-index --chmod=+x {path}/{program[0]})")
    if manifest.get("type") == "plugin" and not manifest.get("previews"):
        problem(where, "plugins need a screenshot in previews")


def main():
    listing = load(os.path.join(ROOT, "list.json"))
    if listing is None:
        return 1
    if listing.get("schema") != 1:
        problem("list.json", "schema must be 1")
    if not isinstance(listing.get("name"), str) or not listing["name"]:
        problem("list.json", "name is missing")
    entries = listing.get("packages")
    if not isinstance(entries, list):
        problem("list.json", "packages must be a list")
        entries = []
    validator = schema_validator()
    seen_ids, seen_paths = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("path"), str):
            problem("list.json", f"each package needs an id and a path: {entry!r}")
            continue
        if entry["id"] in seen_ids:
            problem("list.json", f"{entry['id']} is listed twice")
        seen_ids.add(entry["id"])
        seen_paths.add(os.path.normpath(entry["path"]))
        check_package(entry, validator)
    for kind in ("plugins", "themes"):
        base = os.path.join(ROOT, kind)
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if os.path.isdir(os.path.join(base, name)) and os.path.normpath(f"{kind}/{name}") not in seen_paths:
                    problem(f"{kind}/{name}", "not listed in list.json")
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s)")
        return 1
    print(f"ok: {len(entries)} package(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
