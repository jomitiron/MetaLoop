#!/usr/bin/env bash
# Self-test of the metaloop kit on THIS machine. It renders a fix run and a verify run from a test project profile, runs
# the scripts against stubs (claude, pmset, a stand-in toolchain `st-run`, a stand-in service: python's http.server), every
# test-output parser against sample output, every stack preset, and the native PostgreSQL and MongoDB presets for real
# where those servers are installed (plus Chrome and tmux).
# No real session, build or push; nothing outside a temp folder is touched.
#   bash skills/metaloop/kit/selftest.sh   (macOS, Linux or Windows Git Bash; from a clone of the MetaLoop repository,
#   or as bash <kit>/selftest.sh from an installed copy, where a scratch repository stands in for the project)
# Run it after any change to the kit, on every platform you changed it for. Exit 0 = every check passed.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$KIT" rev-parse --show-toplevel 2>/dev/null)"
T="$(mktemp -d "${TMPDIR:-/tmp}/metaloop-selftest.XXXXXX")"
# Outside a git checkout (an installed plugin): a scratch repository with one commit stands in for the project.
CLONE=1
if [ -z "$REPO" ]; then
    CLONE=0; REPO="$T/project-repo"
    git init -q -b main "$REPO" && git -C "$REPO" -c user.name=selftest -c user.email=selftest@example.invalid \
        commit -q --allow-empty -m init || { echo "could not make a scratch repository in $REPO"; exit 1; }
fi
STUBS="$T/stubs"; mkdir -p "$STUBS"
PY="$(command -v python3 || command -v python)"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN=0 ;; esac
pass=0; fail=0; skipped=0
ok() { pass=$((pass + 1)); echo "  ok    $*"; }
bad() { fail=$((fail + 1)); echo "  FAIL  $*"; }
skip() { skipped=$((skipped + 1)); echo "  skip  $*"; }
check() { local what="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$what"; else bad "$what"; fi; }
TMUX_NAME="metaloop-selftest-$$"
cleanup() {
    tmux kill-session -t "=$TMUX_NAME" >/dev/null 2>&1
    [ -f "$T/ver/state/services.json" ] && (cd "$T/ver" && "$PY" services.py down --state state) >/dev/null 2>&1
    pkill -f "sleep 611" >/dev/null 2>&1   # the stand-in service that never answers
    rm -rf "$T"
}
trap cleanup EXIT
free_port() { "$PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])"; }
wait_for() { local n="$1"; shift; for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

# Stubs. claude: a preflight-shaped reply from the model it was given. st-run: a stand-in build and test command
# passing build or suite (or a missing-workload build failure). bash: the bash under test (on macOS /bin/bash is 3.2).
cat > "$STUBS/claude" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null; sleep 1
m=none; while [ $# -gt 0 ]; do [ "$1" = --model ] && m="${2%"[1m]"}"; shift; done
echo '{"type":"result","result":"READY","modelUsage":{"'"$m"'":{"canonicalModel":"'"$m"'","contextWindow":1000000}}}'
EOF
cat > "$STUBS/st-run" <<'EOF'
#!/usr/bin/env bash
# a stand-in toolchain: logs each call with the env the gate gave it; `test` answers like jest
echo "st-run $* | LC_ALL=${LC_ALL:-} | SVC=${SVC_URL:-}" >> "$SELFTEST_LOG"
case "$1" in
  build) if [ -n "${SELFTEST_BUILD_FAIL:-}" ]; then echo "error: missing toolchain component xyz"; exit 1; fi
         echo "built" ;;
  test)  if [ -n "${SVC_URL:-}" ]; then echo "svc=$(curl -s "$SVC_URL/ping.txt")" >> "$SELFTEST_LOG"; fi
         if [ "$2" = unit ] && [ -n "${SELFTEST_ZERO:-}" ]; then echo "Tests:       0 total"; exit 0; fi
         if [ "$2" = unit ] && [ -n "${SELFTEST_UNIT_FAIL:-}" ]; then
             echo "  ● $SELFTEST_UNIT_FAIL"; echo "Tests:       1 failed, 2 passed, 3 total"; exit 1
         fi
         echo "Tests:       3 passed, 3 total" ;;
esac
EOF
chmod +x "$STUBS/claude" "$STUBS/st-run"
ln -s "${SELFTEST_BASH:-$(command -v bash)}" "$STUBS/bash"
export PATH="$STUBS:$PATH" SELFTEST_LOG="$T/steps.log"

# The test profile: the stand-in toolchain and a stand-in service, so every stack-neutral path runs with no real stack.
SVC_PORT=$(free_port); VSVC_PORT=$(free_port); APP_PORT=$(free_port)
write_profile() {  # <out> [python that edits p]
    "$PY" - "$1" "${2:-pass}" <<EOF
import json, sys
p = {
 "requires": [{"tool": "st-run", "for": "the stand-in build and tests", "install": "a selftest stub", "who": "claude"}],
 "env": {"LC_ALL": "en_US.UTF-8"},
 "gate": {"steps": [
  {"name": "build", "run": "st-run build", "hints": [{"match": "missing toolchain component", "say": "the toolchain is incomplete"}]},
  {"name": "unit", "run": "st-run test unit", "tests": "jest", "slots": 3},
  {"name": "integration", "run": "st-run test integration", "tests": "jest", "services": ["web"],
   "skippable": "CI's integration job runs it"}]},
 "services": {"web": {"port": $SVC_PORT, "start": "exec '$PY' -u -m http.server {port} --bind 127.0.0.1 --directory {dir}",
                      "up": "curl -s -o /dev/null http://127.0.0.1:{port}/", "init": "echo pong > {dir}/ping.txt",
                      "ready": "curl -sf http://127.0.0.1:{port}/ping.txt >/dev/null", "timeout": 20,
                      "env": {"SVC_URL": "http://127.0.0.1:{port}"}}},
 "verify": {"url": "http://127.0.0.1:$APP_PORT", "health": "/", "start": "exec '$PY' -m http.server {app_port} --bind 127.0.0.1",
            "services": {"web": {"port": $VSVC_PORT, "persist": "$T/persist-web", "reuse": True,
                                 "seed": "echo seeded >> '$T/seed.log'"}},
            "provides": ["webhooks"]},
 "chain_allow": ["st-run *"], "verify_allow": ["curl *localhost*"],
 "caps": {"payments": "start the payment provider's sandbox listener as a verify service, then requeue the test"},
}
exec(sys.argv[2])
json.dump(p, open(sys.argv[1], "w"), indent=1)
EOF
}
write_profile "$T/project.json"
echo "metaloop kit self-test: $(uname -s), bash $("$STUBS/bash" -c 'echo $BASH_VERSION'), $("$PY" --version 2>&1)"

cd "$REPO" || exit 1
init() { "$PY" "$KIT/init_run.py" "$1" "$2" OWNER=Selftest GH_REPO=o/r GH_LOGIN=selftest PROJECT="$T/project.json" "${@:3}" > "$T/init.log" 2>&1; }

echo "== init_run renders runs whose every command exists on this machine"
init fix "$T/fix" || { cat "$T/init.log"; exit 1; }
init verify "$T/ver" || { cat "$T/init.log"; exit 1; }
for run in fix ver; do
    noexec=$(cd "$T/$run" && for f in *.sh *.py; do [ -x "$f" ] || echo "$f"; done)
    check "$run: every script is executable${noexec:+ (not: $(echo $noexec))}" test -z "$noexec"
    py=$(sed -n 's/^PYTHON=//p' "$T/$run/loop.conf" | tr -d "'")
    check "$run: loop.conf PYTHON ('$py') runs here" command -v "${py:-none}"
    missing=$("$PY" - "$T/$run/settings.json" <<'EOF'
import json, shutil, sys
d = json.load(open(sys.argv[1], encoding="utf8"))
cmds = [h["command"] for ev in d["hooks"].values() for m in ev for h in m["hooks"]]
cmds += [a[5:-1] for a in d["permissions"]["allow"] if a.startswith("Bash(") and ".py" in a]
print(" ".join(sorted({c.split()[0] for c in cmds if not shutil.which(c.split()[0])})))
EOF
)
    check "$run: hooks and allow-listed scripts start with a command that exists${missing:+ (missing: $missing)}" test -z "$missing"
    check "$run: the runbook names the run's python, not a bare 'python' this machine lacks" \
        sh -c "[ '$py' = python ] || ! grep -qE '(^|[\` ])python [^-]' '$T/$run/runbook.md'"
done
check "the project profile is copied into both runs" sh -c "cmp -s '$T/project.json' '$T/fix/project.json' && cmp -s '$T/project.json' '$T/ver/project.json'"
check "fix sessions may run the profile's chain_allow commands" grep -q '"Bash(st-run \*)"' "$T/fix/settings.json"
check "verify sessions may run its verify_allow commands, and not the chains'" \
    sh -c "grep -q '\"Bash(curl \*localhost\*)\"' '$T/ver/settings.json' && ! grep -q 'st-run' '$T/ver/settings.json'"
check "APP_URL comes from the profile's verify.url" grep -qx "APP_URL=http://127.0.0.1:$APP_PORT" "$T/ver/loop.conf"
check "BASE is the repository's default branch, not a fixed name" sh -c "b=\$(sed -n 's/^BASE=//p' '$T/fix/loop.conf'); [ -n \"\$b\" ] && git -C '$REPO' rev-parse -q --verify \"origin/\$b\" >/dev/null || git -C '$REPO' rev-parse -q --verify \"\$b\" >/dev/null"
check "the next-step hint names the run's python, not a bare 'python'" \
    sh -c "[ '$py' = python ] || ! grep -q 'run python ' '$T/init.log'"
