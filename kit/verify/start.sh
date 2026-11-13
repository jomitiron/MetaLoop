#!/usr/bin/env bash
# Runs the loop and keeps its window (or tmux session) after it ends, so the last lines stay readable. Start it with
#   <run>/launch.sh "verify-<name>" <run>/start.sh
# (Windows: a minimised mintty window, as `mintty -w min -t "Verify loop <name>" /usr/bin/bash -l <run>/start.sh` always
# was; macOS: a detached tmux session under caffeinate. Never a window that takes focus while the owner is signing in
# elsewhere: it sends their keystrokes to the wrong place.)
cd "$(dirname "${BASH_SOURCE[0]}")" && ./qa-loop.sh
echo; read -r -p "Loop ended. Press Enter to close this window."
