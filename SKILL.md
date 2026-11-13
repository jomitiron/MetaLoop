---
name: metaloop
description: Opt-in way to run large engineering work as unattended Claude Code loops with human gates - a plan designed with Google's EGM (Elephant-Goldfish Model: brainstorm, draft, fresh-context Goldfish review), split into parallel branches whose split EGM's Goldfish also review, and signed off on a page, a live-verify loop that tests the app end to end, then parallel fix chains (one git worktree and branch each) that build, gate, open PRs and record review comments, each reporting on its own live page, while the main session orchestrates decisions, design and schema sign-offs, review rounds, merges and re-verification. Use when the user says "run it in a loop", "live verify all of these", "fix all of these in parallel", "overnight", "unattended", or the work spans many defects or branches (roughly 5+ branches, or more than a day of work).
---

# Metaloop

Big work done as **loops of fresh, headless Claude Code sessions**, each small enough to stay sharp, with durable state
in files, a guard that keeps every session's context in bounds, and **the owner deciding at fixed gates**. The main
session you are in is the **orchestrator**: it never does the bulk work itself; it sets up loops, watches them, turns
their output into decisions for the owner, and carries those decisions back in.

At full size that means a test plan of 75 tests run live, a fix plan of 40+ items with a dozen decisions, two or three
waves of parallel PRs (each fix on its own branch, checked out in its own git worktree), design and schema pages signed
off before anything is built, review rounds of 60+ items, merge reconciliation, and a re-verify run.

## When to opt in (and when not)

Opt in when the work is wide: many defects or tests, many branches, independent pieces that can run in parallel, or a
live verification too long for one session. Don't for one bug, one feature branch, or anything you would finish in a
single session: the set-up and the gates cost more than they save.

## Proposing it

When the work fits, offer the loop before starting; never start one unasked. One short message, then the set-up
questions in one batch, each with its recommended answer first:

> This is wide enough for a loop: **N** tests / defects across **M** areas. I'd run it as:
> 1. **Verify**: a headless loop runs the test plan against the e2e stack and records every result. It stops for you
>    only when a person must sign in.
> 2. **Plan**: with EGM. We design it together (`/egm:egm-brainstorm`, `/egm:egm-draft`), fresh reviewers with none of
>    our conversation pick the design apart (`/egm:egm-review`), and you approve it. I split the approved design into
>    branches (each with its own files, the journeys it delivers and its tasks, each with the test that proves it),
>    fresh reviewers check the split for collisions, and it goes on a page for your sign-off. Nothing starts before you
>    sign it off.
> 3. **Fix**: parallel chains, each fix on its own branch in its own worktree: failing test first, fix, docs, the full
>    gate, security review, PR, CI. UI and stored-data changes stop at a page for your sign-off before they're built.
>    Each chain has its own live page: where it is, what it has done, and what it is asking you. Here I only post the
>    link when a page needs you.
> 4. **Review and merge**: each PR's review comments go on its chain's page with my recommendation; you approve there,
>    the chain applies, I answer the threads. You merge; I reconcile conflicts and re-verify.
>
> You'd decide at five points: the plan (the design's approval and the split's sign-off), design sign-offs, schema sign-offs, review items, merges.
> Typical cost: $3 to $15 per PR, $1 to $25 per verify session.

| Question | Options (recommended first) |
|---|---|
| Which models, and how much of its memory may a session use? | Opus 5.5 1M throughout: plan at extra-high effort, code at high, verify at extra-high; hand off at 65%, stop at 72% (never past 75%) · a cheaper model for the verify loop only |
| How many fixes at once? | 5 · 3 (lighter on the machine) · 8 (faster, more gate contention) |
| When may the run stop and wait for you? | Only for a sign-in a person must do · for anything it can't do itself |
| Who merges? | You do · I may merge once CI and the review round are green |

Write the answers into the runbook as the run's hard rules (step 0). If the owner declines, do the work the normal way.

## The roles

