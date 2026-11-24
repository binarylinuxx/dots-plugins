## Modes

**Parallax**: a folder of layers, cut from one picture, each a full image with
transparency where the layers behind show through:

```text
~/.local/wallpapers/layers/
├── 0.png    the sky, at the back: stays put
├── 1.png    far hills
├── 2.png    near hills
└── 3.png    the foreground: slides the most
```

As you change workspace the layers slide at their own depths, the front ones
furthest, and glide into place.

**Time of day**: a folder with `morning`, `day`, `evening` and `night` images
(any image type). Each starts at 6:00, 10:00, 17:00 and 20:00, crossfading in
over the half hour before.

## Settings

Its page in **Settings → Plugins** sets the mode, the folder (empty is
`~/.local/wallpapers/layers`), how far the layers travel and how long they
glide. With nothing in the folder, your normal wallpaper shows.

`bin/wallpaper.py` reads the folder and works out the crossfade;
`plugin.facet` places the layers. It needs a blxshell with Wallpaper views and
the Parallax component.
