# Planning with EGM, fanning out with MetaLoop

A fix run's plan comes from Google's [Elephant-Goldfish Model](https://github.com/google/elephant-goldfish-model) (EGM)
when `PLANNER=egm` (the default). EGM designs: the orchestrator drafts a design doc with the owner and fresh "Goldfish"
subagents review it with no memory of the conversation. MetaLoop then does what EGM leaves to "tell AI to build to the
plan": it splits the approved design into branches, has EGM's Goldfish review that split, and runs the branches as
parallel chains it delegates to and monitors.

| EGM's role | In a MetaLoop run |
|---|---|
| **Elephant** (holds the context, drafts) | The orchestrator: this session, on the plan pin |
| **Goldfish** (fresh reviewers) | Subagents EGM spawns: the design review, then the fan-out review |
| **You** (trade-offs, approval) | The owner |

Chains never run EGM: they can't spawn subagents, and their brief carries what they need from the design.

```text
  the owner's goal, or a verify run's failures
        |
        v   1. Design (EGM; the orchestrator is the Elephant)
  /egm:egm-brainstorm  ->  concepts_brief.md
  /egm:egm-draft       ->  docs/designs/<feature>.md     the owner's go-ahead section by section
  /egm:egm-review      ->  Goldfish stages  ->  /egm:egm-resolve, until no open Blocker or Major
  the owner approves (Status: Approved); the design's PR merges into <base>
        |
        v   2-5. Hand-off (egm_plan.py, in the fix run folder)
  import  ->  plan.json gets the design: goals, journeys, files, verification
  the orchestrator draws the branches: files, cujs, depends_on, wave, tasks with tests
  check   ->  render fanout.md  ->  /egm:egm-review-loop with the fan-out Goldfish  ->  fix the split
  plan_page.py  ->  the owner signs off on the page  ->  sign_plan.py (runs check again)
        |
        v   6. Fan out and monitor (MetaLoop)
  make_briefs.py  ->  every brief carries the design, its file boundary and its journeys
  launch.sh start.sh queue  ->  chains in parallel worktrees, one live page each
  wait_chain.sh, live_sync.py, egm_plan.py boundary  ->  review items  ->  the owner merges
        |
        v   7. After merges
  /egm:egm-drift-report docs/designs/<feature>.md  ->  the owner: update the doc, or the code
```

## 1. Design (EGM)

- Set this session to the plan pin (`PLAN_MODEL` at `PLAN_EFFORT`) before you start, as for any planning.
- `/egm:egm-brainstorm <the work>`. For a run that starts from a verify run, give it the results page and the defects
  you confirmed (orchestrator reference, "Planning", steps 1 to 3: verify before escalating, investigate by area,
  classify). It writes `concepts_brief.md`.
- `/egm:egm-draft` turns the brief into `docs/designs/<feature>.md`. EGM asks one question at a time in the chat and
  waits for the owner's go-ahead after each section: during design, that is the owner's gate (the plan page takes over at
  the sign-off of the fan-out). EGM writes no production code while it designs, and neither do you.
- What the hand-off reads, so make sure the draft has it: a `**Status:**` line; **Goals** and **Non-Goals**; **Open
  Questions** (empty by the end); **Critical User Journeys** as `### CUJ <n>: <title>` with Given / When / Then; and the
  **Detailed Implementation Plan**: `#### <n>. \`<path>\` (Create|Modify|Delete)` per file, with **Type / Scope** and
  **Proposed Changes**, and a **Verification Plan**. A directory glob only for generated output.
- `/egm:egm-review docs/designs/<feature>.md`, then `/egm:egm-resolve` on its findings; repeat until a round leaves no
  unsettled Blocker or Major. EGM's `implementation_readiness` Goldfish holds the plan to its zero-decision rule: a chain
  that has to make a design choice will make a different one from the chain beside it.
- The owner approves: `Status: Approved`. The design goes to `<base>` in a pull request (EGM's human-review step) and the
  owner merges it. Chains branch from `origin/<base>` and read the design there, so `check` refuses until it is merged.

## 2. Import

```bash
python egm_plan.py import <repo>/docs/designs/<feature>.md plan.json
```

It refuses a design that isn't Approved, lists no target files, or still has open questions. `--as-decisions` puts the
open questions on the plan page as round 1 instead; use it only for questions whose answer doesn't change the design
(anything else goes back to `/egm:egm-draft`). It writes `design` (path, sha256, status, link), `goals`, `non_goals`,
`cujs`, `files` and `verify` into `plan.json`. Re-importing a changed design keeps the branches and decisions and clears a
sign-off, so the owner signs the changed plan again.

## 3. Draw up the branches

The same `branches` as any fix run ([fix-loop.md](fix-loop.md), "Briefs"; `plan.egm.example.json` in the run folder),
each with three more fields:

| Field | What |
|---|---|
| `files` | The design's files this branch creates or changes: its binding boundary. A file matching a design glob counts. |
| `cujs` | The journeys it delivers (`CUJ1`, ...). Each is proved by one of its tasks. |
| `depends_on` | Slugs it builds on. Each sits in an earlier wave, and this branch's wave starts after they merge. |

- Split along the design's phases (EGM's readiness standard asks for stable, buildable phases): each phase's files
  become one or more branches of a wave.
- One owner per file per wave. A piece several branches need (an interface, a schema, a registration, a shared fixture)
  goes in an earlier wave they all depend on.
- Tests travel with the code they prove. Tasks are outcomes, each with the test that proves it.
- Waves here order dependencies: wave 1 starts first, and each later wave starts once the branches it builds on merged.
  The sign-off gates still apply inside that order: a change users see needs its mockup signed off, a change to what is
  stored its schema page, before it is built. Make that a `mode: design` branch, and put the build after it in a later
  wave that depends on it (unless the approved design already has the signed-off mockup or schema it needs).
- `python egm_plan.py check plan.json` until it says ok: the design on the base is the one imported and still Approved,
  every design file has an owner, no file has two owners in a wave, every dependency is in an earlier wave, every journey
  is delivered, every build branch names its files.

## 4. Fan-out review (Goldfish)

`check` proves the bookkeeping. Whether separate sessions can really build the branches at once without colliding is a
judgement, so EGM's Goldfish review it with no memory of how the split was made.

```text
python egm_plan.py render plan.json fanout.md

/egm:egm-review-loop
  TargetFile:      <run>/fanout.md
  SemanticTarget:  full file
  Reviewers:       <run>/fanout_readiness.md, implementation_readiness
  Standards:       <run>/fanout_readiness.md -> <run>/fanout-readiness-standard.md,
                   implementation_readiness -> implementation-readiness-standard
  GoldfishContext: docs/designs/<feature>.md, and the directories its files live in
```

The fan-out Goldfish (`fanout_readiness.md`, against `fanout-readiness-standard.md`) looks for hidden coupling within a
wave, unowned work, missing dependencies, boundaries too narrow for their tests, and files that will conflict anyway. The
readiness Goldfish checks each branch can be built without a design choice. `fanout.md` is rendered: apply what
`/egm:egm-resolve` agrees to `plan.json`, re-render, and let the loop run until it converges (two clean rounds; at most
five). A finding that needs the design changed goes back to step 1: draft, review, approve, merge, re-import.

## 5. Sign-off

`plan_page.py plan.json plan.html "<Title>"` and publish, as for any fix run. The page links the design and shows each
branch's files, journeys and dependencies beside its tasks. The owner signs off on the page; `sign_plan.py` runs `check`
again and refuses if the design on the base moved since the import.

## 6. Fan out and monitor

As in [orchestrator.md](orchestrator.md) and [fix-loop.md](fix-loop.md): `make_briefs.py plan.json --wave 1`, live
pages, `launch.sh ... start.sh queue-wave1.txt <MAX_PAR>`, `wait_chain.sh`. What the design adds:

- Every brief has "The design (binding)": the doc as the spec, the branch's files (its boundary) with the design's
  proposed changes for each, its journeys as Given / When / Then, and the design's verification steps.
- A chain stops with `needs` when a change falls outside its boundary or the design doesn't settle it. Answer from the
  design; if the design is wrong, take it back to EGM and re-import. Never widen a boundary into a file another branch of
  the same wave owns.
- When a chain ends `awaiting_owner`, run `python egm_plan.py boundary plan.json <slug>` before telling the owner its PR
  is ready. Files outside the boundary (exit 1) are a finding for the owner; tests outside the list are expected.
- A wave whose branches depend on earlier ones starts once those PRs merged: `make_briefs.py plan.json --wave <n>` then.

## 7. After merges: drift

After each merge batch, and at the run's close, `/egm:egm-drift-report docs/designs/<feature>.md` compares the design
with the merged code. Each divergence is the owner's call: update the document (EGM) or the code (a new plan round).
Then re-verify as usual.

## Without EGM

`init_run.py fix <run> PLANNER=grill` plans by grilling rounds on the plan page, as before EGM: for a run that is all
defects with no design to settle, or a machine without the EGM plugin (`doctor.py` says so, and that it's the owner's
call). Planning still always happens, and is signed off.