| Who | Does | Never does |
|---|---|---|
| **Owner** (the engineer who opted in) | Sets the hard rules, answers the plan's rounds and signs it off, makes every decision, signs off designs and schemas, answers chains and approves review items on their live pages, merges | Babysits sessions |
| **Orchestrator** (this session; EGM's Elephant) | Designs with the owner through EGM, splits the approved design into branches, writes briefs, starts and watches loops, publishes and syncs every live page, relays the owner's answers to the chains, answers PR threads, merges the base into branches, files tickets | Writes the fixes itself; merges; decides for the owner; carries a chain's conversation in the chat |
| **EGM** (Google's plugin, run by the orchestrator) | Brainstorms and drafts the design doc; its Goldfish (fresh subagents with no memory of the conversation) review the design, then the fan-out; drift-reports the design against merged code | Writes code; runs inside a chain |
| **Verify loop** (headless sessions) | Runs the test plan against the live e2e stack, records results in a ledger | Edits code, files anything, pauses for anything but a sign-in |
| **Fix chains** (headless sessions, one branch each, checked out in its own worktree) | red → green → docs → gate → security → PR → CI → records review comments as proposals; asks the owner through its live page (`task.py ask`) | Applies a review comment unapproved, posts to GitHub threads or any page, merges, opens a PR while its question is open |

## Non-negotiables

1. **Context ceiling.** No session's request may pass 75% of its window. `ctx_guard.py` (a PostToolUse hook) asks for a
   hand-off at 65% and ends the session at 72%. Sessions hand over through files, never through memory.
2. **Model pins.** Every call, background calls included, runs on a pinned model and effort. Defaults, all on Opus 5.5
   1M: **plan** at xhigh (the orchestrator's grilling and plan, and a design branch's sessions until its sign-off),
   **code** at high (build sessions), the verify loop at xhigh. A preflight refuses to start otherwise and the guard stops
   any session that drifts.
3. **Human gates are real gates.** Decisions, design (mockup) and schema sign-offs, review-item approvals, database writes
   outside the agreed list, and merges are the owner's. A bare "done" with no comments on the pages is not a sign-off:
   ask. Never work around a safety check (the auto-mode classifier blocks Claude from admin-merging; the owner merges).
4. **Pause only for a sign-in.** The verify loop stops for the owner only when a person must sign in (OAuth, MFA). Every
   other need is recorded as blocked with the exact ask, and the run goes on.
5. **Workers never post or merge.** Chains record; the orchestrator answers every review thread and summary, signed per
   with the tool, the model and the account they were posted from (`threads.py` adds the line), citing commits, and
   checks every claim before posting it.
6. **The brief is binding.** A chain fixes exactly its brief; neighbours become notes, then tickets.
7. **Every long process has a watcher** that reports every terminal state. A pause nobody watches
   sits for hours.
8. **Everything that ships follows the repo's rules**: TDD, the full gate before a PR, `/security-review`, docs with the
   change, mockup and schema sign-off before building, whatever else the repo asks for alongside a PR, PRs to the base.
9. **Nothing is installed without the owner's yes.** Missing tools are found at set-up by `doctor.py`, never mid-run. Loop
   sessions never install anything; a check left out on a machine that can't run it is the owner's decision, written
   into the runbook and named in every PR body or results report.
10. **Planning always happens, and is signed off.** Every fix run plans first, including one that starts from a list of
    tickets: with EGM by default (`PLANNER=egm`: an approved, Goldfish-reviewed design on the base, imported by
    `egm_plan.py`, whose split passes `egm_plan.py check` and the fan-out Goldfish), or by grilling rounds on the plan
    page (`PLANNER=grill`: [skills/grilling](../grilling/SKILL.md), with
    [skills/domain-modeling](../domain-modeling/SKILL.md) writing each decision into the feature's decisions log and each
    settled term into `docs/glossary.md`); then every branch broken into tasks, each with the test that proves it.
    `make_briefs.py` writes no brief until `sign_plan.py` records the owner's sign-off, and the runner starts no branch
    without it.
11. **Every parallel task has its own live page; the chat only links to it.** Each chain, and the verify loop, gets a page
    (`live_page.py`) where the owner sees its progress, answers its questions, decides its review comments and asks it
    things. A new message in the chat pushes an ask out of sight; the page keeps it on top until it is answered. So the
    main window never relays that conversation: for each thing a page needs, it posts one line with the link
    (`live_sync.py --attention`), and again in every status update until it is answered. Live pages are built in the run
    folder as `*.live.html`, which the repo ignores: they are never committed (signed-off mockups and schema pages still
    are).

## The lifecycle

Each phase lists its commands; the details are in the reference files. `<run>` is a run folder made by
`kit/init_run.py`.

### 0. Set up (orchestrator + owner)
- Agree the hard rules with the owner (the set-up questions in "Proposing it") and write them into the run's runbook: the ceiling, the model pins, the pause
  rule, budgets, the approved database writes, who merges.
- The project profile, once per repository: `.metaloop/project.json` says how this project builds, tests and serves,
  which services (databases, caches, queues) its checks need, and which tools. Write it with
  `python skills/metaloop/kit/init_project.py --stack <stack> [--db <service>]...` from the presets (Node, Python,
  Ruby, Go, Rust, Java, .NET, PHP; Postgres, MySQL, MongoDB, Redis, SQLite; Docker or native), fill in what it marks,
  commit it ([reference/project.md](reference/project.md)). Nothing else in MetaLoop knows the stack.
- `python skills/metaloop/kit/init_run.py verify|fix <run> OWNER=<name> [KEY=VALUE ...]` (`python3` on macOS), fill the
  runbook's FILL IN parts.
- `doctor.py` in the run folder lists what this machine is missing, what the run does without each piece and who
  installs it. Clear it before the first start ([reference/orchestrator.md](reference/orchestrator.md), "Missing
  dependencies"): one question to the owner for the installs Claude may run; the exact commands for the ones only they
  can (a password, a first launch, an Apple ID, a licence, a sign-in); any fewer-checks setting they approve
  (`GATE_SKIP`, `START_SERVER=0`) goes into the runbook's hard rules. Re-run it until it exits 0, then check
  `./preflight.sh` prints `ok`.

### 1. Verify ([reference/verify-loop.md](reference/verify-loop.md))
- Test plan → `tests/<ID>.md`, `python init_ledger.py "<title>"`; a verify worktree on the base; the e2e stack and one
  shared Chrome with a persistent profile (the owner signs in there once).
- Its live page first: `live_page.py verify`, publish, `live_page.py --url verify <url>`, `live_sync.py verify` and write.
- Start: `<run>/launch.sh "verify-<name>" <run>/start.sh` (Windows: a minimised mintty window; macOS: a detached tmux
  session under caffeinate). Arm `wait_verify.sh` at once and re-arm it after every event; sync the page each time and
  post the `--attention` lines. On PAUSED: raise the run's
  Chrome (`raise_chrome.sh <tab-url-text>`), tell the owner exactly what to do in which window, arm
  `resume_on_signin.sh` to resume by itself.
- At the end: `ledger.py report`, publish the results page (an Artifact).

### 2. Plan, Always: EGM designs, MetaLoop fans out ([reference/egm.md](reference/egm.md))
- Plan on the plan pin: set this session to Opus 5.5 at xhigh (`/model`, `/effort`) and start the investigation agents
  on it.
- Check each drafted defect against later sessions' notes and the code before calling it real. Investigate by area
  (parallel read-only agents, one per area).
- **Design with EGM** (`PLANNER=egm`, the default): `/egm:egm-brainstorm`, `/egm:egm-draft` into
  `docs/designs/<feature>.md`, `/egm:egm-review` and `/egm:egm-resolve` until no Blocker or Major is open. The owner
  approves it (`Status: Approved`) and merges its PR into the base: chains read it there.
- **Hand it off**: `egm_plan.py import <design> plan.json`; draw up the branches (`files`, `cujs`, `depends_on`, `wave`,
  `tasks` with tests); `egm_plan.py check plan.json` until ok; `egm_plan.py render plan.json fanout.md` and have EGM's
  Goldfish review the split (`/egm:egm-review-loop` with `fanout_readiness.md`); fix `plan.json` and re-render until it
  converges. Then the plan page and sign-off below; `sign_plan.py` runs the check again.
- **Without EGM** (`PLANNER=grill`, [reference/orchestrator.md](reference/orchestrator.md), "Planning (Every Fix Run)"):
  grill the owner in rounds ([skills/grilling](../grilling/SKILL.md)) on the plan page: each round is every question
  that can be answered now, numbered, each with a recommendation. Facts come from the agents, never from the owner.
  `plan_page.py plan.json plan.html "<Title>"`, publish, and post one line in the chat: "Round N is ready → <link>". Read
  the answers from the page (`ArtifactData` list `answers`), record each as the decision's `decided`, and work out the
  next round; [skills/domain-modeling](../domain-modeling/SKILL.md) writes each decision and term down as it lands.
- When no question is left, draw up `plan.json`: defects (why with file:line, fix, size, gate), the decisions by round,
  branches by wave (wave 1 has no gate, wave 2 needs a mockup, wave 3 a schema page), each with a `title` and its `tasks`,
  each task with the test that proves it.
- Either way: `plan_page.py`, publish (an EGM plan's page links the design and shows each branch's files and journeys);
  the owner signs off on the page; `sign_plan.py plan.json "<when>" "<who>"`.

### 3. Build the ungated wave ([reference/fix-loop.md](reference/fix-loop.md))
- `python make_briefs.py plan.json --wave 1`.
- Live pages first ([reference/orchestrator.md](reference/orchestrator.md), "Live Pages"): `live_page.py <every slug in
  the queue>`, publish each with the capabilities it prints, `live_page.py --url <slug> <url>`, then `live_sync.py --all`
  and write each page's writes (`ArtifactData` batch), `live_sync.py --all --done`.
- `<run>/launch.sh "fix-<name> wave1" <run>/start.sh queue-wave1.txt 5`. Arm `wait_chain.sh`: it returns when a chain
  ends or asks, and every `LIVE_SYNC_MIN` minutes with progress. Each time: sync the pages, then post exactly the lines
  `live_sync.py --attention` prints. Relay each answer from a page with `task.py answer` (requeue a stopped chain).
- Each chain ends `awaiting_owner` with a PR, green CI and its review comments as proposals.

### 4. Design the gated waves
- Design briefs (`"mode": "design"`): chains draft a delta mockup or a schema page on the branch and stop.
- Orchestrator: read every page in full; `fix_page.py` for the Artifact contract; check pages that touch the same screen
  for overlaps; publish (`md_to_page.py` for schema markdown); `post_publish.sh` links the README row. Send the owner
  every link with its open questions.
- On an explicit sign-off: `record_signoff.py` (README rows, a SIGNED OFF note, requeue), then run the build queue.
  The chain builds exactly the signed-off page.

### 5. Review Comments, On Each Chain's Page
- As a chain ends `awaiting_owner`: write your recommendation per item, in plain words, to `live/<slug>.recs.json`
  (Apply / Reply only / Owner's call), sync, and post its "Ready" line. The owner approves on the chain's page.
- Read the approvals (`ArtifactData` list `approvals`), `approve.py` writes APPROVED notes and a queue; run it. PRs whose
  items are all reply-only get answered at once.
- As each chain ends: `answer.py <PR> <slug> --map`, write the replies, `answer.py ... replies/<PR>.json`, answer the
  review summary with `threads.py comment`, then tell the owner the PR is ready.

### 6. Merge and integrate
- The owner merges. After every merge batch: `retire.sh --apply` (each merged worktree goes as it merges); check each
  open PR's mergeability; `merge_base.sh <slug>`; resolve conflicts (both sides' additions usually stay; reconcile code
  that both PRs moved, and check auto-merged code still compiles); run the area's tests, then the gate; push;
  `wait_ci.sh`; report. A clean re-merge after a dependency merged still needs a build.

### 7. Re-verify and retire
- Requeue the tests the merged fixes cover (`ledger.py requeue ...`), with notes for guide corrections and anything still
  pending; move the verify worktree to the new base; run the verify loop again. New failures go back to step 2.
- A run planned with EGM: `/egm:egm-drift-report docs/designs/<feature>.md` after each merge batch and at the close;
  the owner decides, per divergence, whether the doc or the code changes.
- File the follow-ups in the team's issue tracker (through its own skill or CLI, if the repo has one). `retire.sh --apply` removes spent worktrees and
  branches; remove the verify and base worktrees by hand. At the start of a new run,
  `retire.sh --all-runs --apply` retires what earlier runs' PRs merged after they closed.

## Keeping the owner informed

- Lead with what needs them: a pause, a decision, a sign-off, a PR to merge. Then what's ready. Then what's running.
- A chain's questions, review items and progress live on its page. The chat carries only the lines `live_sync.py
  --attention` prints ("Needs you · <slug>: <one line> → <link>", "Ready · <slug>: ... → <link>") and the plan's
  "Round N is ready → <link>", each repeated in every status update until it is answered. Never paste a chain's question
  into the chat.
- Name evidence tiers: merged, PR only, local only.
- Never claim what you didn't check, and say so when you got something wrong.
- Once the run is set up, questions go on a page the owner answers on, never into a pop-up; one that isn't any chain's
  goes on the plan page as a new round.

## Run folders

```
<run>/                          one folder per loop (init_run.py)
  loop.conf / loop.json         the run's settings (model pins, thresholds, repo, base, owner, worktree root, platform
                                fallbacks: PYTHON, GATE_SKIP, START_SERVER)
  project.json                  the project profile, copied from the repo: gate steps, services, how the app is served
  services.py, project.py       the project's databases and services (one per gate slot, the verify loop's own), the profile
  runbook.md, settings.json     appended to / given to every session (permissions, hooks)
  ctx_guard.py, end_gate.py     the hooks; logs/ctx.log has every reading
  verify: ledger.json, tests/, guide/, evidence/, HANDOFF.md, PAUSED.md, REPORT.md
  fix:    plan.json (with an EGM run's design, journeys and files), fanout.md, briefs/, queue-*.txt, logs/runner.log, replies/, design-pages.md, locks/ (gate slots)
  live/                         <slug>.live.html (never committed), urls.json, and per page .sync / .pending / .recs json
<WT_ROOT>/<slug>/.fixloop/      per branch: brief.md, status.json, HANDOFF.md, gate.json, logs/
```

## References

- [reference/verify-loop.md](reference/verify-loop.md): the live-verify loop in full.
- [reference/fix-loop.md](reference/fix-loop.md): chains, modes, phases, the gate, permissions.
- [reference/orchestrator.md](reference/orchestrator.md): every main-session procedure, step by step.
- [reference/project.md](reference/project.md): the project profile, the stack and service presets, the gate's parsers.
- [reference/egm.md](reference/egm.md): planning with EGM and the hand-off to the fix chains, step by step.
- [reference/pitfalls.md](reference/pitfalls.md): what went wrong in practice and the fix for each.
- [kit/README.md](kit/README.md): the scripts, what each does, how to start.
