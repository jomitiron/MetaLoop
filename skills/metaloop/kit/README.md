# Loop kit

Scripts for [metaloop](../SKILL.md). `init_run.py` copies them into a run folder and renders the templates with
the run's settings; you never run them from here. Nothing in the kit assumes a language, framework or database: the
project's own commands, services and tools come from its profile, `.metaloop/project.json`
([reference/project.md](../reference/project.md)), which `init_project.py` writes from the presets in `presets/`.

`<kit>` below is this folder. Installed as a plugin, it is in Claude Code's plugin cache and the skill gives Claude its
path (`${CLAUDE_SKILL_DIR}/kit`); in a clone of the MetaLoop repository it is `skills/metaloop/kit`.

## The project profile

```bash
# from inside the project's repository; --list shows every preset
python3 <kit>/init_project.py --stack <node|python|ruby|go|rust|java-maven|java-gradle|dotnet|php|custom> \
    [--db <postgres|mysql|mongodb|redis|sqlite>]... [--via docker|native]
```

It writes `.metaloop/project.json`: the gate's steps (with the right test-output parser), the services those steps need
(a fresh instance per gate slot, in Docker or native), how the verify loop builds, starts and health-checks the app (its
own services, data kept and seeded once), the tools the machine needs, and the commands sessions may run. Fill in what it
marks `FILL IN`, check the commands against the repo, commit it.

## Prerequisites

`doctor.py` (in every run folder) checks all of these on the machine it runs on, and says for each missing one what the
run does without it and who installs it. The orchestrator runs it at set-up and asks the owner before installing
anything (see [reference/orchestrator.md](../reference/orchestrator.md), "Missing dependencies").

- **Every run:** `claude` CLI signed in · `gh` signed in · Python 3 (`python` on Windows, `python3` on macOS: loop.conf
  `PYTHON`) · `pip install markdown` (for schema pages) · the project profile, and every tool it `requires` (its
  toolchain; Docker, or each native database server, for the services its checks use).
- **Fix runs planned with EGM** (`PLANNER=egm`, the default): Google's EGM plugin in the orchestrator's Claude Code
  (`claude plugin marketplace add google/elephant-goldfish-model`, `claude plugin install egm@egm`, a new session).
  `PLANNER=grill` plans without it.
- **Verify runs:** Chrome · Node (for `npx chrome-devtools-mcp`) · curl · the profile's `verify.start` (or
  `START_SERVER=0` against an app someone runs elsewhere).
- **Windows:** Git Bash with `mintty` and `cygpath`.
- **macOS:** `tmux` (or the `screen` macOS ships) for detached runs; mains power and an open lid for unattended runs
  (`launch.sh` runs them under `caffeinate` and refuses on battery). Nothing else: no Homebrew bash, no `python` shim.

## Start a run

```bash
# from inside the repo (Windows: Git Bash, with a short root like /c/w; macOS: python3, e.g. ~/w)
python <kit>/init_run.py fix    /c/w/<name>  OWNER=<you> SLUG_PREFIX=<area>-fix-
python <kit>/init_run.py verify /c/w/<name>  OWNER=<you> "PAUSE_FOR=<the one sign-in that may pause the run>"
cd /c/w/<name> && python doctor.py && ./preflight.sh  # doctor exits 0, preflight prints ok
./launch.sh "<what>" ./start.sh [queue-file MAX_PAR]  # detached: mintty (Windows) or tmux (macOS)
```

