#!/usr/bin/env bash
# Compiles the glass shader into lib/glass.vws with vw-shaderc, from the vw
# blxshell itself is built with (its flake's lock), and glslc from its
# toolchain. CI runs it through tools/build.py; locally, BLXSHELL_FLAKE=~/dots
# builds against a checkout.
set -euo pipefail
flake=${BLXSHELL_FLAKE:-github:binarylinuxx/dots}
vw=$(nix build --no-link --print-out-paths --inputs-from "$flake" vw)
mkdir -p lib
nix develop "$flake#default.devShell" --command "$vw/bin/vw-shaderc" shaders/glass.comp -o lib/glass.vws
