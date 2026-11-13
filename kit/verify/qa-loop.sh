#!/usr/bin/env bash
# Live-verify loop. Each session is a fresh `claude -p` on the pinned model, seeded from the ledger and the previous
# session's HANDOFF.md. Stops when every test is recorded, when the owner quits at a pause, after MAX_SESSIONS, or
# after two sessions in a row with no ledger progress. Resumable: rerun to pick up where it stopped.
#
#   ./qa-loop.sh                 normal run
#   REUSE_SERVER=1 ./qa-loop.sh  use a server already on APP_URL's port
#   KEEP_UP=1 ./qa-loop.sh       leave the server and Chrome running on exit
set -u
RUN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RUN"
source ./loop.conf
source ./platform.sh
readonly MODEL MODEL_ARG EFFORT
export LOOP_STATE="$(cygpath -m "$RUN")" LOOP_MODEL="$MODEL" LOOP_EFFORT="$EFFORT" LOOP_CTX_WINDOW="$CTX_WINDOW" \
       LOOP_SOFT_PCT="$SOFT_PCT" LOOP_HARD_PCT="$HARD_PCT"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL" ANTHROPIC_SMALL_FAST_MODEL="$MODEL"   # background calls too
PORT="${APP_URL##*:}"; PORT="${PORT%%/*}"
: "${MAX_SESSIONS:=30}"

mkdir -p logs handoffs evidence state

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a logs/loop.log; }
notify() {
    printf '\a'
    platform_notify "$1" "$2"
}
die() { log "STOP: $*"; notify "Verify loop stopped" "$*"; exit 1; }

# ---------------------------------------------------------------- the app under test, as project.json "verify" says
# Its databases and services (verify.services: started, or reused when already up; kept data seeded once), its build,
# then its start command in the background, until verify.health on APP_URL answers. Nothing here knows the stack.
SERVER_STARTED=0
pj() { "$PYTHON" project.py get "$1"; }
app_env() { "$PYTHON" services.py env --state state; "$PYTHON" project.py exports verify; }
start_server() {
    local pid code build start health tmo out
    [ "$START_SERVER" = 1 ] || { log "START_SERVER=0: expecting the app on $APP_URL"; return; }
    pid=$(port_pid "$PORT")
    if [ -n "$pid" ]; then
        [ "${REUSE_SERVER:-0}" = 1 ] || die ":$PORT is held by PID $pid. Stop it first, or rerun with REUSE_SERVER=1."
        log "reusing the server already on :$PORT (PID $pid)"; return
    fi
    [ -d "$VERIFY_WORKTREE" ] || die "no verify worktree at $VERIFY_WORKTREE (git worktree add --detach $VERIFY_WORKTREE origin/$BASE)"
    start=$(pj verify.start); build=$(pj verify.build); health=$(pj verify.health); tmo=$(pj verify.timeout)
    [ -n "$start" ] || die "project.json has no verify.start (how the app is served), or rerun init_run.py with START_SERVER=0"
    if [ -n "$(pj verify.services)" ]; then
        out=$("$PYTHON" services.py up --for verify --state state 2>>logs/loop.log) || die "$(echo "$out" | tr '\n' ' ')"
        log "services up: $(pj verify.services) (logs/loop.log says which were reused)"
    fi
    if [ -n "$build" ]; then
        log "building in $VERIFY_WORKTREE ($(git -C "$VERIFY_WORKTREE" rev-parse --short HEAD)): $build"
        ( eval "$(app_env)"; cd "$VERIFY_WORKTREE" && bash -c "$build" ) > logs/build.log 2>&1 || die "the build failed; see logs/build.log"
    fi
    log "starting the app: $start"
    ( eval "$(app_env)"; cd "$VERIFY_WORKTREE" && exec bash -c "$start" ) >> logs/server.log 2>&1 &
    for _ in $(seq 1 $(( ${tmo:-180} / 2 ))); do
        code=$(curl -s -o /dev/null -w '%{http_code}' "$APP_URL${health:-/}" || true)
        case "$code" in 2*|3*) SERVER_STARTED=1; log "app up on $APP_URL (${health:-/} answered $code)"; return ;; esac
        sleep 2
    done
    die "the app did not answer $APP_URL${health:-/} within ${tmo:-180}s; see logs/server.log"
}
stop_server() {
    if [ "$SERVER_STARTED" = 1 ]; then
        local pid; pid=$(port_pid "$PORT")
        [ -n "$pid" ] && kill_tree "$pid"
        log "app stopped"
    fi
    if [ -f state/services.json ]; then "$PYTHON" services.py down --state state; log "services stopped (kept data stays)"; fi
}

