# wikilens demo tape — charmbracelet/vhs
# =============================================================================
# WHAT THIS IS
#   A reproducible recording script for the wikilens demo GIF. It records the
#   `wikilens audit` command, which is a pure-function graph scan: it runs
#   instantly, fully OFFLINE, with NO model download and NO API key required.
#   That makes it the ideal demo: fast to render and safe to run anywhere.
#
# HOW TO RENDER
#   1. Install vhs (assumes vhs v0.11.0):   https://github.com/charmbracelet/vhs
#        macOS:    brew install vhs
#        Linux:    see release assets at the URL above
#        Go:       go install github.com/charmbracelet/vhs@latest
#      vhs also needs ttyd and ffmpeg on PATH (the install docs cover both).
#   2. Install wikilens so the `wikilens` console script is on PATH:
#        pip install -e .         # from a clone of this repo, OR
#        pip install wikilens     # from PyPI
#   3. From the repo root (so `fixtures/audit_vault` resolves), run:
#        vhs demo.tape
#      This writes demo.gif next to this file.
#
# WINDOWS NOTE
#   On native Windows 11 vhs is awkward: it depends on ttyd, which has no
#   first-class Windows build, so vhs effectively wants WSL or a container.
#   The committed demo.gif was recorded on native Windows with OBS and converted
#   to GIF with ffmpeg (palettegen/paletteuse). ScreenToGif also works. Use
#   whichever records the `wikilens audit fixtures/audit_vault` run cleanly;
#   the GIF is what matters, and this tape documents the canonical command.
# =============================================================================

# Where should we write the GIF?
Output demo.gif

# Terminal sizing and styling for a crisp, readable recording.
Set Width 1200
Set Height 600
Set FontSize 22
Set Padding 24
Set TypingSpeed 60ms
Set Theme "Catppuccin Mocha"

# Let the terminal settle before we start typing.
Sleep 1s

# Type the demo command (fast, offline, no API key, no model download).
Type "wikilens audit fixtures/audit_vault"

# Brief pause so the viewer can read the command before it runs.
Sleep 800ms

# Run it.
Enter

# The audit is a pure graph scan and returns almost instantly; hold on the
# markdown report (16 notes, 19 findings) long enough to read it.
Sleep 6s
