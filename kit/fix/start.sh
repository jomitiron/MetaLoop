#!/usr/bin/env bash
# Runs a runner and keeps its window (or tmux session) after it ends, so the last lines stay readable. Start it with
#   <run>/launch.sh "fix-<name> <what>" <run>/start.sh <queue-file> [MAX_PAR]
# (Windows: a minimised mintty window, as `mintty -w min -t "Fix runner (<what>)" /usr/bin/bash -l <run>/start.sh ...`
# always was; macOS: a detached tmux session under caffeinate. Never a window that takes focus: it steals keystrokes.)
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
QUEUE="${1:-queue.txt}" MAX_PAR="${2:-$(. ./loop.conf; echo "$MAX_PAR")}" ./runner.sh
echo; read -r -p "Runner ended. Press Enter to close this window."