# ---------------------------------------------------------------- one shared Chrome (persistent profile, debug port)
start_chrome() {
    if curl -s "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1; then log "reusing Chrome on :$CDP_PORT"; return; fi
    "$CHROME" --remote-debugging-port="$CDP_PORT" --user-data-dir="$(cygpath -w "$RUN/chrome-profile")" \
        --no-first-run --no-default-browser-check --window-size=1600,1000 about:blank >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        curl -s "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 && { log "Chrome up (profile chrome-profile, port $CDP_PORT)"; return; }
        sleep 1
    done
    die "Chrome did not open debugging port $CDP_PORT"
}
stop_chrome() { chrome_stop "$RUN/chrome-profile"; }

cleanup() { [ "${KEEP_UP:-0}" = 1 ] && return; stop_server; stop_chrome; }
trap cleanup EXIT
trap 'log "interrupted"; exit 130' INT

# ---------------------------------------------------------------- pause (only for PAUSE_FOR; see ledger.py pause)
RESUME_NOTE=""
handle_pause() {
    local id ans="" ask
    id=$("$PYTHON" ledger.py paused-id)
    if [ -z "$id" ]; then mv PAUSED.md "handoffs/paused-orphan-$(date +%s).md"; return 0; fi
    ask=$(tail -n +3 PAUSED.md)
    log "PAUSED at $id"
    notify "Verify loop paused at $id" "$(echo "$ask" | head -c 180)"
    printf '\n%s\n\n' "$(cat PAUSED.md)"
    echo "Do it in the run's Chrome window, then:  Enter = done  ·  s = skip (recorded as blocked)  ·  q = quit (rerun later to resume)"
    echo "(or create a file named RESUME, SKIP or QUIT in $RUN)"
    while :; do
        if [ -f RESUME ]; then rm -f RESUME; ans=""; break; fi
        if [ -f SKIP ]; then rm -f SKIP; ans=s; break; fi
        if [ -f QUIT ]; then rm -f QUIT; ans=q; break; fi
        if [ -t 0 ]; then read -r -t 5 ans && break; else sleep 5; fi
    done
    case "$ans" in
        q|Q) log "quit while paused at $id (rerun to continue)"; return 1 ;;
        s|S) "$PYTHON" ledger.py skip "$id" "Skipped at the pause by $OWNER. Ask was: $(echo "$ask" | head -c 300)" >/dev/null
             RESUME_NOTE="$OWNER skipped $id at the pause; it is recorded as blocked. Go on to the next test." ;;
        *)   "$PYTHON" ledger.py resume "$id" >/dev/null
             RESUME_NOTE="$OWNER finished the human step for $id. Continue $id from there (its ledger notes and the hand-off say what was set up). The ask was: $ask" ;;
    esac
    mv PAUSED.md "handoffs/paused-$id-$(date +%s).md"
    log "resuming after the pause at $id (${ans:-done})"
}

# ---------------------------------------------------------------- main
start_server
start_chrome
r=$(./preflight.sh); [ "$r" = ok ] || die "preflight refused (not $MODEL only, ${CTX_WINDOW} window): $r"
log "preflight ok: $MODEL, ${CTX_WINDOW} window, $EFFORT; thresholds $SOFT_PCT% / $HARD_PCT%"
sha=$(git -C "$VERIFY_WORKTREE" rev-parse --short HEAD 2>/dev/null || echo "?")
"$PYTHON" ledger.py build "$sha" >/dev/null
# tests whose `Requires:` this machine can't meet are recorded blocked now, with the ask, instead of costing a session
have="${HAVE_CAPS:-},$(pj verify.provides)"   # what this machine has, and what the app's own services provide
log "requirements: $("$PYTHON" ledger.py requires-check "$have")"

