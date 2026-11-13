#!/usr/bin/env bash
# Prints "ok" when a one-line `claude -p` call on the pinned model reports ONLY that model, on the expected window, at the
# pinned effort; otherwise prints what it got. Background calls are pinned too (ANTHROPIC_DEFAULT_HAIKU_MODEL /
# ANTHROPIC_SMALL_FAST_MODEL), so a "haiku" helper call shows up here as a second model and fails the check.
#   preflight.sh            the code pin (reads loop.conf from this folder)
#   preflight.sh plan       the plan pin: PLAN_MODEL, PLAN_MODEL_ARG, PLAN_EFFORT (a design branch's sessions)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
[ "${1:-code}" = plan ] && { MODEL="$PLAN_MODEL"; MODEL_ARG="$PLAN_MODEL_ARG"; EFFORT="$PLAN_EFFORT"; }
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL" ANTHROPIC_SMALL_FAST_MODEL="$MODEL"
mkdir -p "$HERE/state"
out=$(mktemp "$HERE/state/preflight.XXXXXX")   # private: chains waking together must not read each other's probe
# (no suffix after the X's: BSD mktemp randomises only trailing X's, so on macOS two preflights would share one file)
trap 'rm -f "$out"' EXIT
(cd "$HERE" && claude -p --model "$MODEL_ARG" --effort "$EFFORT" --strict-mcp-config \
    --output-format json --no-session-persistence <<< "Reply with the single word READY." > "$out" 2>/dev/null)
MODEL="$MODEL" CTX_WINDOW="$CTX_WINDOW" "$PYTHON" - "$out" <<'EOF'
import json, os, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf8"))
except (OSError, ValueError) as e:
    print(f"unreadable output: {e}"); sys.exit()
mu = d.get("modelUsage") or {}
bad = [k for k, v in mu.items() if v.get("canonicalModel") != os.environ["MODEL"]]
win = sorted({v.get("contextWindow") for v in mu.values()})
result = (d.get("result") or "").strip()
ok = result.upper().startswith("READY") and mu and not bad and win == [int(os.environ["CTX_WINDOW"])]
print("ok" if ok else f"models={list(mu)} windows={win} result={result[:80]!r}")
EOF
