#!/usr/bin/env python3
"""Builds every package in list.json into a .blx, plus index.json.

    python3 tools/build.py [--out build] [--base-url URL]

A .blx is a zstd-compressed tar with manifest.json at its root, the same as
`blxshell pack` makes. Entries are sorted and their times, owners and modes
normalised, so the same folder always gives the same bytes (and the same
sha256 in the index).

index.json is what `blxshell install <id>` and `blxshell search` read:

    {
      "schema": 1,
      "name": "...",
      "repository": "owner/name",
      "packages": [
        { "id", "type", "name", "version", "description", "compositors",
          "permissions", "blxshell", "tags", "previews",
          "file", "url", "sha256", "size" }
      ]
    }

`url` is where the file is published: base-url + file. The release workflow
uploads everything in the output folder to the "packages" release, so the
default base is that release's download address.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def compress(data: bytes) -> bytes:
    try:
        from compression import zstd  # Python 3.14+
        return zstd.compress(data, level=19)
    except ImportError:
        if not shutil.which("zstd"):
            sys.exit("need the zstd command (or Python 3.14+)")
        return subprocess.run(["zstd", "-19", "-q", "-c"], input=data, capture_output=True, check=True).stdout


def pack(folder: str) -> bytes:
    """The folder as a reproducible tar.zst."""
    paths = []
    for directory, folders, files in os.walk(folder):
        folders[:] = sorted(f for f in folders if f != "__pycache__")
        for name in folders + files:
            full = os.path.join(directory, name)
            if name.endswith(".pyc"):
                continue
            if os.path.islink(full):
                sys.exit(f"{full} is a symlink; packages hold only files and folders")
            paths.append(full)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for full in sorted(paths, key=lambda p: os.path.relpath(p, folder)):
            relative = os.path.relpath(full, folder).replace(os.sep, "/")
            info = tar.gettarinfo(full, arcname=relative + ("/" if os.path.isdir(full) else ""))
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if info.isdir():
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.mode = 0o755 if os.access(full, os.X_OK) else 0o644
                with open(full, "rb") as f:
                    tar.addfile(info, f)
    return compress(buffer.getvalue())


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "binarylinuxx/dots-plugins")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "build"))
    parser.add_argument("--base-url", default=f"https://github.com/{repository}/releases/download/packages/")
    parser.add_argument("--raw-url", default=f"https://raw.githubusercontent.com/{repository}/main/")
    args = parser.parse_args()

    with open(os.path.join(ROOT, "list.json"), encoding="utf-8") as f:
        listing = json.load(f)
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)

    index = {"schema": 1, "name": listing.get("name", repository), "repository": repository, "packages": []}
    for entry in listing["packages"]:
        folder = os.path.join(ROOT, entry["path"])
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        file = f"{manifest['id']}-{manifest['version']}.blx"
        data = pack(folder)
        with open(os.path.join(args.out, file), "wb") as f:
            f.write(data)
        plugin = manifest.get("plugin") or {}
        index["packages"].append({
            "id": manifest["id"],
            "type": manifest["type"],
            "name": manifest["name"],
            "version": manifest["version"],
            "description": manifest.get("description", ""),
            "compositors": manifest.get("compositors", []),
            "permissions": plugin.get("permissions", []),
            "blxshell": manifest.get("blxshell", ""),
            "tags": manifest.get("tags", []),
            "previews": [args.raw_url + entry["path"] + "/" + p for p in manifest.get("previews", [])],
            "file": file,
            "url": args.base_url + file,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
        print(f"{file}  {len(data)} bytes")

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"index.json  {len(index['packages'])} package(s)")


if __name__ == "__main__":
    main()
