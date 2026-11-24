#!/usr/bin/env python3
"""Draws a simple thumbnail for a package that has no screenshot, and lists
it in the manifest's previews.

    python3 tools/thumbnail.py plugins/<id> [--style pill|layers]

  pill    the package's name in a bar module on a bar strip (the default)
  layers  stacked hills, for wallpapers and anything layered

It writes thumbnail.svg into the package folder. A real screenshot is nicer
but not required: this keeps every package with a picture.
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

# The shell's own dark palette, so thumbnails sit with the screenshots.
BAR = "#0d0f0c"
PILL = "#1e201b"
ACCENT = "#a8d08d"
TEXT = "#e2e3da"
MUTED = "#8d9286"


def pill(name: str) -> str:
    """A bar strip with one module: a ring and the plugin's name."""
    width, height = 800, 96
    label = escape(name)
    text_width = 11 * len(name)
    pill_width = 70 + text_width
    x = (width - pill_width) / 2
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="{BAR}"/>
  <rect x="{x:.0f}" y="24" width="{pill_width:.0f}" height="48" rx="24" fill="{PILL}"/>
  <circle cx="{x + 30:.0f}" cy="48" r="13" fill="none" stroke="{MUTED}" stroke-opacity="0.35" stroke-width="3"/>
  <path d="M {x + 30:.0f} 35 A 13 13 0 0 1 {x + 43:.0f} 48" fill="none" stroke="{ACCENT}" stroke-width="3" stroke-linecap="round"/>
  <text x="{x + 54:.0f}" y="54" font-family="Google Sans Flex, Rubik, sans-serif" font-size="18" font-weight="600" fill="{TEXT}">{label}</text>
</svg>
'''


def layers(name: str) -> str:
    """Hills in layers, back to front, under a sky: a wallpaper."""
    width, height = 800, 450
    hills = [
        ("#2d4f1d", 0.55, "M0 260 C 140 200, 260 230, 380 210 S 640 190, 800 240 L 800 450 L 0 450 Z"),
        ("#3d6b28", 0.75, "M0 310 C 120 270, 250 300, 400 280 S 650 260, 800 300 L 800 450 L 0 450 Z"),
        ("#5a8a3a", 0.9, "M0 360 C 150 330, 300 370, 450 345 S 680 330, 800 360 L 800 450 L 0 450 Z"),
        ("#a8d08d", 1.0, "M0 410 C 160 395, 320 425, 480 405 S 700 395, 800 412 L 800 450 L 0 450 Z"),
    ]
    paths = "\n".join(f'  <path d="{d}" fill="{colour}" fill-opacity="{opacity}"/>' for colour, opacity, d in hills)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#11140f"/>
      <stop offset="1" stop-color="#253b18"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#sky)"/>
  <circle cx="610" cy="120" r="46" fill="{ACCENT}" fill-opacity="0.85"/>
{paths}
  <text x="40" y="70" font-family="Rubik, sans-serif" font-size="30" font-weight="700" fill="{TEXT}">{escape(name)}</text>
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder")
    parser.add_argument("--style", choices=["pill", "layers"], default="pill")
    args = parser.parse_args()
    manifest_path = os.path.join(args.folder, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as error:
        sys.exit(f"can't read {manifest_path}: {error}")
    svg = (layers if args.style == "layers" else pill)(manifest.get("name") or manifest.get("id", "plugin"))
    with open(os.path.join(args.folder, "thumbnail.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    previews = manifest.setdefault("previews", [])
    if "thumbnail.svg" not in previews:
        previews.append("thumbnail.svg")
        # Keep previews next to the other descriptive fields.
        ordered = {}
        for key, value in manifest.items():
            if key == "previews":
                continue
            ordered[key] = value
            if key == "tags":
                ordered["previews"] = previews
        ordered.setdefault("previews", previews)
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {os.path.join(args.folder, 'thumbnail.svg')}")


if __name__ == "__main__":
    main()
