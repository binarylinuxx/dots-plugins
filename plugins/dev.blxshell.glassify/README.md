# Glassify

Makes the whole lock screen liquid glass. Every pill, card, widget and the
password sheet bends the wallpaper behind it through rounded edges, the way
a slab of glass does. It does only refraction: no highlights, rims or glare.

Its page in **Settings → Plugins** sets:

- **Refraction**: how far the edges bend the light, in pixels.
- **Rounded edge**: how wide the curved rim is. Wider looks softer and thicker.
- **Magnification**: how much the middle enlarges what is behind it.

The tint follows the theme. Each item's **Background** in the lock screen
layout editor sets how strongly it is tinted, from clear glass to frosted
colour. Refraction is clearest over a sharp wallpaper: turn off **Blur the
wallpaper** in Settings → Lock screen.

It is one shader, `shaders/glass.comp`, compiled into `lib/glass.vws` by
`build.sh`. blxshell draws the lock screen's backdrops with it (the plugin's
`lockMaterial`). It needs a blxshell with lock materials, and does nothing at
the login screen, which runs no plugins.