init fix "$T/keep" SLUG_PREFIX=x-
sed -i.bak 's/^MAX_SESSIONS=.*/MAX_SESSIONS=7/' "$T/keep/loop.conf"       # a hand edit, as loop.conf's header invites
"$PY" "$KIT/init_run.py" fix "$T/keep" MAX_PAR=2 > "$T/init-keep.log" 2>&1
for kv in OWNER=Selftest SLUG_PREFIX=x- MAX_SESSIONS=7 MAX_PAR=2; do
    check "a re-run with one KEY=VALUE keeps the run's other settings: $kv" grep -qx "$kv" "$T/keep/loop.conf"
done
check "and loop.json says the same as loop.conf" "$PY" -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['MAX_SESSIONS']=='7' and d['OWNER']=='Selftest', d" "$T/keep/loop.json"
mcp_cmd=$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['mcpServers']['chrome-devtools']['command'])" "$T/ver/mcp.json")
check "verify: the Chrome MCP command ('$mcp_cmd') exists" command -v "$mcp_cmd"
chrome=$(sed -n 's/^CHROME=//p' "$T/ver/loop.conf" | tr -d "'")
if [ -e "$chrome" ] || [ "$WIN" = 1 ]; then check "verify: CHROME points at an installed Chrome" test -e "$chrome"
else skip "verify: CHROME ($chrome): no Chrome installed"; fi

echo "== model pins: code on Opus 5.5 high, plan on Opus 5.5 xhigh, the verify loop at xhigh"
for kv in MODEL=claude-opus-5-5 "MODEL_ARG='claude-opus-5-5[1m]'" EFFORT=high \
          PLAN_MODEL=claude-opus-5-5 "PLAN_MODEL_ARG='claude-opus-5-5[1m]'" PLAN_EFFORT=xhigh; do
    check "fix: loop.conf has $kv" grep -qxF "$kv" "$T/fix/loop.conf"
done
check "verify: loop.conf has EFFORT=xhigh" grep -qx EFFORT=xhigh "$T/ver/loop.conf"

echo "== preflight: two at once in one run both pass, and the plan pin"
( cd "$T/fix" && ./preflight.sh > "$T/pf1" 2>&1 ) & a=$!
( cd "$T/fix" && ./preflight.sh > "$T/pf2" 2>&1 ) & b=$!
wait $a; wait $b
check "preflight 1 printed ok ($(head -c 80 "$T/pf1"))" grep -qx ok "$T/pf1"
check "preflight 2 printed ok ($(head -c 80 "$T/pf2"))" grep -qx ok "$T/pf2"
pf=$(cd "$T/fix" && ./preflight.sh plan 2>&1)
check "preflight plan printed ok ($(echo "$pf" | head -c 80))" test "$pf" = ok
pf=$(cd "$T/fix" && sed -i.bak 's/^PLAN_MODEL=.*/PLAN_MODEL=claude-other-model/' loop.conf && ./preflight.sh plan 2>&1)
check "a plan pin that answers as another model is refused ($(echo "$pf" | head -c 60))" test "$pf" != ok
mv "$T/fix/loop.conf.bak" "$T/fix/loop.conf"

echo "== task.py pin: a design branch plans until its sign-off, everything else codes"
pw="$T/pin"; mkdir -p "$pw/.fixloop"
pin_is() {  # <brief first lines> <notes json> -> the pin task.py picks
    printf '%b' "$1" > "$pw/.fixloop/brief.md"
    echo '{"slug":"s","status":"todo","phase":null,"pr":null,"notes":'"$2"',"reviews":[],"summary":""}' > "$pw/.fixloop/status.json"
    (cd "$pw" && "$PY" "$T/fix/task.py" pin)
}
check "a build brief runs on the code pin" test "$(pin_is '# Fix branch `s`\n\nDefects: D1\n' '[]')" = code
check "a design brief runs on the plan pin" test "$(pin_is '# Design branch `s`\n\nMode: design. Deliver: mockup\n' '[]')" = plan
check "... with its mode on the first line too" test "$(pin_is 'Mode: design. Deliver: mockup\n' '[]')" = plan
check "a signed-off design brief runs on the code pin" \
    test "$(pin_is '# Design branch `s`\n\nMode: design. Deliver: mockup\n' '["2026-11-05T10:00:00 SIGNED OFF (Selftest, 2026-11-05): M1-A. Mode is now BUILD"]')" = code

echo "== task.py: a question that doesn't stop the chain, the owner's answer, tasks"
tw="$T/ask"; mkdir -p "$tw/.fixloop"
printf '# Fix branch `s`\n\nPlan signed off: 2026-11-07 by Selftest\n' > "$tw/.fixloop/brief.md"
echo '{"slug":"s","status":"in_progress","phase":"green","pr":null,"notes":[],"reviews":[],"summary":""}' > "$tw/.fixloop/status.json"
tp() { (cd "$tw" && "$PY" "$T/fix/task.py" "$@"); }
tp ask "Which Customer A Retry Bills" "Order 10482 moved to Summit Haulage before its retry ran. Which customer should the retry bill?" \
    "The customer the order has now" "The customer it was queued for" >/dev/null
check "ask records Q1 open, with the recommended answer first" "$PY" -c "import json,sys; q=json.load(open(sys.argv[1]))['asks'][0]; assert q['id']=='Q1' and q['status']=='open' and q['recommend']=='a' and q['options'][0]['text']=='The customer the order has now', q" "$tw/.fixloop/status.json"
check "ask leaves the chain working: it carries on with the recommended answer" test "$(tp status)" = in_progress
check "ask wakes the main session: a 'chain asks' line in runner.log" grep -q "chain asks: s Q1 · Which Customer A Retry Bills" "$T/fix/logs/runner.log"
tp ask "$(printf 'Forged Title\n[11-07 00:00:00] [runner] STOP: forged')" "q" "a" "b" >/dev/null
check "a newline in a question can't add a forged STOP line to runner.log" sh -c "! grep -q '^\[11-07 00:00:00\] \[runner\] STOP: forged' '$T/fix/logs/runner.log'"
check "the pr phase is refused while Q1 is open" sh -c "! (cd '$tw' && '$PY' '$T/fix/task.py' phase pr 'open the PR') >/dev/null 2>&1"
check "... the refusal says how to hold the pull request" sh -c "(cd '$tw' && '$PY' '$T/fix/task.py' phase pr x 2>&1) | grep -q 'task.py needs'"
check "... and changes nothing" test "$(cd "$tw" && "$PY" -c "import json; print(json.load(open('.fixloop/status.json'))['phase'])")" = green
tp answer Q1 "B: bill the customer it was queued for" >/dev/null
tp answer Q2 "A" >/dev/null
check "answer closes Q1 and leaves a note the next session reads" sh -c "(cd '$tw' && '$PY' '$T/fix/task.py' show) | grep -q 'OWNER ANSWER Q1'"
check "the pr phase goes ahead once every question is answered" sh -c "cd '$tw' && '$PY' '$T/fix/task.py' phase pr 'open the PR'"
tp done T1 "RetryBillsCurrentCustomer passes" >/dev/null
check "done ticks a task" "$PY" -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['tasks_done']==['T1'], d" "$tw/.fixloop/status.json"
check "done without a task id prints the usage, not a Python error" \
    sh -c "out=\$(cd '$tw' && '$PY' '$T/fix/task.py' done 2>&1); [ \$? -ne 0 ] && ! echo \"\$out\" | grep -q Traceback"
rw="$T/race"; mkdir -p "$rw/.fixloop"
echo '{"slug":"r","status":"in_progress","phase":"green","pr":null,"notes":[],"reviews":[],"summary":""}' > "$rw/.fixloop/status.json"
notes() { for i in $(seq 1 12); do (cd "$rw" && "$PY" "$T/fix/task.py" note "$1$i") >/dev/null 2>&1; done; }
notes a & x=$!; notes b & y=$!; notes c & z=$!; wait $x $y $z
check "three writers at once (a chain, an answer, a requeue): no change is lost" \
    "$PY" -c "import json,sys; n=json.load(open(sys.argv[1]))['notes']; assert len(n)==36, len(n)" "$rw/.fixloop/status.json"

