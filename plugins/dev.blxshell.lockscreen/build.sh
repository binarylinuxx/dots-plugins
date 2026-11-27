#!/usr/bin/env bash
# Builds lib/plugin.so with blxshell's own toolchain (the clang and vw the
# released shell is built with), so its ABI tag matches the shell's. CI runs
# it through tools/build.py; locally, BLXSHELL_FLAKE=~/dots builds against a
# checkout.
set -euo pipefail
flake=${BLXSHELL_FLAKE:-github:binarylinuxx/dots}
# The installed blxshell has <blxshell/plugin.hpp>, stamped with its ABI tag.
shell=$(nix build --no-link --print-out-paths "$flake")
mkdir -p lib
nix develop "$flake#default.devShell" --command \
  clang++ -std=c++23 -O2 -fPIC -shared -Wall src/plugin.cpp -o lib/plugin.so -I"$shell/include"
