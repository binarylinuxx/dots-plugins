# Glassify

Makes the whole lock screen glass. Every pill, card, widget and the password
sheet refracts the wallpaper behind it through its rounded rim.

Four styles, picked in **Settings → Plugins → Glassify**:

- **Island (multi-pass)**: zwwm's island glass in full, ShojiWM's
  island-refract (MIT, bea4dev). Its 18 passes run in zwwm's order with its
  values (`shaders/island/`). A mask, a jump-flood distance field, smoothing
  and the ridge build the lens, then the refraction draws through it.
- **Liquid (single pass)**: zwwm's glass.frag, the same lens from an exact
  distance field in one pass. It matches Island for these rounded shapes and
  costs far less.
- **Frosted (Kawase)**: zwwm's kawase-glass, a quarter-circle lens over the
  blurred wallpaper.
- **Simple**: Glassify 1.0's plain round rim.

The page sets the lens (refraction, rim width, colour fringe, magnification,
corner shape, edge softness, bend smoothing) and what is behind the glass
(blur, blur radius, brightness). It also has the island glass's highlight and
inner shadow, which are off by default: only refraction until you turn them
up. The defaults are the values of zwwm's glass shaders.

The tint follows the theme, or the backdrop colour picked in the layout editor
or in Settings → Lock screen. Each item's **Background** sets how strongly it
is tinted. Refraction is clearest over a sharp wallpaper: turn off **Blur the
wallpaper** in Settings → Lock screen. Frosted blurs it itself.

`shaders/glass.comp` draws every style, and the island passes are in
`shaders/island/`. `build.sh` compiles them into `lib/`. blxshell draws the
lock screen's backdrops with them (the plugin's `lockMaterial`, with settings
passed as `shader_data`). Island needs a blxshell and vw with named pass
images. Nothing shows at the login screen, which runs no plugins.