echo "== planning: no brief before the plan is signed off, every branch broken into tasks"
cp "$T/fix/plan.example.json" "$T/fix/plan-t.json"
check "make_briefs refuses a plan that isn't signed off" sh -c "! (cd '$T/fix' && '$PY' make_briefs.py plan-t.json --wave 1) >/dev/null 2>&1"
check "sign_plan refuses while a decision is open" sh -c "! (cd '$T/fix' && '$PY' sign_plan.py plan-t.json 2026-11-07 Selftest) >/dev/null 2>&1"
plan_edit() { "$PY" -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf8')); exec(sys.argv[2]); json.dump(p, open(sys.argv[1], 'w', encoding='utf8'))" "$T/fix/plan-t.json" "$1"; }
plan_edit "[d.update(decided=d['recommend']) for d in p['decisions']]; p['branches'][1]['tasks'] = []"
check "sign_plan refuses a branch with no tasks" sh -c "! (cd '$T/fix' && '$PY' sign_plan.py plan-t.json 2026-11-07 Selftest) >/dev/null 2>&1"
plan_edit "p['branches'][1]['tasks'] = [{'id': 'T1', 'text': 'The panel says Not syncing', 'test': 'order panel: says Not syncing'}]"
(cd "$T/fix" && "$PY" sign_plan.py plan-t.json 2026-11-07 Selftest >/dev/null && "$PY" make_briefs.py plan-t.json --wave 1 >/dev/null)
check "a signed-off plan's briefs say so" grep -q "^Plan signed off: 2026-11-07 by Selftest" "$T/fix/briefs/retry-current-customer.md"
check "... and list the branch's tasks with the test that proves each" grep -q "^- T1 · .* · proved by: " "$T/fix/briefs/retry-current-customer.md"
(cd "$T/fix" && "$PY" plan_page.py plan-t.json "$T/plan.html" "Selftest Plan" > "$T/plan_page.out" 2>&1)
check "plan_page renders the plan into the page" sh -c "grep -q 'retry-current-customer' '$T/plan.html' && ! grep -qE '__PLAN__|__TWO_WAY__' '$T/plan.html'"
check "plan_page prints the capabilities to publish it with" grep -q '"comments"' "$T/plan_page.out"
check "... where only the owner writes the answers and the sign-off" \
    sh -c "grep -q '\"path\": \"answers\", \"read\": \"view\", \"write\": \"owner\"' '$T/plan_page.out' && grep -q '\"path\": \"signoff\", \"read\": \"view\", \"write\": \"owner\"' '$T/plan_page.out'"

echo "== EGM planner: an approved design fans out into branches that are checked before sign-off"
E="$T/egm"; mkdir -p "$E/repo/docs/designs"
gitc() { git -c user.name=Selftest -c user.email=selftest@example.com "$@"; }
git init -q --bare "$E/origin.git" && git init -q -b develop "$E/repo" && git -C "$E/repo" remote add origin "$E/origin.git"
D="$E/repo/docs/designs/webhooks.md"
cat > "$D" <<'EOF'
# Webhook delivery

*   **Author:** selftest
*   **Status:** Approved
*   **Date:** 2026-11-13

## Goals

*   Every subscribed event reaches its endpoint, signed
*   A failed delivery retries with backoff

## Non-Goals

*   Exactly-once delivery

## Open Questions

<!-- answered questions are removed -->

## Critical User Journeys (CUJs)

### CUJ 1: Endpoint receives a signed event

*   **Given**: a subscription to order.created
*   **When**: an order is created
*   **Then**: the endpoint gets one POST with a valid
    signature header

### CUJ 2: A failed delivery is retried

*   **Given**: an endpoint that returns 503
*   **When**: an event is delivered
*   **Then**: it is retried with backoff

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `src/webhooks/signing.py` (Create)

*   **Type / Scope**: Python module
*   **Proposed Changes**: sign(payload, secret) -> str

#### 2. `src/webhooks/dispatcher.py` (Create)

*   **Type / Scope**: Python service
*   **Proposed Changes**: Dispatcher.deliver(event)

#### 3. `src/events/bus.py` (Modify)

*   **Type / Scope**: Python module
*   **Proposed Changes**: publish() hands subscribed events to Dispatcher

### Verification Plan

*   **Unit Tests**: `pytest tests/webhooks`
EOF
(cd "$E/repo" && git add -A && gitc commit -qm design && git push -q origin develop 2>/dev/null)
(cd "$E/repo" && "$PY" "$KIT/init_run.py" fix "$E/run" OWNER=Selftest GH_REPO=o/r GH_LOGIN=selftest BASE=develop > "$T/init-egm.log" 2>&1) || cat "$T/init-egm.log"
check "init_run: a fix run plans with EGM unless told otherwise" grep -q "^PLANNER=egm" "$E/run/loop.conf"
check "... and its next step says how" grep -q "egm_plan.py import" "$T/init-egm.log"
check "... with the hand-off in the run: script, example, Goldfish reviewer and standard" \
    sh -c "cd '$E/run' && [ -x egm_plan.py ] && [ -f plan.egm.example.json ] && [ -f fanout_readiness.md ] && [ -f fanout-readiness-standard.md ]"
check "plan.egm.example.json's split passes the check (all but the design-on-the-base part)" "$PY" - "$E/run" <<'EOF'
import json, sys
sys.path.insert(0, sys.argv[1]); import egm_plan
p = json.load(open(sys.argv[1] + "/plan.egm.example.json", encoding="utf8"))
probs = [x for x in egm_plan.check(p, ".", "develop", fetch=False) if "origin/" not in x]
assert not probs, probs
EOF
sed 's/\*\*Status:\*\* Approved/**Status:** In Review/' "$D" > "$E/review.md"
check "import refuses a design that isn't Approved" sh -c "! (cd '$E/run' && '$PY' egm_plan.py import '$E/review.md' x.json) >/dev/null 2>&1"
sed 's/<!-- answered questions are removed -->/*   **Retry Cap**: how long do we keep retrying?/' "$D" > "$E/open.md"
check "import refuses a design with an open question" sh -c "! (cd '$E/run' && '$PY' egm_plan.py import '$E/open.md' q.json) >/dev/null 2>&1"
(cd "$E/run" && "$PY" egm_plan.py import "$E/open.md" q.json --as-decisions >/dev/null 2>&1)
check "... or, with --as-decisions, puts it on the plan page as an open round-1 decision" "$PY" -c \
    "import json,sys; d=json.load(open(sys.argv[1]))['decisions']; assert len(d)==1 and d[0]['round']==1 and d[0]['decided'] is None and d[0]['title']=='Retry Cap', d" "$E/run/q.json"
(cd "$E/run" && "$PY" egm_plan.py import "$D" plan.json > "$E/import.out" 2>&1)
check "import reads the design's files, journeys, goals and checks into plan.json" "$PY" - "$E/run/plan.json" <<'EOF'
import json, sys
p = json.load(open(sys.argv[1], encoding="utf8"))
assert p["design"]["path"] == "docs/designs/webhooks.md" and p["design"]["status"] == "Approved", p["design"]
assert p["design"]["url"] == "https://github.com/o/r/blob/develop/docs/designs/webhooks.md", p["design"]
assert [f["path"] for f in p["files"]] == ["src/webhooks/signing.py", "src/webhooks/dispatcher.py", "src/events/bus.py"], p["files"]
assert p["files"][2]["action"] == "Modify" and p["files"][2]["changes"].startswith("publish() hands"), p["files"][2]
assert [j["id"] for j in p["cujs"]] == ["CUJ1", "CUJ2"] and p["cujs"][0]["then"].endswith("a valid signature header"), p["cujs"]
assert len(p["goals"]) == 2 and p["non_goals"] == ["Exactly-once delivery"], p
assert p["verify"] == ["**Unit Tests**: `pytest tests/webhooks`"] and p["decisions"] == [] and p["owner"] == "Selftest", p
EOF
check "import reads a design laid out by phases: '(Modify, Phase 2)', '### Phase 1' groups, numbered goals" "$PY" - "$E/run" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1]); import egm_plan
d = egm_plan.parse_design("""# X

*   **Status:** Approved

## Goals & Non-Goals

### Goals

1.  First goal
2.  Second goal
    continued

### Non-Goals

*   Not this

## Detailed Implementation Plan

### Phase 1: Core

#### 1. `a.py` (Create)

*   **Proposed Changes**: make a

#### 2. Host packages (Modify)

### Phase 2: Wiring

#### 3. `b.py` (Modify, Phase 2)

### Verification Plan

*   `pytest`
""")
assert [(f["path"], f["action"], f.get("phase")) for f in d["files"]] == [("a.py", "Create", "1"), ("b.py", "Modify", "2")], d["files"]
assert d["goals"] == ["First goal", "Second goal continued"] and d["non_goals"] == ["Not this"], d
assert d["unpathed"] == ["Host packages (Modify)"] and d["verify"] == ["`pytest`"], d
assert egm_plan.parse_design(open(sys.argv[1] + "/../repo/docs/designs/webhooks.md").read())["unpathed"] == []
p = egm_plan.check({"design": {"path": "x.md", "sha256": ""}, "unpathed": d["unpathed"], "branches": []}, ".", "develop", fetch=False)
assert any("'Host packages (Modify)' names no file" in x for x in p), p
EOF
check "check refuses a plan with no branches drawn up" sh -c "! (cd '$E/run' && '$PY' egm_plan.py check plan.json) >/dev/null 2>&1"
egm_edit() { "$PY" -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf8')); exec(sys.argv[2]); json.dump(p, open(sys.argv[1], 'w', encoding='utf8'))" "$E/run/plan.json" "$1"; }
egm_edit "p['branches'] = [
 {'slug': 'sign', 'title': 'Signed', 'wave': 1, 'files': ['src/webhooks/signing.py', 'src/events/bus.py'], 'cujs': ['CUJ1'], 'scope': 's', 'tasks': [{'id': 'T1', 'text': 't', 'test': 'test_sign'}]},
 {'slug': 'dispatch', 'title': 'Dispatched', 'wave': 1, 'files': ['src/webhooks/dispatcher.py', 'src/events/bus.py', 'src/other.py'], 'cujs': ['CUJ1'], 'depends_on': ['sign'], 'scope': 's', 'tasks': [{'id': 'T1', 'text': 't', 'test': 'test_dispatch'}]}]"
(cd "$E/run" && "$PY" egm_plan.py check plan.json > "$E/check1.out" 2>&1)
check "check: one file owned by two branches of a wave" grep -q "src/events/bus.py is in both sign and dispatch (wave 1)" "$E/check1.out"
check "check: a journey no branch delivers" grep -q "no branch delivers CUJ2" "$E/check1.out"
check "check: a file the design doesn't list" grep -q "dispatch changes src/other.py, which the design doesn't list" "$E/check1.out"
check "check: a dependency in the same wave" grep -q "a dependency goes in an earlier wave" "$E/check1.out"
check "sign_plan refuses a fan-out that fails the check" sh -c "! (cd '$E/run' && '$PY' sign_plan.py plan.json 2026-11-13 Selftest) >/dev/null 2>&1"
egm_edit "b=p['branches']; b[0]['files']=['src/webhooks/signing.py']; b[1].update(wave=2, cujs=['CUJ1', 'CUJ2']); b[1]['files'].remove('src/other.py')"
check "check passes a sound fan-out: each file owned once, every journey delivered, the dependency a wave earlier" \
    sh -c "cd '$E/run' && '$PY' egm_plan.py check plan.json"
(cd "$E/run" && "$PY" egm_plan.py render plan.json "$E/fanout.md" > /dev/null 2>&1)
check "render writes the split for the Goldfish review: who owns each file, who delivers each journey" \
    sh -c "grep -qF '| \`src/events/bus.py\` | Modify | \`dispatch\` (2) |' '$E/fanout.md' && grep -qF '| CUJ2: A failed delivery is retried | \`dispatch\` |' '$E/fanout.md' && grep -q 'None: egm_plan.py check passes' '$E/fanout.md'"
