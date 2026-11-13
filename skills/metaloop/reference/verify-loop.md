# The live-verify loop

Runs a written test plan against the running app, test by test, across as many fresh sessions as it takes, and leaves
a ledger of results, drafted defects and the asks only a person can do. It never edits code and never files anything.

## Inputs

- **A test plan** as one markdown file per test: `tests/<ID>.md`, first line `# <ID> · <Title>`, then where it runs,
  preconditions, steps, what the app must show, what a third party must show, and "Watch" lines for suspected gaps.
  An optional `Hint:` line says which steps need the owner and how (see `kit/examples/test.example.md`). An optional
  `Requires: <capability>` line (e.g. `webhooks`) names what the machine must have for the test to run at all: at the start of each
  run, a test whose requirement is missing is recorded blocked with the ask (`ledger.py requires-check`), so no session
  spends itself on it. If the plan is a published page, convert it once with a small script and keep the script with
  the run.
- **Optional `guide/verify.md`**: suspected gaps as table rows `| V1 | what | where | code |`; sessions mark each one
  seen or not seen when a test meets it.
- **`guide/start.md`**: accounts, test data names, timing, how to find a record in each system.

## The stack

Whatever the project is built with, the project profile's `verify` section says how to run it
([project.md](project.md)); nothing in the loop knows the language, framework or database.

- **A verify worktree** on the base (`git worktree add --detach <VERIFY_WORKTREE> origin/<base>`). The loop builds and
  starts the app from it (`verify.build`, then `verify.start` in the background) and waits for `verify.health` on
  `APP_URL` to answer: never from your own checkout.
- **The app's services** (`verify.services`: a database, a cache, a queue, a provider's webhook listener) start first,
  through `services.py`, in Docker or native as the profile says. They get their own ports, apart from the gate's. Data
  can be kept between runs (`persist`) and seeded once when new (`seed`), so the test accounts survive the way a
  container's volume would; an instance already answering is reused (`reuse`). Their env (`DATABASE_URL`, ...) reaches
  the build and the app.
- **Pass the app its settings explicitly.** `verify.env` and the services' env are exported before `verify.start`; a
  framework's own launch or profile file can override shell variables (a webhook secret ignored, every event refused),
  so start it the way that doesn't (e.g. without the launch profile).
- **One shared Chrome** on a debug port with a persistent profile in the run folder. Every session drives it through
  `chrome-devtools-mcp --browserUrl`; the owner signs in to third parties there once and the sign-in survives sessions.
- **Third-party sandboxes only.** A CLI the tests drive goes through a wrapper in the repo that pins its sandbox and
  refuses live mode; the wrapper is the only form of it in `verify_allow`.

## A session

The wrapper (`qa-loop.sh`) starts each session with `claude -p` on the pinned model, the runbook appended to the
system prompt, `settings.json` (permissions and hooks), `mcp.json`, `--permission-mode dontAsk`, no subagents, a budget
cap, and the prompt on stdin: the ledger summary, the previous `HANDOFF.md`, and the guard's stop record if the last
session was force-stopped. It stops the run after two sessions in a row that change nothing in the ledger, or four
that only add notes (no test moved on).

The session works the ledger: `ledger.py next` → read `tests/<ID>.md` → `start` → do it in the browser → `ref` every
record it creates → `set pass|fail|blocked` the moment the test is done → `defect` on a failure (draft only) → next.
Results are never batched: a forced stop loses whatever isn't in the ledger.

Verdicts: **pass** when every expected line is confirmed; **fail** names the line, what was seen and what it should be;
**blocked** when the test can't run as written for a reason outside the feature. A step the plan calls hard to force
isn't forced through the database.

## Pausing and asking

- **Pause only for a sign-in** (`ledger.py pause <ID> "<ask>" --signin`; anything else is refused). The ask must stand on
  its own: which window (the run's Chrome, its profile path), the URL to start from, exactly what to do and pick, what to
  leave open, what the session will check after.
- **Everything else** goes through `ledger.py needs <ID> "<exact ask>"`: the test is recorded as blocked with the ask and
  the run goes on. The ask goes on the run's live page, where the owner answers it, and into `REPORT.md`.
- The wrapper shows the pause in its window, raises a toast, and waits for Enter / `s` / `q` or a `RESUME`, `SKIP` or `QUIT`
  file in the run folder.

## Changing the rules mid-run

The runbook is read at the start of every session, so a new instruction from the owner ("skip every brand test", "you may
create a second sandbox company", "these database writes are approved for these tests") goes into it as a dated section
and applies from the next session. Put test-specific guidance into that test's ledger notes (`ledger.py note`): the next
session sees them through `ledger.py next`. Never edit `qa-loop.sh` while it runs (see pitfalls).

## The orchestrator's job while it runs

0. **Its live page** goes up before the start (`live_page.py verify` in this run folder, publish, `--url`): each test's
   result as it is recorded, the counts, every ask, and the sign-in when it pauses. It is never committed.
1. **Watch it.** `wait_verify.sh` as a background task, re-armed after every event. It returns on PAUSED, the end, a STOP,
   and every `LIVE_SYNC_MIN` minutes when the ledger changed. Each time: `live_sync.py verify`, write, `--done`, and post
   the `live_sync.py --attention` lines (orchestrator reference, "Live Pages"). An answer on the page to an ask: requeue
   the test with the answer as a note.
2. **On a pause:** read `PAUSED.md`; bring the run's Chrome to the front on the right tab
   (`raise_chrome.sh <host>`: the tab over the debug port, then the window, through `raise_chrome.ps1` on Windows and
   System Events on macOS, which asks once for Automation permission); tell the owner in two or three
   lines what to do and in which window (people reach for their own browser); arm
   `resume_on_signin.sh '<pattern only the finished step produces>'` so the loop resumes the moment it's done. If the
   owner says "done" but the run's Chrome shows nothing new, they signed in elsewhere: say so and raise the window again.
3. **Unblock** what you're allowed to: a database write the owner approved for that test (record the values it replaces in
   the test's notes first), then `ledger.py requeue <ID>`. Confirm which copy of a setting the code reads before changing
   one (a settings copy and a config copy of the same stamp both existed; only one was read).
4. **Don't let the stack drift**: if a session reports the server down, restart it with `REUSE_SERVER=0`; keep
   `KEEP_UP=1` when you'll re-run soon.

## Results

- `ledger.py report > REPORT.md`; publish a results page (pass/fail per test with the one-line result, the asks, the
  drafted defects) as an Artifact, and link it from the plan.
- **Re-verifying after fixes merge:** move the verify worktree to the new base (`git checkout --detach origin/<base>`),
  add a note to each test you requeue (what merged, guide corrections, anything still pending and how to judge it), then
  `ledger.py requeue <IDs>` and run the loop again. Requeue only tests whose every defect is fixed; hold the rest.

## Typical costs

Sessions cost $1 to $25 each (a long session with many tests and screenshots is at the top). A 75-test plan takes about
15 sessions over two days, most of it waiting on sign-ins and nightly jobs.