Settings live in `loop.conf` / `loop.json` (re-run `init_run.py` with `KEY=VALUE` to change them: every other setting,
hand edits to `loop.conf` included, and the run's state are kept, and a rendered `runbook.md` or `settings.json` you
edited by hand is kept too, with the new render beside it as `<name>.new`).
Defaults: code on Opus 5.5 1M at high (`MODEL`, `MODEL_ARG`, `EFFORT`), plan on Opus 5.5 1M at xhigh (`PLAN_MODEL`,
`PLAN_MODEL_ARG`, `PLAN_EFFORT`: a design branch's sessions until its sign-off), the verify loop on Opus 5.5 1M at xhigh,
hand-off at 65%, stop at 72%, $150 per session, 10 sessions per chain, 5 chains at once
(on macOS and Linux, one per 8 GB of memory, at most 5), base: the repository's default branch, branches
`ai-work/<SLUG_PREFIX><slug>`,
worktrees in `<run>-wt/`, live pages synced at least every 10 minutes (`LIVE_SYNC_MIN`).

Machine fallbacks (doctor.py says when each applies):

| Key | Default | What |
|---|---|---|
| `PYTHON` | `python` (Windows), `python3` | The interpreter every script, hook, allow-list entry and runbook names. |
| `PROJECT` | `.metaloop/project.json` | The project profile (relative to the repo, or absolute). |
| `GATE_SKIP` | empty | **The owner's decision only:** gate steps (by name) left out on this machine, e.g. one whose service this machine can't run; CI runs it instead. The gate's verdict and every PR body name it. |
| `START_SERVER` | `1` | `0`: the verify loop tests an app already running on `APP_URL` (the profile's `verify.url`). |
| `KNOWN_FLAKES` | empty | Tests that fail only under shared load: reported, not counted; each must pass when run alone. |
| `KNOWN_PLATFORM_FAILURES` | empty | Tests that fail on this platform every time and pass on CI: reported, not counted, never re-run alone. |
| `HAVE_CAPS` | empty | Capabilities this machine has beyond what the loop detects (and the profile's `verify.provides`), for tests with a `Requires:` line. |
| `MOCKUPS_DIR`, `SCHEMA_DIR` | `docs/mockups`, `docs/schema-changes` | Where design chains put pages for sign-off (or the profile's `docs`). |

## Shared (`kit/common`)

| File | What |
|---|---|
| `doctor.py [--json]` | Every dependency: ok, fallback, skipped, warn or missing; what the run does without it; the install and who runs it. Installs nothing. |
| `preflight.sh [plan]` | Prints `ok` when a one-line `claude -p` call reports only the pinned model, window and effort (the code pin, or with `plan` the plan pin). |
| `launch.sh <name> <start.sh> [args]` | Starts a loop without taking focus: minimised mintty (Windows), detached tmux or screen under caffeinate (macOS). |
| `platform.sh` | Sourced by every shell script: the Windows calls (cygpath, toasts, netstat, taskkill, PowerShell) and their macOS / Linux equivalents. |
| `ctx_guard.py`, `session_result.py`, `notify.ps1` | The context and model guard; a session's result line; the Windows toast. |
| `live_page.py`, `live_page.html` | A chain's (or the verify run's) live page, written to `live/<slug>.live.html` in the run folder, never committed (the repo ignores `*.live.html`); `--url` records where it was published. It draws itself from its own database. |
| `live_sync.py` | The writes that keep each live page current (state, lines, questions, review items), for the main session's ArtifactData batch; `--done` once written; `--attention` prints the main window's one line per thing a page needs, with its link. |
| `two_way.js` | Shared by the live pages and the plan page: Ask Claude (Send to Claude), and Claude's answers from the page's `replies`. |
| `project.py` | Reads the project profile: `check`, `get <key>`, `exports <section>`; the test-output parsers the gate uses. |
| `services.py up\|env\|down` | The project's background services (databases, caches, queues, listeners): a fresh one per gate slot, or the verify loop's own (kept, seeded once, reused). |

## Verify run (`kit/verify`)

| File | What |
|---|---|
| `qa-loop.sh` | The wrapper: the profile's verify services, its build and start commands until its health URL answers, the shared Chrome, the preflight, then sessions until done. |
| `start.sh` | Runs the loop and keeps its window: start it with `launch.sh "verify-<name>" <run>/start.sh`. |
| `ledger.py` / `init_ledger.py` | The run's state, and building it from `tests/*.md` (see `kit/examples/test.example.md`; an optional `Requires: <capability>` line names what the machine must have). |
| `runbook.md` | Rendered from the template; fill its FILL IN parts (what is verified, P0, approved writes, how sessions sign in, routes, sandboxes). |
| `settings.json`, `mcp.json` | Session permissions and hooks; the Chrome DevTools MCP on the run's debug port. |
| `end_gate.py` | Stop hook: no ending before the ledger and HANDOFF.md are written. |
| `wait_verify.sh` | Watcher: returns on PAUSED, the end, or a STOP, and every `LIVE_SYNC_MIN` minutes when the ledger changed. |
| `raise_chrome.sh` (`raise_chrome.ps1`), `resume_on_signin.sh` | Put the run's Chrome in front on the right tab; resume the loop when the sign-in lands. |

## Fix run (`kit/fix`)

| File | What |
|---|---|
| `plan.example.json` → `plan.json` | Defects, decisions, branches by wave. |
| `egm_plan.py import\|check\|render\|boundary` | The hand-off from EGM ([reference/egm.md](../reference/egm.md)): imports an approved EGM design doc into `plan.json` (goals, journeys, files, verification); checks the branches drawn from it (design on the base, every file owned once per wave, every journey delivered, dependencies in earlier waves); renders the split as `fanout.md` for the Goldfish review; lists what a chain changed outside its files. |
| `plan.egm.example.json` | A plan imported from an EGM design, with its branches drawn up (`files`, `cujs`, `depends_on`). |
| `fanout_readiness.md`, `fanout-readiness-standard.md` | The Goldfish reviewer and standard `/egm:egm-review-loop` uses on `fanout.md`: hidden coupling within a wave, unowned work, missing dependencies, boundaries too narrow for their tests. |
| `plan_page.py`, `plan_page.html` | The plan page: the owner answers each grilling round on it, reads the plan (branches by wave, each broken into tasks with its proving test) and signs it off. Answers and sign-off live in the page's database. |
| `sign_plan.py` | Records the owner's sign-off in `plan.json`; refuses while a decision is open or a branch has no tasks. |
| `make_briefs.py` | `briefs/<slug>.md` (with the branch's title, tasks and a `Plan signed off:` line) and a queue file, from a signed-off plan only. The runner starts no branch whose brief lacks that line. |
| `start.sh <queue> [MAX_PAR]`, `runner.sh`, `fixloop.sh` | Run a queue of chains in parallel; one chain of sessions per branch. |
| `task.py`, `gate.py` | A branch's state (`task.py pin`: the plan or code pin its next session runs on; `ask` / `answer`: a question for the owner that doesn't stop the chain, and the answer from its live page; `done`: a task ticked); the pre-PR gate (the profile's gate steps, detached, slot-limited, each slot with its own services). |
| `pr_read.py <PR> comments\|reviews\|issue` | The chains' only way to read PR comments: GET only (chains may not call `gh api`). |
| `runbook.md`, `settings.json`, `end_gate.py` | What every chain session is told and allowed; its stop hook. |
| `status.py [queue]` | Every branch's state, phase, PR and last note. |
| `wait_chain.sh`, `wait_gate.sh <slug>`, `wait_ci.sh <PR>...` | Watchers; each times out after `WAIT_HOURS` and prints the state it saw. `wait_chain.sh` also returns on a chain's question, and every `LIVE_SYNC_MIN` minutes when a chain's state changed. |
| `fix_page.py`, `md_to_page.py`, `post_publish.sh` | Make a design page publishable; render a schema page; link the published artifact in its README row. |
| `record_signoff.py` | Record a sign-off on design branches and queue their builds (`--dry-run` first). |
| `approve.py` | Record the owner's review-item approvals (from each chain's live page) and queue the chains that apply them. |
| `threads.py`, `answer.py` | List, reply to and resolve PR threads; answer summaries (the signature line added). |
| `merge_base.sh <slug>` | Bring a branch up to date with the base after merges; `--commit` after resolving starts the gate. |
| `retire.sh [--all-runs] [--apply]` | Remove worktrees and branches of merged PRs, keeping their state. After every merge batch; `--all-runs` covers earlier runs' late merges. |

## Changing the kit

`bash <kit>/selftest.sh` renders both kinds of run from a test profile and runs the scripts against stubs
(claude, pmset, stand-in test runners and services), every test-output parser against sample output, and the native
PostgreSQL and MongoDB presets for real where those servers are installed. Run it on every platform a change touches
(macOS: it runs under the system's bash 3.2; `SELFTEST_BASH=<bash>` picks another). Windows branches stay as they were
unless the change is for Windows.