(cd "$E/run" && "$PY" sign_plan.py plan.json 2026-11-13 Selftest > /dev/null 2>&1 && "$PY" make_briefs.py plan.json --wave 2 > /dev/null 2>&1)
B="$E/run/briefs/dispatch.md"
check "sign_plan signs off a sound fan-out" grep -q '"at": "2026-11-13"' "$E/run/plan.json"
check "a brief names the design as its spec" grep -qF 'Design: `docs/designs/webhooks.md` (EGM, Approved' "$B"
check "... lists its files as its boundary, with the design's proposed change for each" \
    grep -qF -- '- `src/events/bus.py` (Modify) · Python module · publish() hands subscribed events to Dispatcher' "$B"
check "... its journeys as given / when / then" grep -qF -- '- CUJ2 · A failed delivery is retried: given an endpoint that returns 503' "$B"
check "... and what it builds on" grep -q '^Builds on: sign' "$B"
(cd "$E/run" && "$PY" plan_page.py plan.json "$E/plan.html" "Webhooks" > /dev/null 2>&1)
check "plan_page links the design and draws each branch's files" sh -c "grep -q 'docs/designs/webhooks.md' '$E/plan.html' && grep -q 'b.files' '$E/plan.html'"
nb="$E/run/nobase.json"; cp "$E/run/plan.json" "$nb"
"$PY" -c "import json,sys; p=json.load(open(sys.argv[1])); p['design']['path']='docs/designs/unmerged.md'; json.dump(p, open(sys.argv[1], 'w'))" "$nb"
check "check refuses a design that isn't merged into the base yet" sh -c "(cd '$E/run' && '$PY' egm_plan.py check nobase.json) 2>&1 | grep -q 'is not on origin/develop'"
(cd "$E/repo" && git checkout -q -b ai-work/dispatch && mkdir -p src/webhooks src/events tests/webhooks && echo x > src/webhooks/dispatcher.py \
    && echo x > src/events/bus.py && echo x > tests/webhooks/test_dispatcher.py && git add -A && gitc commit -qm build)
check "boundary: a chain that kept to its files (and their tests) passes" sh -c "cd '$E/run' && '$PY' egm_plan.py boundary plan.json dispatch --worktree '$E/repo'"
(cd "$E/repo" && echo x > src/webhooks/signing.py && git add -A && gitc commit -qm stray)
check "boundary: a file another branch owns is flagged" \
    sh -c "(cd '$E/run' && '$PY' egm_plan.py boundary plan.json dispatch --worktree '$E/repo') 2>&1 | grep -A2 OUTSIDE | grep -q src/webhooks/signing.py"
(cd "$E/repo" && git checkout -q develop && echo "*   One more goal" >> docs/designs/webhooks.md && gitc commit -qam "design v2" && git push -q origin develop 2>/dev/null)
check "check notices the design on the base moved since the import" \
    sh -c "(cd '$E/run' && '$PY' egm_plan.py check plan.json) 2>&1 | grep -q 'not the one this plan was imported from'"
(cd "$E/run" && "$PY" egm_plan.py import "$D" plan.json > /dev/null 2>&1)
check "re-importing a changed design keeps the branches and clears the sign-off" "$PY" -c \
    "import json,sys; p=json.load(open(sys.argv[1])); assert p['signed_off'] is None and len(p['branches'])==2, p['signed_off']" "$E/run/plan.json"
"$PY" "$E/run/doctor.py" --json > "$E/doctor.json" 2>/dev/null
check "doctor: PLANNER=egm needs the EGM plugin (the stub claude has none), installable, or PLANNER=grill" "$PY" - "$E/doctor.json" <<'EOF'
import json, sys
i = [x for x in json.load(open(sys.argv[1]))["items"] if x["name"] == "EGM plugin"][0]
assert i["state"] == "missing" and i["ask"] == "PLANNER=grill" and "egm@egm" in i["install"] and i["who"] == "claude", i
EOF
(cd "$E/repo" && "$PY" "$KIT/init_run.py" fix "$E/run" PLANNER=grill > /dev/null 2>&1)
"$PY" "$E/run/doctor.py" --json > "$E/doctor-grill.json" 2>/dev/null
check "doctor: PLANNER=grill doesn't need it" "$PY" -c \
    "import json,sys; i=[x for x in json.load(open(sys.argv[1]))['items'] if x['name']=='EGM plugin'][0]; assert i['state']=='skipped', i" "$E/doctor-grill.json"

echo "== runner: a queue of three chains, two at a time, under this bash"
for s in alpha beta-error gamma; do printf '# Fix branch `%s`\n\nPlan signed off: 2026-11-07 by Selftest\n' "$s" > "$T/fix/briefs/$s.md"; done
cat > "$T/fix/fixloop.sh" <<'EOF'
#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$ROOT/loop.conf"
mkdir -p "$WT_ROOT/$1/.fixloop"; sleep 2
echo '{"slug":"'"$1"'","status":"awaiting_owner","phase":"ci","pr":null,"notes":[],"reviews":[],"summary":"stub"}' > "$WT_ROOT/$1/.fixloop/status.json"
EOF
chmod +x "$T/fix/fixloop.sh"
printf '# a comment\nalpha\n\nbeta-error\ngamma\r\n' > "$T/fix/queue-test.txt"
( cd "$T/fix" && QUEUE=queue-test.txt MAX_PAR=2 STAGGER_SECS=0 POLL_SECS=1 ./runner.sh > "$T/runner.out" 2>&1 ) &
r=$!; wait_for 60 sh -c "! kill -0 $r"; kill $r 2>/dev/null
for s in alpha beta-error gamma; do
    check "runner: $s started and ended awaiting_owner" grep -q "chain ended: $s (awaiting_owner)" "$T/fix/logs/runner.log"
done
check "runner: all chains ended" grep -q "all chains ended" "$T/fix/logs/runner.log"
check "runner: a queue with no design branch checks only the code pin" sh -c "! grep -q 'plan pin' '$T/fix/logs/runner.log'"
printf '# Design branch `delta`\n\nMode: design. Deliver: mockup\nPlan signed off: 2026-11-07 by Selftest\n' > "$T/fix/briefs/delta.md"
printf 'delta\n' > "$T/fix/queue-design.txt"
( cd "$T/fix" && QUEUE=queue-design.txt STAGGER_SECS=0 POLL_SECS=1 ./runner.sh > "$T/runner2.out" 2>&1 ) &
r=$!; wait_for 30 sh -c "! kill -0 $r"; kill $r 2>/dev/null
check "runner: a queue with a design branch checks the plan pin too" grep -q "plan pin claude-opus-5-5, xhigh" "$T/fix/logs/runner.log"
wtr=$(sed -n 's/^WT_ROOT=//p' "$T/fix/loop.conf" | tr -d "'")
printf '# Design branch `eps`\n\nMode: design. Deliver: mockup\nPlan signed off: 2026-11-07 by Selftest\n' > "$T/fix/briefs/eps.md"
mkdir -p "$wtr/eps/.fixloop"
echo '{"slug":"eps","status":"todo","phase":null,"pr":null,"notes":["2026-11-06T10:00:00 SIGNED OFF (Selftest, 2026-11-06): M1-A."],"reviews":[],"summary":""}' > "$wtr/eps/.fixloop/status.json"
printf 'eps\n' > "$T/fix/queue-signed.txt"
( cd "$T/fix" && QUEUE=queue-signed.txt STAGGER_SECS=0 POLL_SECS=1 ./runner.sh > "$T/runner3.out" 2>&1 ) &
r=$!; wait_for 30 sh -c "! kill -0 $r"; kill $r 2>/dev/null
check "runner: a queue whose design branch is signed off checks only the code pin" \
    sh -c "grep 'preflight ok' '$T/fix/logs/runner.log' | tail -1 | grep -q 'queue queue-signed.txt' && ! grep 'preflight ok' '$T/fix/logs/runner.log' | tail -1 | grep -q 'plan pin'"
grep -qiE "unbound|command not found|invalid option|syntax error" "$T/runner.out" && bad "runner: shell errors: $(grep -iE 'unbound|not found|invalid|syntax' "$T/runner.out" | head -2)"
printf '# Fix branch `zeta`\n\nDefects: D1\n' > "$T/fix/briefs/zeta.md"
printf 'zeta\n' > "$T/fix/queue-unsigned.txt"
out=$(cd "$T/fix" && QUEUE=queue-unsigned.txt STAGGER_SECS=0 POLL_SECS=1 ./runner.sh 2>&1)
check "runner: refuses a branch whose brief has no signed-off plan" sh -c "echo \"\$1\" | grep -q 'STOP: zeta.*Plan signed off'" _ "$out"
check "... and starts nothing" sh -c "! grep -q 'chain started: zeta' '$T/fix/logs/runner.log'"

echo "== live pages: one per chain, kept current from its state, never committed"
lw="$wtr/lp"; mkdir -p "$lw/.fixloop/state"
printf '# Fix branch `lp`\n\nTitle: Retry Bills The Right Customer\nPlan signed off: 2026-11-07 by Selftest\n\n## Tasks\n- T1 · A retry bills the current customer · proved by: RetryBillsCurrentCustomer\n' > "$lw/.fixloop/brief.md"
cp "$lw/.fixloop/brief.md" "$T/fix/briefs/lp.md"
cat > "$lw/.fixloop/status.json" <<'EOF'
{"slug": "lp", "status": "in_progress", "phase": "green", "pr": null, "summary": "", "reviews": [], "tasks_done": [],
 "notes": ["2026-11-07T13:41:00 [red] Failing test committed: a retry after a customer change bills the old customer (9b07f13)",
           "2026-11-07T14:31:00 [green] Fix committed: a retry bills the customer the order has now (c41e9a2)"],
 "asks": [{"id": "Q1", "title": "Which Customer A Retry Bills", "question": "Which customer should the retry bill?",
           "options": [{"key": "a", "text": "The customer the order has now"}, {"key": "b", "text": "The customer it was queued for"}],
           "recommend": "a", "at": "2026-11-07T14:20:00", "status": "open"}]}
