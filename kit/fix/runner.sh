#!/usr/bin/env bash
# Runs the branches listed in a queue file as parallel chains, MAX_PAR at a time; starts the next as one ends.
# Every chain end (and the runner's own end) is written to logs/runner.log and raised as a toast.
#   QUEUE=queue.txt MAX_PAR=5 ./runner.sh          (start.sh opens it in its own window)
#   ./runner.sh --preflight-only                   check both model pins and stop
# Plain bash 3.2 (macOS's): no mapfile, no associative arrays.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1
_max_par="${MAX_PAR:-}"
source ./loop.conf
source ./platform.sh
MAX_PAR="${_max_par:-$MAX_PAR}"   # the caller's MAX_PAR wins over loop.conf
QUEUE="${QUEUE:-queue.txt}"
STAGGER_SECS="${STAGGER_SECS:-45}"   # between chain starts: staggers worktree creation and first builds
POLL_SECS="${POLL_SECS:-30}"
mkdir -p logs locks
log() { echo "[$(date '+%m-%d %H:%M:%S')] [runner] $*" | tee -a logs/runner.log; }
notify() { platform_notify "$1" "$2"; }

pf=$(./preflight.sh)
[ "$pf" = ok ] || { log "STOP: preflight refused: $pf"; notify "Runner stopped" "preflight refused: $pf"; exit 1; }
Q=()
while IFS= read -r line; do Q+=("$line"); done < <(grep -v '^#' "$QUEUE" 2>/dev/null | sed 's/\r$//' | grep -v '^$')
# No branch starts without a signed-off plan: make_briefs.py writes the "Plan signed off:" line only for a plan the owner
# signed off (sign_plan.py). A started branch answers from its worktree's copy of the brief, a new one from briefs/.
for s in ${Q[@]+"${Q[@]}"}; do
    b="briefs/$s.md"; [ -f "$WT_ROOT/$s/.fixloop/brief.md" ] && b="$WT_ROOT/$s/.fixloop/brief.md"
    grep -q '^Plan signed off: ' "$b" 2>/dev/null && continue
    log "STOP: $s: its brief has no 'Plan signed off:' line. Get the plan page signed off, record it with sign_plan.py, then make_briefs.py"
    notify "Runner stopped" "$s has no signed-off plan"; exit 1
done
# The plan pin too when a queued branch's next session runs on it (task.py pin: a design branch not yet signed off), or
# when asked. A started branch answers from its worktree, where the sign-off note is; a new one from its brief.
plan=""
for s in ${Q[@]+"${Q[@]}"}; do
    if [ -f "$WT_ROOT/$s/.fixloop/status.json" ]; then p=$(cd "$WT_ROOT/$s" && "$PYTHON" "$ROOT/task.py" pin 2>/dev/null)
    else p=$("$PYTHON" "$ROOT/task.py" pin "briefs/$s.md" 2>/dev/null); fi
    [ "$p" = plan ] && plan=1
done
if [ -n "$plan" ] || [ "${1:-}" = "--preflight-only" ]; then
    pf=$(./preflight.sh plan)
    [ "$pf" = ok ] || { log "STOP: plan-pin preflight refused: $pf"; notify "Runner stopped" "plan-pin preflight refused: $pf"; exit 1; }
    plan=" · plan pin $PLAN_MODEL, $PLAN_EFFORT"
fi
log "preflight ok: $MODEL, $CTX_WINDOW, $EFFORT$plan · MAX_PAR=$MAX_PAR · queue $QUEUE"
[ "${1:-}" = "--preflight-only" ] && exit 0
SLUGS=(); PIDS=()   # the running chains: SLUGS[k] runs as PIDS[k]

reap() {  # log every chain that has ended and drop it from the running lists
    local k s=() p=() st
    for ((k = 0; k < ${#PIDS[@]}; k++)); do
        if kill -0 "${PIDS[$k]}" 2>/dev/null; then s+=("${SLUGS[$k]}"); p+=("${PIDS[$k]}"); continue; fi
        wait "${PIDS[$k]}" 2>/dev/null
        st=$(cd "$WT_ROOT/${SLUGS[$k]}" 2>/dev/null && "$PYTHON" "$ROOT/task.py" status 2>/dev/null)
        log "chain ended: ${SLUGS[$k]} (${st:-unknown})"; notify "Chain ended: ${SLUGS[$k]}" "${st:-unknown}"
    done
    SLUGS=(${s[@]+"${s[@]}"}); PIDS=(${p[@]+"${p[@]}"})
}

i=0
while [ "$i" -lt "${#Q[@]}" ] || [ "${#PIDS[@]}" -gt 0 ]; do
    reap
    while [ "${#PIDS[@]}" -lt "$MAX_PAR" ] && [ "$i" -lt "${#Q[@]}" ]; do
        slug="${Q[$i]}"; i=$((i + 1))
        ./fixloop.sh "$slug" &
        SLUGS+=("$slug"); PIDS+=("$!")
        log "chain started: $slug (pid $!)"
        sleep "$STAGGER_SECS"
    done
    [ "${#PIDS[@]}" -gt 0 ] && sleep "$POLL_SECS"
done
log "all chains ended"
notify "Chains finished" "All ${#Q[@]} in $QUEUE have stopped; see logs/runner.log"
