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

The full procedure is in [reference/egm.md](skills/metaloop/reference/egm.md). `PLANNER=grill` plans the original way, with grilling
rounds on the plan page.

## Layout

This repository is a Claude Code plugin and the marketplace that lists it.

| Path | What |
|---|---|
| [.claude-plugin/](.claude-plugin/) | `plugin.json` (the plugin) and `marketplace.json` (the catalog Claude Code installs it from). |
| [skills/metaloop/SKILL.md](skills/metaloop/SKILL.md) | The skill: when to offer a loop, the roles, the non-negotiables, the lifecycle. |
| [skills/metaloop/reference/](skills/metaloop/reference/) | The orchestrator's procedures, the project profile, the fix and verify loops, the EGM hand-off, and pitfalls met in practice. |
| [skills/metaloop/kit/](skills/metaloop/kit/) | The scripts `init_run.py` copies into a run folder (see [its README](skills/metaloop/kit/README.md)). |
| [skills/metaloop/kit/presets/](skills/metaloop/kit/presets/) | Ready-made project profiles: stacks, and the databases and services their checks need. |
| [evals/](evals/) | Behaviour evals for the skill (`claude plugin eval .`). |
| [.github/workflows/check.yml](.github/workflows/check.yml) | Validates the plugin and runs the kit's self-test on every pull request. |

## Install

MetaLoop installs as a Claude Code plugin, once per machine, and works in any repository:

```bash
claude plugin install metaloop --marketplace jomitiron/MetaLoop
```

That adds this repository as the `metaloop` marketplace and installs `metaloop@metaloop`. Start a new session: Claude
picks the skill up when the work fits (or run `/metaloop:metaloop`).

For planning with EGM, install Google's plugin too:

```bash
claude plugin install egm --marketplace google/elephant-goldfish-model
```

### Keep it up to date

Turn on auto-update once: in Claude Code, `/plugin` → **Marketplaces** → `metaloop` → **Enable auto-update**. Claude
Code then checks in the background during a session and installs a newer MetaLoop, which loads at the next start (or
after `/reload-plugins`). Auto-update is off by default for marketplaces outside Anthropic's own. Without it, update by
hand:

```bash
claude plugin update metaloop@metaloop
```

A run already under way keeps the copy of the kit it was made with; running `init_run.py` on it again brings in the new
kit and keeps the run's settings and any runbook or settings you edited (the new render goes beside them as `.new`).

### Set up a team's repository

To give everyone who works in a repository MetaLoop and EGM, with MetaLoop updating itself, commit this to the
repository's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "metaloop": {
      "source": { "source": "github", "repo": "jomitiron/MetaLoop" },
      "autoUpdate": true
    },
    "egm": {
      "source": { "source": "github", "repo": "google/elephant-goldfish-model" }
    }
  },
  "enabledPlugins": {
    "metaloop@metaloop": true,
    "egm@egm": true
  }
}
```

Claude Code registers both marketplaces for each person once they trust the folder. Enabling a plugin there doesn't
install it, so each person runs these once in the repository:

```bash
claude plugin install metaloop@metaloop --scope project
```

```bash
claude plugin install egm@egm --scope project
```

### Use it in a project

Describe the project once, from the presets, and commit the file it writes, `.metaloop/project.json`. Ask Claude to set
MetaLoop up for the repository and it runs this from the installed kit (`--list` shows every preset):

```bash
python3 <kit>/init_project.py --stack node --db postgres
```

Then it starts a run (`init_run.py fix|verify <run folder> OWNER=<you>`) and has the run's `doctor.py` say what else
the machine needs. `<kit>` is the kit folder inside the installed plugin; Claude knows its path.

## Releasing changes

Every commit on `main` is a release. `plugin.json` has no `version`, so Claude Code versions MetaLoop by commit: people
with auto-update on get a merged change at their next session, and everyone else on `claude plugin update`.

- Merge only what is ready. [check.yml](.github/workflows/check.yml) validates the plugin and runs the kit's self-test
  on every pull request. Run the [evals](#evals) before merging a change to `SKILL.md` or the references.
- Try a change before it ships: from a clone, `claude --plugin-dir .` loads the working copy for that session instead
  of the installed plugin.
- To hold users on numbered releases instead, add `"version": "1.0.0"` to `.claude-plugin/plugin.json` and raise it for
  each release (`claude plugin tag --push` tags it). Users then get nothing new until the version changes.

## Stacks and services

| Stacks | Databases and services (Docker or native) |
|---|---|
| Node (Jest or Vitest), Python (pytest), Ruby on Rails (RSpec), Go, Rust (Cargo), Java (Maven or Gradle), .NET, PHP (PHPUnit), or `custom` | PostgreSQL, MySQL, MongoDB (a replica set), Redis, SQLite |

A preset fills in the gate's steps with the right test-output parser, the services those steps need (a fresh instance
per gate slot, on its own port, removed after), how the verify loop builds, starts and health-checks the app (its own
services, data kept between runs and seeded once), the tools the machine needs, and the commands sessions may run.
Whatever it can't know, such as how this particular app starts, it marks `FILL IN`, and the run won't start until each
is filled in. Anything the presets don't cover is a few lines of JSON: any command, any test runner (give it a summary
pattern), any service with a start command and a ready check. [reference/project.md](skills/metaloop/reference/project.md) has every
field.

MetaLoop also uses companion skills where the repository or the user has them (`grilling` and `domain-modeling`, for
`PLANNER=grill`) and follows the repository's own instructions (CLAUDE.md, AGENTS.md) in every session.

## Evals

[evals/](evals/) checks the skill steers Claude as intended: eight cases, from offering a loop only for wide work, to
planning with EGM before any chain starts, to leaving merges and sign-offs to the owner. Each runs with and without the
skill, so the report shows the difference it makes.

```bash
claude plugin eval . --judge-model sonnet
```

## Self-test

From a clone of this repository:

```bash
bash skills/metaloop/kit/selftest.sh
```

It renders a fix run and a verify run in a temp folder from a test profile and runs the scripts against stand-ins (a
stub toolchain, a stub service), every test-output parser against sample output, and every stack preset; where
PostgreSQL or MongoDB is installed it starts the native presets for real. Nothing outside the temp folder is touched.