EOF
(cd "$T/fix" && "$PY" live_page.py lp > "$T/lp.out" 2>&1)
check "live_page writes the page into the run folder as live/lp.live.html" test -f "$T/fix/live/lp.live.html"
check "... with its settings filled in" sh -c "grep -q 'Retry Bills The Right Customer' '$T/fix/live/lp.live.html' && ! grep -qE '__CONFIG__|__TWO_WAY__' '$T/fix/live/lp.live.html'"
check "... and prints the capabilities to publish it with" grep -q '"db"' "$T/lp.out"
check "... where only the owner writes the answers and approvals relayed to the chain" \
    sh -c "grep -q '\"path\": \"answers\", \"read\": \"view\", \"write\": \"owner\"' '$T/lp.out' && grep -q '\"path\": \"approvals\", \"read\": \"view\", \"write\": \"owner\"' '$T/lp.out'"
if [ "$CLONE" = 1 ]; then
    check "the repo ignores *.live.html, so a live page can never be committed" git -C "$REPO" check-ignore -q skills/metaloop/x.live.html
else
    skip "the MetaLoop repository ignores *.live.html (not a clone of it)"
fi
(cd "$T/fix" && "$PY" live_page.py --url lp https://claude.ai/artifact/LP1 >/dev/null)
(cd "$T/fix" && "$PY" live_sync.py lp > "$T/sync1.json" 2>&1)
check "first sync: the state, both progress lines and the open question" "$PY" - "$T/sync1.json" <<'EOF'
import json, sys
page = json.load(open(sys.argv[1]))["pages"][0]
w = page["writes"]; cols = [x["collection"] for x in w]
assert page["slug"] == "lp" and page["url"] == "https://claude.ai/artifact/LP1", page
assert cols.count("state") == 1 and cols.count("events") == 2 and cols.count("asks") == 1, cols
assert all(x["op"] == "set" and "if_version" not in x for x in w), w   # every write creates a new document
st = [x for x in w if x["collection"] == "state"][0]["data"]
assert st["badge"]["tone"] == "warn" and st["tasks"][0]["id"] == "T1", st
EOF
(cd "$T/fix" && "$PY" live_sync.py lp > "$T/sync1b.json" 2>&1)
check "until --done, the same writes are offered again" cmp -s "$T/sync1.json" "$T/sync1b.json"
(cd "$T/fix" && "$PY" live_sync.py lp --done >/dev/null && "$PY" live_sync.py lp > "$T/sync2.json" 2>&1)
check "after --done, an unchanged chain needs no writes" "$PY" -c "import json,sys; o=json.load(open(sys.argv[1])); assert all(not p['writes'] for p in o['pages']), o" "$T/sync2.json"
check "--url without the URL prints the usage, not a Python error" \
    sh -c "out=\$(cd '$T/fix' && '$PY' live_page.py --url lq 2>&1); [ \$? -ne 0 ] && ! echo \"\$out\" | grep -q Traceback"
printf '# Fix branch `lq`\n\nTitle: A Chain Still In The Queue\nPlan signed off: 2026-11-07 by Selftest\n' > "$T/fix/briefs/lq.md"
(cd "$T/fix" && "$PY" live_page.py --url lq https://claude.ai/artifact/LQ1 >/dev/null && "$PY" live_sync.py lq lp > "$T/syncq.json" 2>&1)
check "a chain that hasn't started yet: Queued, and no step done" "$PY" - "$T/syncq.json" <<'EOF'
import json, sys
st = [x["data"] for x in json.load(open(sys.argv[1]))["pages"][0]["writes"] if x["collection"] == "state"][0]
assert st["badge"]["text"] == "Queued" and all(s["state"] == "todo" for s in st["steps"]), st
EOF
check "a page published later shows on the other pages, even one with nothing new" "$PY" - "$T/syncq.json" <<'EOF'
import json, sys
w = json.load(open(sys.argv[1]))["pages"][1]["writes"]
assert [x["collection"] for x in w] == ["state"] and [p["slug"] for p in w[0]["data"]["peers"]] == ["lq"], w
EOF
(cd "$T/fix" && "$PY" live_sync.py lq lp --done >/dev/null)
(cd "$lw" && "$PY" "$T/fix/task.py" phase docs "Docs updated: the sync retry section" >/dev/null)
(cd "$T/fix" && "$PY" live_sync.py lp > "$T/sync3.json" 2>&1)
check "a new step: one new line and a new state, nothing sent twice" "$PY" -c "import json,sys; w=json.load(open(sys.argv[1]))['pages'][0]['writes']; assert sorted(x['collection'] for x in w)==['events','state'], w" "$T/sync3.json"
(cd "$T/fix" && "$PY" live_sync.py lp --done >/dev/null)
att=$(cd "$T/fix" && "$PY" live_sync.py --attention 2>&1)
check "--attention prints the main window's line for the open question, with the link" \
    sh -c "echo \"\$1\" | grep -q 'Needs you · lp: Which Customer A Retry Bills → https://claude.ai/artifact/LP1'" _ "$att"
(cd "$lw" && "$PY" "$T/fix/task.py" review "CodeRabbit #101: a deleted order crashes the retry, Retry.cs:40" "Skip the retry and log it" >/dev/null)
(cd "$T/fix" && "$PY" live_sync.py lp > "$T/sync4.json" 2>&1)
check "a review item waits for the main session's recommendation" "$PY" -c "import json,sys; w=json.load(open(sys.argv[1]))['pages'][0]['writes']; assert not [x for x in w if x['collection']=='reviews'], w" "$T/sync4.json"
echo '{"1": "Apply"}' > "$T/fix/live/lp.recs.json"
(cd "$T/fix" && "$PY" live_sync.py lp > "$T/sync5.json" 2>&1)
check "... and goes up with it" "$PY" -c "import json,sys; r=[x for x in json.load(open(sys.argv[1]))['pages'][0]['writes'] if x['collection']=='reviews']; assert len(r)==1 and r[0]['data']['rec']=='Apply', r" "$T/sync5.json"
mkdir -p "$T/fix/retired/lr"   # what retire.sh keeps of a merged chain once its worktree is gone
echo '{"slug":"lr","status":"done","phase":"ci","pr":{"number":7,"url":"https://github.com/o/r/pull/7"},"summary":"merged","notes":["2026-11-07T15:00:00 [ci] CI passed"],"reviews":[]}' > "$T/fix/retired/lr/status.json"
(cd "$T/fix" && "$PY" live_sync.py lr > "$T/syncr.json" 2>/dev/null)
check "after its worktree is retired, a chain's page keeps its state: Done, with its PR" "$PY" - "$T/syncr.json" <<'EOF'
import json, sys
st = [x["data"] for x in json.load(open(sys.argv[1]))["pages"][0]["writes"] if x["collection"] == "state"][0]
assert st["badge"]["text"] == "Done" and st["pr"]["number"] == 7, st
EOF

echo "== wait_chain: wakes for a question as well as a chain end, and for progress to sync"
n0=$(wc -l < "$T/fix/logs/runner.log")
echo "[11-07 14:20:00] [lp] chain asks: lp Q2 · Another Question" >> "$T/fix/logs/runner.log"
( cd "$T/fix" && WAIT_POLL_SECS=1 LIVE_SYNC_SECS=0 ./wait_chain.sh "$n0" > "$T/wc1.out" 2>&1 ) & r=$!
wait_for 20 sh -c "! kill -0 $r"; kill $r 2>/dev/null
check "a 'chain asks' line returns at once" grep -q "chain asks: lp Q2" "$T/wc1.out"
n1=$(wc -l < "$T/fix/logs/runner.log")
( cd "$T/fix" && WAIT_POLL_SECS=1 LIVE_SYNC_SECS=3 ./wait_chain.sh "$n1" > "$T/wc2.out" 2>&1 ) & r=$!
sleep 2; echo "[11-07 14:21:00] [runner] chain started: lq" >> "$T/fix/logs/runner.log"; touch "$lw/.fixloop/status.json"
wait_for 30 sh -c "! kill -0 $r"; kill $r 2>/dev/null
check "no chain event, but a chain's state changed: it returns after LIVE_SYNC_SECS naming the chain" \
    sh -c "grep -q 'progress' '$T/wc2.out' && grep -q 'lp' '$T/wc2.out'"
check "... handing back the same from-line, so a stop logged meanwhile is still read next time" grep -qx "== next from-line: $n1" "$T/wc2.out"

echo "== platform helpers"
p=$(free_port)
"$PY" -m http.server "$p" --bind 127.0.0.1 >/dev/null 2>&1 &
wait_for 20 curl -s "http://127.0.0.1:$p/" -o /dev/null
pid=$(bash -c "source '$T/fix/platform.sh' && port_pid $p")
check "port_pid finds the process listening on :$p ($pid)" test -n "$pid"
bash -c "source '$T/fix/platform.sh' && kill_tree $pid"
check "kill_tree stops it" wait_for 10 sh -c "! curl -s http://127.0.0.1:$p/ -o /dev/null"
check "sha1 prints a SHA-1" sh -c "echo x | bash -c \"source '$T/fix/platform.sh' && sha1\" | grep -qE '^[0-9a-f]{40}'"
[ "$WIN" = 1 ] || check "cygpath stands in for Git Bash's on POSIX" \
    test "$(bash -c "source '$T/fix/platform.sh' && cygpath -m '$T/a b'")" = "$T/a b"

echo "== test-output parsers: every preset reads its runner's summary, failures and names"
check "dotnet, pytest, jest, vitest, go, cargo, rspec, maven and phpunit output, passing, failing and empty" "$PY" - "$T/fix" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1]); import project as P
cases = [
 ("dotnet", "  Failed Billing.Tests.RetryTests.Retry_BillsTheCurrentCustomer [147 ms]\nFailed! - Failed:     1, Passed:   120, Skipped:     0, Total:   121\nPassed! - Failed:     0, Passed:    40, Skipped:     0, Total:    40", 1, 160, ["Billing.Tests.RetryTests.Retry_BillsTheCurrentCustomer"]),
 ("pytest", "FAILED tests/test_retry.py::test_bills - AssertionError\nERROR tests/test_db.py::test_conn - ConnectionError\n===== 1 failed, 12 passed, 1 error, 2 warnings in 3.21s =====", 2, 12, ["tests/test_db.py::test_conn", "tests/test_retry.py::test_bills"]),
 ("pytest", "3 passed in 0.12s", 0, 3, []),
 ("pytest", "========== no tests ran in 0.01s ==========", 0, 0, []),
 ("jest", "  ● Retry › bills the current customer\n  ● Console\nTests:       1 failed, 30 passed, 31 total", 1, 30, ["Retry › bills the current customer"]),
 ("vitest", " FAIL  src/retry.test.ts > Retry > bills\n      Tests  1 failed | 22 passed (23)", 1, 22, ["src/retry.test.ts > Retry > bills"]),
 ("go", "--- FAIL: TestRetry (0.00s)\n--- PASS: TestSign (0.00s)\n    --- PASS: TestSign/vector (0.00s)\nFAIL", 1, 2, ["TestRetry"]),
 ("cargo", "test retry::bills ... FAILED\ntest result: FAILED. 9 passed; 1 failed; 0 ignored\ntest result: ok. 4 passed; 0 failed; 0 ignored", 1, 13, ["retry::bills"]),
 ("rspec", "rspec ./spec/retry_spec.rb:12 # Retry bills\n25 examples, 1 failure, 2 pending", 1, 22, ["./spec/retry_spec.rb:12"]),
 ("maven", "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.05 s - in com.x.SignTest\n[ERROR] com.x.RetryTest.bills  Time elapsed: 0.01 s  <<< FAILURE!\n[ERROR] Tests run: 5, Failures: 1, Errors: 0, Skipped: 0", 1, 4, ["com.x.RetryTest.bills"]),
 ("phpunit", "OK (12 tests, 30 assertions)", 0, 12, []),
 ("phpunit", "1) Tests\\RetryTest::testBills\nFAILURES!\nTests: 12, Assertions: 30, Failures: 1.", 1, 11, ["Tests\\RetryTest::testBills"]),
]
for kind, text, f, p, names in cases:
    r = P.parse_tests(text, kind)
    assert (r["failed"], r["passed"], r["failed_tests"]) == (f, p, names), (kind, r)
