# MetaLoop

A Claude Code skill for running large engineering work as loops of fresh, headless sessions: spec engineering up
front, parallel execution in isolated worktrees, and every session kept well inside its context window, with the owner
deciding at fixed gates.

- **Spec first.** Nothing is built before a plan the owner signed off: every branch broken into tasks, each with the
  test that proves it.
- **Parallel.** Each branch is its own chain of `claude -p` sessions in its own git worktree, five at a time by default,
  each with a live page where the owner sees its progress and answers its questions.
- **Context-efficient.** A guard hook hands a session off at 65% of its window and stops it at 72%; sessions hand over
  through files, never memory, so every session starts sharp.
- **Any stack.** Nothing in MetaLoop knows a language, framework or database. A project describes itself in one file,
  `.metaloop/project.json`: how it builds and tests, which services its checks need, how its app is served.

## EGM plans, MetaLoop fans out

Planning uses Google's [Elephant-Goldfish Model](https://github.com/google/elephant-goldfish-model) (EGM). The main
session is EGM's **Elephant**: it designs the work with the owner. EGM's **Goldfish**, fresh subagents with none of the
conversation, review the design. MetaLoop then splits the approved design into branches, has the Goldfish review that
split, and orchestrates the chains that build it.

```text
EGM          /egm:egm-brainstorm -> /egm:egm-draft -> /egm:egm-review + /egm:egm-resolve -> owner approves, design merged
hand-off     egm_plan.py import -> branches drawn up -> egm_plan.py check -> fan-out Goldfish review -> owner signs off
MetaLoop     make_briefs.py -> parallel chains (red, green, docs, gate, security, PR, CI) -> review items -> owner merges
after merge  /egm:egm-drift-report -> the owner updates the doc or the code -> re-verify
```

The full procedure is in [reference/egm.md](reference/egm.md). `PLANNER=grill` plans the original way, with grilling
rounds on the plan page.

## Layout

| Path | What |
|---|---|
| [SKILL.md](SKILL.md) | The skill: when to offer a loop, the roles, the non-negotiables, the lifecycle. |
| [reference/](reference/) | The orchestrator's procedures, the project profile, the fix and verify loops, the EGM hand-off, and pitfalls met in practice. |
| [kit/](kit/) | The scripts `init_run.py` copies into a run folder (see [kit/README.md](kit/README.md)). |
| [kit/presets/](kit/presets/) | Ready-made project profiles: stacks, and the databases and services their checks need. |

## Install

MetaLoop runs from inside the repository it works on, at `skills/metaloop`:

```bash
git clone https://github.com/jomitiron/MetaLoop.git skills/metaloop
```

For planning with EGM, install its plugin in Claude Code and start a new session:

```bash
claude plugin marketplace add google/elephant-goldfish-model
```

```bash
claude plugin install egm@egm
```

Describe the project once, from the presets, and commit the file it writes (`--list` shows them all):

```bash
python3 skills/metaloop/kit/init_project.py --stack node --db postgres
```

Then start a run and let `doctor.py` say what else the machine needs:

```bash
python3 skills/metaloop/kit/init_run.py fix ~/w/<name> OWNER=<you>
```

## Stacks and services

| Stacks | Databases and services (Docker or native) |
|---|---|
| Node (Jest or Vitest), Python (pytest), Ruby on Rails (RSpec), Go, Rust (Cargo), Java (Maven or Gradle), .NET, PHP (PHPUnit), or `custom` | PostgreSQL, MySQL, MongoDB (a replica set), Redis, SQLite |

A preset fills in the gate's steps with the right test-output parser, the services those steps need (a fresh instance
per gate slot, on its own port, removed after), how the verify loop builds, starts and health-checks the app (its own
services, data kept between runs and seeded once), the tools the machine needs, and the commands sessions may run.
Whatever it can't know, such as how this particular app starts, it marks `FILL IN`, and the run won't start until each
is filled in. Anything the presets don't cover is a few lines of JSON: any command, any test runner (give it a summary
pattern), any service with a start command and a ready check. [reference/project.md](reference/project.md) has every
field.

MetaLoop also points to companion skills a repository may have (`skills/grilling`, `skills/domain-modeling` for
`PLANNER=grill`) and follows the repository's own instructions (CLAUDE.md, AGENTS.md) in every session.

## Self-test

```bash
bash skills/metaloop/kit/selftest.sh
```

It renders a fix run and a verify run in a temp folder from a test profile and runs the scripts against stand-ins (a
stub toolchain, a stub service), every test-output parser against sample output, and every stack preset; where
PostgreSQL or MongoDB is installed it starts the native presets for real. Nothing outside the temp folder is touched.
