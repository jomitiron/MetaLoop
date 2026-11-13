#!/usr/bin/env bash
# Waits for a branch's gate to finish and prints the verdict with every suite's line (PASS, FAIL, or the process gone).
#   wait_gate.sh <slug>          (start the gate first: cd <worktree> && python <run>/gate.py --start)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
cd "$WT_ROOT/$1" || { echo "no worktree for $1"; exit 2; }
sleep 20
deadline=$(( $(date +%s) + ${WAIT_HOURS:-3} * 3600 ))   # a full gate takes 20-40 minutes; a hung build or slot never ends
until "$PYTHON" "$HERE/gate.py" --status 2>&1 | grep -aqiE "^gate (PASS|FAIL)|process gone|no gate run|did not start"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "TIMEOUT after ${WAIT_HOURS:-3}h, gate still running. Status, slot owners and the last log lines:"
        "$PYTHON" "$HERE/gate.py" --status; ls "$HERE/locks" 2>/dev/null; cat "$HERE"/locks/*/owner 2>/dev/null
        tail -n 5 .fixloop/logs/gate-*.log 2>/dev/null | tail -n 20; exit 3
    fi
    sleep 60
done
echo "== $1"; "$PYTHON" "$HERE/gate.py" --status