assert P.parse_tests("no summary here", "jest")["failed"] is None
EOF

echo "== presets: every stack, alone and with a database, makes a profile whose only gaps are marked"
pr="$T/presets-repo"; mkdir -p "$pr" && git -C "$pr" init -q
check "init_project.py --list names every stack and service" sh -c "'$PY' '$KIT/init_project.py' --list | grep -q java-maven && '$PY' '$KIT/init_project.py' --list | grep -q mongodb"
check "each composes; a stack with a database gives its test step and the verify loop that database" "$PY" - "$KIT" "$pr" "$T/fix" <<'EOF'
import json, os, subprocess, sys
kit, repo, run = sys.argv[1:]
sys.path.insert(0, run); import project as P
stacks = sorted(f[:-5] for f in os.listdir(os.path.join(kit, "presets", "stacks")))
dbs = sorted(f[:-5] for f in os.listdir(os.path.join(kit, "presets", "services")))
assert len(stacks) >= 10 and {"postgres", "mysql", "mongodb", "redis", "sqlite"} <= set(dbs), (stacks, dbs)
for stack in stacks:
    for db, via in [(None, "docker")] + [(d, v) for d in dbs for v in ("docker", "native")]:
        args = [sys.executable, os.path.join(kit, "init_project.py"), "--stack", stack, "--via", via, "--force"] + (["--db", db] if db else [])
        r = subprocess.run(args, cwd=repo, capture_output=True, text=True)
        assert r.returncode == 0, (stack, db, via, r.stderr)
        p = json.load(open(os.path.join(repo, ".metaloop", "project.json")))
        probs = [x for x in P.problems(p) if "FILL IN" not in x]
        assert not probs, (stack, db, via, probs)
        if db:
            assert any(db in s.get("services", []) for s in p["gate"]["steps"]), (stack, db)
            assert db in P.verify_services(p) and "{project}" not in json.dumps(p), (stack, db)
            assert db == "sqlite" or P.service_spec(p, db, "verify").get("port") != P.service_spec(p, db).get("port"), (stack, db)
r = subprocess.run([sys.executable, os.path.join(kit, "init_project.py"), "--stack", "node"], cwd=repo, capture_output=True, text=True)
assert r.returncode != 0 and "--force" in r.stderr, r.stderr  # never written over by accident
EOF

echo "== gate: the profile's steps, a fresh service per slot, test parsers, GATE_SKIP"
wt="$T/wt"; mkdir -p "$wt/.fixloop"
gate_run() {  # waits for a verdict; prints --status
    (cd "$wt" && "$PY" "$T/fix/gate.py" --start >/dev/null 2>&1)
    wait_for 180 sh -c "cd '$wt' && '$PY' '$T/fix/gate.py' --status | grep -qE '^gate (PASS|FAIL)'"
    (cd "$wt" && "$PY" "$T/fix/gate.py" --status)
}
init fix "$T/fix" GATE_SKIP= KNOWN_FLAKES= KNOWN_PLATFORM_FAILURES=
: > "$SELFTEST_LOG"; out=$(gate_run)
if ! echo "$out" | grep -q '^gate PASS'; then
    echo "  gate diagnostic: $out"
    for f in "$wt"/.fixloop/logs/gate-*.log "$wt"/.fixloop/logs/gate-runner.err "$wt"/.fixloop/logs/service-*.log; do
        [ -f "$f" ] && { echo "  --- $f"; cat "$f"; }
    done
fi
check "gate passes ($(echo "$out" | head -1))" sh -c "echo \"\$1\" | grep -q '^gate PASS'" _ "$out"
check "every step ran with the profile's env" sh -c "[ \$(grep -c '^st-run' '$SELFTEST_LOG') = 3 ] && ! grep '^st-run' '$SELFTEST_LOG' | grep -qv 'LC_ALL=en_US.UTF-8'"
check "the step that names a service reached its own instance, set up by its init" grep -q "^svc=pong" "$SELFTEST_LOG"
check "only that step got the service's env" sh -c "[ \$(grep -c 'SVC=http://127.0.0.1:$SVC_PORT' '$SELFTEST_LOG') = 1 ]"
check "the service is stopped afterwards" wait_for 15 sh -c "! curl -s http://127.0.0.1:$SVC_PORT/ -o /dev/null"
check "and its folder removed" sh -c "! ls -d '$wt'/.fixloop/state/svc-web-* 2>/dev/null | grep -q ."
check "the verdict names each step's summary and the services it used" sh -c "echo \"\$1\" | grep -q 'unit: Tests: *3 passed' && echo \"\$1\" | grep -q 'services: SVC_URL'" _ "$out"
: > "$SELFTEST_LOG"; out=$(SELFTEST_UNIT_FAIL="Retry › bills the current customer" gate_run)
check "a failing test fails the gate and is named" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'FAILED Retry › bills the current customer'" _ "$out"
check "... and the suites after it still run" grep -q "st-run test integration" "$SELFTEST_LOG"
init fix "$T/fix" KNOWN_FLAKES="bills the current customer"
out=$(SELFTEST_UNIT_FAIL="Retry › bills the current customer" gate_run)
check "a known flake is reported, not counted" sh -c "echo \"\$1\" | grep -q '^gate PASS' && echo \"\$1\" | grep -q 'known flaky (confirm alone): Retry'" _ "$out"
init fix "$T/fix" KNOWN_FLAKES= KNOWN_PLATFORM_FAILURES="bills the current customer"
out=$(SELFTEST_UNIT_FAIL="Retry › bills the current customer" gate_run)
check "a platform failure is reported apart from flakes, not re-run alone" sh -c "echo \"\$1\" | grep -q '^gate PASS' && echo \"\$1\" | grep -q 'fails on this platform every time'" _ "$out"
init fix "$T/fix" KNOWN_PLATFORM_FAILURES=
out=$(SELFTEST_ZERO=1 gate_run)
check "a suite that ran zero tests fails the gate" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'NO TESTS RAN'" _ "$out"
: > "$SELFTEST_LOG"; out=$(SELFTEST_BUILD_FAIL=1 gate_run)
check "a failed build stops the gate, with the step's hint" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'the toolchain is incomplete' && ! grep -q 'st-run test' '$SELFTEST_LOG'" _ "$out"
init fix "$T/fix" GATE_SKIP=integration
: > "$SELFTEST_LOG"; out=$(gate_run)
check "GATE_SKIP: the gate passes and names the step it left out, with what checks it instead" \
    sh -c "echo \"\$1\" | grep -q '^gate PASS.*integration' && echo \"\$1\" | grep -q \"SKIPPED (GATE_SKIP): CI's integration job runs it\"" _ "$out"
