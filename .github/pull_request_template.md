<!-- Adding or updating a plugin or theme? -->

- [ ] One folder under `plugins/` or `themes/`, named after the id, listed in `list.json`
- [ ] `python3 tools/validate.py` and `python3 tools/build.py` pass
- [ ] A plugin has a `screenshot.png` of it in the bar, listed in `previews`
- [ ] `permissions` lists only what it uses, and all of it
- [ ] No compiled binaries or archives: compiled plugins commit source and a `build.sh`
- [ ] An update bumps `version`

What it does, and anything reviewers should look at closely:
