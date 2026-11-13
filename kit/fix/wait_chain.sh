#!/usr/bin/env bash
# Waits for the next chain to end, ask the owner a question (task.py ask) or a runner to stop, after the current end of
# logs/runner.log, then prints every such line since: "chain stops: <status> · <summary>", "chain ended", "chain asks",
# "STOP", "all chains ended". With none of those, it still returns every LIVE_SYNC_MIN minutes (loop.conf; 0 = never) if
# a chain's state changed, naming those chains, so their live pages get the progress (live_sync.py).
# Run it as a background task of the main session (it re-invokes you when it exits). One watcher per runner log is
# enough: every runner writes to the same log. Times out after WAIT_HOURS (default 8) with the state of every chain.
#   wait_chain.sh [from-line]
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
LOG="$HERE/logs/runner.log"
a="${1:-$(wc -l < "$LOG" 2>/dev/null || echo 0)}"
deadline=$(( $(date +%s) + ${WAIT_HOURS:-8} * 3600 ))
every="${LIVE_SYNC_SECS:-$(( ${LIVE_SYNC_MIN:-10} * 60 ))}"
mkdir -p "$HERE/state"; mark="$HERE/state/wait_chain.$$"; touch "$mark"
tick=$(( $(date +%s) + every ))
until tail -n +$((a + 1)) "$LOG" 2>/dev/null | grep -aqE "chain ended|chain asks|STOP|all chains ended"; do
    now=$(date +%s)
    if [ "$every" -gt 0 ] && [ "$now" -ge "$tick" ]; then
        changed=$(find "$WT_ROOT" -path '*/.fixloop/status.json' -newer "$mark" 2>/dev/null | sed 's#/\.fixloop/status\.json$##; s#.*/##' | sort)
        if [ -n "$changed" ]; then
            rm -f "$mark"
            echo "== progress, nothing needs anyone: sync the live pages of $(echo $changed) (live_sync.py)"
            "$PYTHON" "$HERE/status.py"
            echo "== next from-line: $a"; exit 0   # not the log's end: a stop logged since the check above is read next time
        fi
        tick=$(( now + every ))
    fi
    if [ "$now" -ge "$deadline" ]; then
        rm -f "$mark"; echo "TIMEOUT after ${WAIT_HOURS:-8}h with no chain ending. State of every chain:"; "$PYTHON" "$HERE/status.py"; exit 3
    fi
    sleep "${WAIT_POLL_SECS:-30}"
done
rm -f "$mark"
sleep 5   # let the runner write its "chain ended" line after the chain's own "chain stops" line
echo "== since line $a of runner.log:"
tail -n +$((a + 1)) "$LOG" | grep -aE "chain stops|chain ended|chain asks|STOP|all chains ended" | cut -c1-900
echo "== next from-line: $(wc -l < "$LOG")"