check "GATE_SKIP: the step never ran" sh -c "! grep -q 'st-run test integration' '$SELFTEST_LOG'"
write_profile "$T/dead.json" "p['services']['web'].update(start='exec sleep 611', up=None, init=None, timeout=4)"
init fix "$T/fix" GATE_SKIP= PROJECT="$T/dead.json"
out=$(gate_run)
check "a service that never comes up fails the gate, with why" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'web did not come up within 4s'" _ "$out"
check "... and is stopped" wait_for 10 sh -c "! pgrep -f 'sleep 611' >/dev/null"
"$PY" -m http.server "$SVC_PORT" --bind 127.0.0.1 >/dev/null 2>&1 & squat=$!
wait_for 20 curl -s "http://127.0.0.1:$SVC_PORT/" -o /dev/null
init fix "$T/fix" PROJECT="$T/project.json"
out=$(gate_run); kill $squat 2>/dev/null
check "a service port someone else holds is never shared: the gate says which" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'port $SVC_PORT is already taken'" _ "$out"
write_profile "$T/nogate.json" "p['gate']['steps'] = []"
init fix "$T/fix" PROJECT="$T/nogate.json"
out=$(gate_run)
check "a profile with no gate steps fails the gate and says so" sh -c "echo \"\$1\" | grep -q '^gate FAIL' && echo \"\$1\" | grep -q 'no gate.steps'" _ "$out"
init fix "$T/fix" PROJECT="$T/project.json"

echo "== verify ledger: Requires: lines"
printf '# T1 · Takes A Card Payment\nRequires: payments\n' > "$T/ver/tests/T1.md"
printf '# T2 · Plain\n' > "$T/ver/tests/T2.md"
(cd "$T/ver" && "$PY" init_ledger.py "Selftest" >/dev/null && "$PY" ledger.py requires-check "" >/dev/null)
st() { "$PY" -c "import json,sys; d=json.load(open('$T/ver/ledger.json')); print([t for t in d['tests'] if t['id']==sys.argv[1]][0][sys.argv[2]])" "$1" "$2"; }
check "a test whose requirement is missing is blocked up front" test "$(st T1 status)" = blocked
check "with the ask to make it available, from the profile's caps" sh -c "echo \"\$1\" | grep -q 'payment provider' " _ "$(st T1 ask)"
check "a test with no requirement stays todo" test "$(st T2 status)" = todo
(cd "$T/ver" && "$PY" init_ledger.py "Selftest" --force >/dev/null && "$PY" ledger.py requires-check "payments" >/dev/null)
check "a met requirement leaves the test todo" test "$(st T1 status)" = todo
(cd "$T/ver" && "$PY" ledger.py needs T2 "Turn on the sandbox test card for the test account" >/dev/null)
(cd "$T/ver" && "$PY" live_page.py verify >/dev/null 2>&1 && "$PY" live_page.py --url verify https://claude.ai/artifact/V1 >/dev/null \
    && "$PY" live_sync.py verify > "$T/vsync.json" 2>&1)
check "verify: its live page gets the ledger's counts and the blocked test's ask" "$PY" - "$T/vsync.json" <<'EOF'
import json, sys
w = json.load(open(sys.argv[1]))["pages"][0]["writes"]
st = [x["data"] for x in w if x["collection"] == "state"][0]
asks = [x["data"] for x in w if x["collection"] == "asks"]
assert st["counts"]["blocked"] == 1 and st["counts"]["todo"] >= 2, st
assert [a["kind"] for a in asks] == ["needs"] and "sandbox" in asks[0]["question"], asks
EOF
cat > "$T/ver/ledger.json" <<'EOF'
{"tests": [{"id": "T1", "title": "Bill A Card", "status": "awaiting_human", "started": "2026-11-07T15:00:00", "ask": "Sign in to the accounting sandbox"}], "sessions": []}
EOF
(cd "$T/ver" && "$PY" live_sync.py verify >/dev/null 2>&1 && "$PY" live_sync.py verify --done >/dev/null)
"$PY" -c "import json,sys; d=json.load(open(sys.argv[1])); d['tests'][0].update(status='pass', finished='2026-11-07T15:09:00'); json.dump(d, open(sys.argv[1], 'w'))" "$T/ver/ledger.json"
(cd "$T/ver" && "$PY" live_sync.py verify > "$T/vsync2.json" 2>&1)
check "verify: once the sign-in is done, its card leaves the page" "$PY" - "$T/vsync2.json" <<'EOF'
import json, sys
st = [x["data"] for x in json.load(open(sys.argv[1]))["pages"][0]["writes"] if x["collection"] == "state"][0]
assert [k for k in st["answered"] if "@signin@" in k], st
EOF
mkdir -p "$T/ver/logs"; echo "[11-07 15:10:00] T2 started" >> "$T/ver/logs/loop.log"; v0=$(wc -l < "$T/ver/logs/loop.log")
( cd "$T/ver" && WAIT_POLL_SECS=1 LIVE_SYNC_SECS=3 ./wait_verify.sh "$v0" > "$T/wv.out" 2>&1 ) & r=$!
sleep 2; echo "[11-07 15:11:00] T2 step 2" >> "$T/ver/logs/loop.log"; touch "$T/ver/ledger.json"
wait_for 30 sh -c "! kill -0 $r"; kill $r 2>/dev/null
check "wait_verify: a progress return hands back the same from-line, so a stop logged meanwhile is still read" \
    sh -c "grep -q 'progress' '$T/wv.out' && grep -qx '== next from-line: $v0' '$T/wv.out'"

echo "== the verify loop's services: kept, seeded once, reused"
sv() { (cd "$T/ver" && "$PY" services.py "$@" --state state) 2>"$T/sv.err"; }
out=$(sv up --for verify)
if ! echo "$out" | grep -q "export SVC_URL=http://127.0.0.1:$VSVC_PORT"; then
    echo "  verify service diagnostic: $out"
    [ ! -f "$T/sv.err" ] || { echo "  --- services.py stderr"; cat "$T/sv.err"; }
    [ ! -f "$T/ver/logs/service-web.log" ] || { echo "  --- service-web.log"; cat "$T/ver/logs/service-web.log"; }
fi
check "up starts the verify instance on its own port and prints its env" sh -c "echo \"\$1\" | grep -q \"export SVC_URL=http://127.0.0.1:$VSVC_PORT\"" _ "$out"
check "... seeds its new persist folder once" sh -c "[ \$(grep -c seeded '$T/seed.log') = 1 ] && [ -f '$T/persist-web/.metaloop-ready' ]"
check "env gives the same export lines to the build and the app" sh -c "(cd '$T/ver' && '$PY' services.py env --state state) | grep -q 'SVC_URL=http://127.0.0.1:$VSVC_PORT'"
cp "$T/ver/state/services.json" "$T/services.first.json"
out=$(sv up --for verify)
check "a second up reuses the instance already answering, and doesn't seed again" \
    sh -c "grep -q 'reusing' '$T/sv.err' && [ \$(grep -c seeded '$T/seed.log') = 1 ]"
cp "$T/services.first.json" "$T/ver/state/services.json"
sv down
check "down stops what up started" wait_for 15 sh -c "! curl -s http://127.0.0.1:$VSVC_PORT/ -o /dev/null"
check "... and keeps the persist folder" test -f "$T/persist-web/.metaloop-ready"
out=$(sv up --for verify); sv down
check "a later run starts it on the kept data without seeding it again" sh -c "[ \$(grep -c seeded '$T/seed.log') = 1 ]"
exp=$(cd "$T/ver" && "$PY" project.py exports verify)
check "the app's env comes from the profile, with {app_port} filled in" sh -c "echo \"\$1\" | grep -q 'export LC_ALL=en_US.UTF-8'" _ "$exp"

echo "== native database presets, for real where the servers are installed"
for svc in postgres mongodb; do
    case $svc in postgres) need="initdb pg_isready psql"; probe='psql "$DATABASE_URL" -tAc "select current_database()"'; want=app ;;
                 mongodb) need="mongod mongosh"; probe='mongosh --quiet "$MONGO_URL" --eval "db.hello().isWritablePrimary"'; want=true ;; esac
    have=1; for t in $need; do command -v "$t" >/dev/null || have=0; done
    if [ "$WIN" = 1 ] || [ "$have" = 0 ]; then skip "native $svc preset: $need not installed (or Windows)"; continue; fi
    got=$("$PY" - "$T/fix" "$KIT/presets/services/$svc.json" "$(free_port)" "$T/native-$svc" "$probe" 2>&1 <<'EOF'
import json, os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import services as S
spec = dict(json.load(open(sys.argv[2]))["native"], port=int(sys.argv[3]) - 1)
os.makedirs(sys.argv[4], exist_ok=True)
with S.Service("db", spec, slot=1, state=sys.argv[4], logs=sys.argv[4]) as env:
    print(subprocess.run(["bash", "-c", sys.argv[5]], env=dict(os.environ, **env), capture_output=True, text=True, timeout=60).stdout.strip())
print("free" if not S.listening(int(sys.argv[3])) else "still listening")
print("left: " + " ".join(d for d in os.listdir(sys.argv[4]) if d.startswith("svc-")))
EOF
)
    check "native $svc: comes up on its slot's port and answers ($(echo "$got" | head -1))" sh -c "echo \"\$1\" | head -1 | grep -qx '$want'" _ "$got"
    check "native $svc: stopped, its port free and its data removed" sh -c "echo \"\$1\" | grep -qx free && echo \"\$1\" | grep -qx 'left: '" _ "$got"
done

echo "== the run's Chrome: found by its profile, stopped without touching any other Chrome"
if [ "$WIN" = 0 ] && [ -e "$chrome" ]; then
    cp=$(free_port)
    "$chrome" --headless=new --remote-debugging-port="$cp" --user-data-dir="$T/chrome-profile" --no-first-run about:blank >/dev/null 2>&1 &
    wait_for 30 curl -s "http://127.0.0.1:$cp/json/version" -o /dev/null
    cpid=$(bash -c "source '$T/ver/platform.sh' && chrome_main_pid '$T/chrome-profile'")
    check "chrome_main_pid finds it ($cpid)" test -n "$cpid"
    bash -c "source '$T/ver/platform.sh' && chrome_stop '$T/chrome-profile'"
    check "chrome_stop stops it" wait_for 15 sh -c "! curl -s http://127.0.0.1:$cp/json/version -o /dev/null"
