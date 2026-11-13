#!/usr/bin/env bash
# Starts a loop (its start.sh) where it can run for days without taking the owner's keyboard focus or dying with the
# orchestrator's session:
#   launch.sh <name> <run>/start.sh [args...]         e.g.  launch.sh "fix-qb wave1" /c/w/qb/start.sh queue-wave1.txt 3
# macOS / Linux: a detached tmux session (watch: tmux attach -t <name>; leave it again with Ctrl-b d), else a detached
#   GNU screen session (ships with macOS). On macOS it runs under `caffeinate -is` so the Mac doesn't sleep under it, and
#   it is refused on battery, where caffeinate can't keep the Mac awake (ALLOW_BATTERY=1 overrides). The lid stays open.
# Windows (Git Bash): a minimised mintty window, the launch SKILL.md has always used.
# Right after it, the orchestrator arms the watcher (wait_verify.sh / wait_chain.sh) as a background task.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/platform.sh"
[ $# -ge 2 ] || { sed -n '2,10p' "$0"; exit 2; }
title="$1"; script="$2"; shift 2
[ -f "$script" ] || { echo "no such script: $script"; exit 2; }
script="$(cd "$(dirname "$script")" && pwd)/$(basename "$script")"

if [ "$PLATFORM" = windows ]; then
    mintty -w min -t "$title" /usr/bin/bash -l "$script" "$@" &
    echo "started in a minimised mintty window: $title"
    exit 0
fi

name=$(printf '%s' "$title" | tr -c 'A-Za-z0-9_-' '-')   # tmux and screen names can't hold dots, colons or spaces
wake=()
if [ "$PLATFORM" = mac ]; then
    if pmset -g batt 2>/dev/null | grep -q "Battery Power" && [ "${ALLOW_BATTERY:-0}" != 1 ]; then
        echo "REFUSED: this Mac is on battery, where caffeinate can't keep it awake, so an unattended run would stall when"
        echo "it sleeps. Plug it in, or rerun with ALLOW_BATTERY=1."
        exit 3
    fi
    wake=(caffeinate -is)
fi
# PATH goes in explicitly: a tmux server started earlier keeps the environment it was started with. Plain `bash`, not
# `bash -l`: a macOS login shell runs path_helper, which moves Homebrew's bin to the end of PATH.
if command -v tmux >/dev/null 2>&1; then
    if tmux has-session -t "=$name" 2>/dev/null; then
        echo "a tmux session named $name is already running (tmux attach -t $name)"; exit 2
    fi
    tmux new-session -d -s "$name" -- env PATH="$PATH" ${wake[@]+"${wake[@]}"} bash "$script" "$@" || exit 1
    echo "started in tmux session '$name' (watch: tmux attach -t $name · leave: Ctrl-b d)"
elif command -v screen >/dev/null 2>&1; then
    screen -dmS "$name" env PATH="$PATH" ${wake[@]+"${wake[@]}"} bash "$script" "$@" || exit 1
    echo "started in screen session '$name' (watch: screen -r $name · leave: Ctrl-a d)"
else
    echo "neither tmux nor screen is installed (brew install tmux); or run 'bash $script $*' in a terminal you leave open"
    exit 2
fi