n=$(ls logs/session-*.jsonl 2>/dev/null | wc -l)
started=0; strikes=0; soft=0; last_end=""
while :; do
    remaining=$("$PYTHON" ledger.py remaining)
    if [ "$remaining" = 0 ]; then
        "$PYTHON" ledger.py report > REPORT.md
        log "every test is recorded: $("$PYTHON" ledger.py summary --short). Report: REPORT.md"
        notify "Verify loop finished" "$("$PYTHON" ledger.py summary --short)"
        break
    fi
    if [ -f PAUSED.md ]; then handle_pause || break; fi

    started=$((started + 1)); n=$((n + 1))
    [ "$started" -gt "$MAX_SESSIONS" ] && die "reached MAX_SESSIONS=$MAX_SESSIONS for this run"

    prompt="state/prompt-$n.md"
    {
        echo "Session $n of the live verify '$RUN_NAME'. Build: $BASE $sha. Now: $(date '+%Y-%m-%d %H:%M')."
        echo; echo "Ledger: $("$PYTHON" ledger.py summary --short)"
        echo; echo "## Hand-off from the previous session"
        if [ -f HANDOFF.md ]; then cat HANDOFF.md
        elif [ -n "$last_end" ]; then echo "(none: the previous session ended with '$last_end' without writing one)"
        else echo "(none)"; fi
        if [ -f state/last_stop.json ]; then
            echo; echo "## The previous session was force-stopped by the context guard"; cat state/last_stop.json; echo
            echo "It may have stopped mid-step without a hand-off. The ledger holds what was recorded; an in_progress test was interrupted. Before redoing its steps, check what it already created so nothing is created twice."
        fi
        if [ -n "$RESUME_NOTE" ]; then echo; echo "## Pause outcome"; echo "$RESUME_NOTE"; fi
        echo; echo "Begin with: "$PYTHON" ledger.py next"
    } > "$prompt"
    [ -f HANDOFF.md ] && mv HANDOFF.md "handoffs/$n-in.md"
    [ -f state/last_stop.json ] && mv state/last_stop.json "state/stop-before-$n.json"
    RESUME_NOTE=""

    fp_before=$("$PYTHON" ledger.py fingerprint)
    date +%s > state/session_start
    log "session $n start: $remaining left"
    # The prompt goes on stdin: an argv prompt makes the CLI print a "no stdin data" warning into stdout and breaks the JSON.
    claude -p --model "$MODEL_ARG" --effort "$EFFORT" \
        --append-system-prompt-file runbook.md \
        --settings settings.json \
        --mcp-config mcp.json --strict-mcp-config \
        --permission-mode dontAsk \
        --disallowedTools Agent Task Workflow \
        --max-budget-usd "$BUDGET_PER_SESSION" \
        --output-format stream-json --verbose \
        < "$prompt" > "logs/session-$n.jsonl" 2> "logs/session-$n.err"
    rc=$?
    IFS='|' read -r sub cost turns apierr text < <("$PYTHON" session_result.py "logs/session-$n.jsonl")
    if [ "$apierr" = usage_limit_reached ] || [ "$apierr" = rate_limit_error ]; then
        # The account hit its usage limit. Not a session, not a strike: hand the next session what this one was handed
        # (unless it wrote its own hand-off before the limit hit), wait for the reset, then go on. Any other preflight
        # refusal while waiting stops the run, as the start-up preflight does.
        [ -f HANDOFF.md ] || { [ -f "handoffs/$n-in.md" ] && mv "handoffs/$n-in.md" HANDOFF.md; }
        [ -f state/last_stop.json ] || { [ -f "state/stop-before-$n.json" ] && mv "state/stop-before-$n.json" state/last_stop.json; }
        log "usage limit ($text): waiting for the reset; checking every 30 minutes"
        started=$((started - 1))
        while sleep 1800; do
            pf=$(./preflight.sh)
            [ "$pf" = ok ] && break
            grep -qiE "limit" <<<"$pf" || die "preflight refused while waiting for the usage limit: $pf"
            log "still limited"
        done
        log "usage limit lifted: carrying on"; continue
    fi
    kind=""
    [ -f state/last_stop.json ] && kind=$("$PYTHON" -c "import json; print(json.load(open('state/last_stop.json')).get('kind', ''))")
    last_end="${kind:-$sub}"
    "$PYTHON" ledger.py session "$n" "$last_end" "$cost" "$turns" >/dev/null
    log "session $n end: $last_end · \$$cost · $turns turns · rc=$rc · $("$PYTHON" ledger.py summary --short)"
    case "$kind" in
        wrong-model|guard-error) die "session $n was stopped by the guard ($kind); see state/last_stop.json and logs/ctx.log" ;;
    esac
    [ "$sub" = success ] || [ -n "$kind" ] || log "session $n did not end cleanly: $sub: $text (see logs/session-$n.err)"

    # No change at all: two strikes stop the run. Notes only (a long test, a wait on a nightly job): four in a row stop it.
    fp_after=$("$PYTHON" ledger.py fingerprint)
    if [ -f PAUSED.md ] || [ "${fp_after%%:*}" != "${fp_before%%:*}" ]; then
        strikes=0; soft=0
    elif [ "$fp_after" = "$fp_before" ]; then
        strikes=$((strikes + 1)); log "no ledger progress in session $n (strike $strikes of 2)"
        [ "$strikes" -ge 2 ] && die "two sessions in a row made no progress"
    else
        soft=$((soft + 1)); log "session $n only added notes ($soft of 4 in a row)"
        [ "$soft" -ge 4 ] && die "four sessions in a row only added notes: no test moved on"
    fi
done