else
    skip "Chrome helpers: no Chrome (or Windows, where raise_chrome.ps1 does this)"
fi

echo "== launch.sh: detached, kept awake, refused on battery"
if [ "$WIN" = 0 ] && { command -v tmux >/dev/null || command -v screen >/dev/null; }; then
    # caffeinate runs the script in its own place and leaves a helper that takes the no-sleep assertion on its behalf a
    # moment later: the script waits up to 5 s for it
    cat > "$T/hello.sh" <<EOF
#!/usr/bin/env bash
n=0; for _ in 1 2 3 4 5 6 7 8 9 10; do
    n=\$(pmset -g assertions 2>/dev/null | grep -c "on behalf of .bash. (pid \$\$)"); [ "\$n" -ge 1 ] && break; sleep 0.5
done
{ echo ran; echo "\$n"; } > "$T/launched"
EOF
    mkdir -p "$T/battery"; printf '#!/bin/sh\necho "Now drawing from '"'"'Battery Power'"'"'"\n' > "$T/battery/pmset"; chmod +x "$T/battery/pmset"
    if [ "$(uname -s)" = Darwin ]; then
        PATH="$T/battery:$PATH" bash "$T/fix/launch.sh" "$TMUX_NAME" "$T/hello.sh" >/dev/null 2>&1; rc=$?
        check "on battery the launch is refused (exit $rc)" test "$rc" = 3
    fi
    bash "$T/fix/launch.sh" "$TMUX_NAME" "$T/hello.sh" > "$T/launch.out" 2>&1
    check "the script ran detached ($(head -c 80 "$T/launch.out"))" wait_for 10 test -s "$T/launched"
    [ "$(uname -s)" = Darwin ] && check "kept awake: caffeinate holds a no-sleep assertion for it" \
        sh -c "[ \"\$(sed -n 2p '$T/launched')\" -ge 1 ]"
else
    skip "launch.sh: no tmux or screen (or Windows, where it opens mintty)"
fi

echo "== retire: removes a merged PR's worktree, keeps every one that still holds work"
R="$T/rt"; mkdir -p "$R/bin" "$R/prs"
cat > "$R/bin/gh" <<'EOF'
#!/usr/bin/env bash
# gh pr list ... --head <branch> --jq ...: prints what the --jq filter would, from $SELFTEST_PRS/<branch, / as _>
while [ $# -gt 0 ]; do [ "$1" = --head ] && { cat "$SELFTEST_PRS/${2//\//_}" 2>/dev/null; exit 0; }; shift; done
EOF
chmod +x "$R/bin/gh"
export GIT_AUTHOR_NAME=selftest GIT_AUTHOR_EMAIL=selftest@example.com GIT_COMMITTER_NAME=selftest GIT_COMMITTER_EMAIL=selftest@example.com
git init -q --bare "$R/origin.git" && git clone -q "$R/origin.git" "$R/repo" 2>/dev/null
git -C "$R/repo" symbolic-ref HEAD refs/heads/develop
git -C "$R/repo" commit -q --allow-empty -m base && git -C "$R/repo" push -q origin develop 2>/dev/null
echo ".fixloop/" >> "$R/repo/.git/info/exclude"
branch_wt() {   # <run> <slug>: a pushed branch in its own worktree, with the .fixloop state a chain leaves
    git -C "$R/repo" worktree add -q -b "ai-work/$2" "$R/$1-wt/$2" origin/develop 2>/dev/null
    git -C "$R/$1-wt/$2" commit -q --allow-empty -m "$2" && git -C "$R/$1-wt/$2" push -q origin "ai-work/$2" 2>/dev/null
    mkdir -p "$R/$1-wt/$2/.fixloop/logs" && echo '{}' > "$R/$1-wt/$2/.fixloop/status.json"
}
pr() { echo "$3 #1 $(git -C "$R/$1-wt/$2" rev-parse HEAD)" > "$R/prs/ai-work_$2"; }   # <run> <slug> <state>
init fix "$R/r1" REPO="$R/repo" WT_ROOT="$R/r1-wt" && init fix "$R/r2" REPO="$R/repo" WT_ROOT="$R/r2-wt"
branch_wt r1 merged && pr r1 merged MERGED
mkdir -p "$R/r1-wt/merged/.fixloop/state" && echo "1|x|0.42|y" > "$R/r1-wt/merged/.fixloop/state/sessions.txt"
echo "Title: Merged" > "$R/r1-wt/merged/.fixloop/brief.md"
branch_wt r1 closed && pr r1 closed CLOSED
branch_wt r1 open && pr r1 open OPEN
branch_wt r1 dirty && pr r1 dirty MERGED && echo scratch > "$R/r1-wt/dirty/notes.md"
branch_wt r1 ahead && pr r1 ahead MERGED && git -C "$R/r1-wt/ahead" commit -q --allow-empty -m "after the merge"
git -C "$R/repo" worktree add -q --detach "$R/r1-wt/base" origin/develop 2>/dev/null
branch_wt r2 late && pr r2 late MERGED
retire() { PATH="$R/bin:$PATH" SELFTEST_PRS="$R/prs" bash "$R/r1/retire.sh" "$@" >> "$R/retire.out" 2>&1; }
retire
check "retire: listing alone removes nothing" test -d "$R/r1-wt/merged"
retire --apply
check "retire: a merged PR's worktree is removed" test ! -e "$R/r1-wt/merged"
check "retire: ... its local branch deleted" sh -c "! git -C '$R/repo' rev-parse -q --verify refs/heads/ai-work/merged"
check "retire: ... and its state kept in retired/" test -f "$R/r1/retired/merged/status.json"
check "retire: ... with its brief and sessions, so its live page keeps its title and cost" \
    sh -c "[ -f '$R/r1/retired/merged/brief.md' ] && [ -f '$R/r1/retired/merged/state/sessions.txt' ]"
check "retire: a closed PR's worktree is removed" test ! -e "$R/r1-wt/closed"
check "retire: an open PR's worktree is kept" test -d "$R/r1-wt/open"
check "retire: a merged one with an uncommitted file is kept" test -f "$R/r1-wt/dirty/notes.md"
check "retire: a merged one with a commit after the PR's head is kept" test -d "$R/r1-wt/ahead"
check "retire: a worktree on no branch (a base) is kept" test -d "$R/r1-wt/base"
check "retire: another run's late merge is left without --all-runs" test -d "$R/r2-wt/late"
retire --apply --all-runs   # flags in either order
check "retire --all-runs: retires the late merge of the run beside it" test ! -e "$R/r2-wt/late"
check "retire --all-runs: ... keeping its state in that run's retired/" test -f "$R/r2/retired/late/status.json"
check "retire --all-runs: ... and still keeps this run's open PR" test -d "$R/r1-wt/open"

echo "== doctor: a verdict per dependency"
for run in fix ver; do
    "$PY" "$T/$run/doctor.py" --json > "$T/doctor-$run.json" 2>"$T/doctor-$run.err"
    check "$run: doctor --json lists every dependency with a known state" "$PY" - "$T/doctor-$run.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
states = {"ok", "fallback", "skipped", "warn", "missing"}
assert d["items"] and all(i["state"] in states and i["name"] and i["for"] for i in d["items"]), d
assert all(i["install"] or i["state"] in ("ok", "skipped") or i["fallback"] for i in d["items"] if i["state"] != "ok")
EOF
done
"$PY" "$T/fix/doctor.py" > "$T/doctor.txt" 2>&1
check "doctor prints a readable report" grep -q "project profile" "$T/doctor.txt"
dj() { "$PY" "$T/fix/doctor.py" --json | "$PY" -c "import json,sys; i=[x for x in json.load(sys.stdin)['items'] if x['name']==sys.argv[1]]; print(json.dumps(i[0]) if i else '')" "$1"; }
check "doctor: the profile and the tools it requires are checked" sh -c "echo \"\$1\" | grep -q '\"state\": \"ok\"'" _ "$(dj st-run)"
write_profile "$T/needs.json" "p['requires'].append({'tool': 'no-such-tool-xyz', 'for': 'the integration suite', 'install': 'brew install xyz', 'who': 'owner', 'skip': 'integration'})"
init fix "$T/fix" PROJECT="$T/needs.json" GATE_SKIP=
check "doctor: a missing tool blocks the run, with its install and the step the owner may leave out instead" \
    "$PY" -c "import json,sys; i=json.loads(sys.argv[1]); assert i['state']=='missing' and i['ask']=='GATE_SKIP=integration' and 'xyz' in i['install'], i" "$(dj no-such-tool-xyz)"
init fix "$T/fix" PROJECT="$T/needs.json" GATE_SKIP=integration
check "doctor: ... and is skipped once the owner has left that step out" \
    "$PY" -c "import json,sys; i=json.loads(sys.argv[1]); assert i['state']=='skipped', i" "$(dj no-such-tool-xyz)"
write_profile "$T/fill.json" "p['gate']['steps'][0]['run'] = 'FILL IN: the build command'"
init fix "$T/fix" PROJECT="$T/fill.json" GATE_SKIP=
check "doctor: a profile with a FILL IN left blocks the run" \
    "$PY" -c "import json,sys; i=json.loads(sys.argv[1]); assert i['state']=='missing' and 'FILL IN' in i['detail'], i" "$(dj 'project profile')"
init fix "$T/fix" PROJECT="$T/none.json"
rm -f "$T/fix/project.json"
check "doctor: no profile at all blocks the run, and says how to write one" \
    "$PY" -c "import json,sys; i=json.loads(sys.argv[1]); assert i['state']=='missing' and 'init_project.py' in i['install'], i" "$(dj 'project profile')"
init fix "$T/fix" PROJECT="$T/project.json"

echo
echo "$pass passed, $fail failed, $skipped skipped"
[ "$fail" = 0 ]
