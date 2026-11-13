# The project profile

MetaLoop assumes no language, framework or database. Everything stack-specific about the repository a run works on is
in one file that repository commits: `.metaloop/project.json`. It says how the project builds and tests (the gate), which
background services those checks need, how the app under test is served (the verify loop), which tools the machine needs,
and which extra commands sessions may run. `init_run.py` copies it into every run folder; `doctor.py` checks it and every
tool it names; `gate.py`, `qa-loop.sh` and `services.py` run what it says.

## Start from the presets

```bash
python3 skills/metaloop/kit/init_project.py --list
```

```bash
python3 skills/metaloop/kit/init_project.py --stack node --db postgres --db redis
```

| Stacks | |
|---|---|
| `node` | npm; Jest (or Vitest); `npm start` on `PORT` |
| `python` | a `.venv`, pip, pytest; you name the serve command (Django, FastAPI, Flask, ...) |
| `ruby` | Bundler, RSpec, `bin/rails server`, `/up` health |
| `go` | `go build`, `go vet`, `go test -v` |
| `rust` | `cargo build`, `clippy`, `cargo test` |
| `java-maven` | `./mvnw` or `mvn verify`, Surefire totals, Spring Boot's `/actuator/health` |
| `java-gradle` | `./gradlew build` and `test` (exit codes; Gradle prints no totals) |
| `dotnet` | `dotnet build` and `dotnet test`, a fixed locale |
| `php` | Composer, PHPUnit, `php -S` |
| `custom` | every command left to fill in |

| Services | Docker (`--via docker`, the default) | Native (`--via native`) | Exports |
|---|---|---|---|
| `postgres` | `postgres:16` | `initdb` + `postgres`, trust auth, no Unix socket | `DATABASE_URL` |
| `mysql` | `mysql:8.4` | `mysqld --initialize-insecure` | `DATABASE_URL` |
| `mongodb` | `mongo:7`, a single-node replica set | `mongod --replSet`, initiated | `MONGO_URL` |
| `redis` | `redis:7` | `redis-server`, no persistence | `REDIS_URL` |
| `sqlite` | no server: a fresh file per slot | | `DATABASE_URL`, `SQLITE_PATH` |

The composer attaches the services to the stack's test step and to the verify loop, gives the verify loop its own ports
and a data folder kept between runs, and leaves `FILL IN` wherever it can't know the answer (how the app is served, how
its test data is loaded). `doctor.py` blocks a run while any `FILL IN` is left. Check the commands against how the
repository really builds and tests, then commit the file. Anything the presets don't cover is a few lines of JSON.

## Fields

```json
{
 "requires": [{"tool": "node", "check": "command -v node", "for": "builds and tests",
               "install": "brew install node", "who": "owner"}],
 "env": {"LC_ALL": "en_US.UTF-8"},
 "gate": {"steps": [
  {"name": "build", "run": "npm ci && npm run build"},
  {"name": "test", "run": "npm test", "tests": "jest", "slots": 3, "services": ["postgres"]},
  {"name": "e2e", "run": "npm run test:e2e", "tests": "jest", "slots": 1, "services": ["postgres", "redis"],
   "skippable": "CI's e2e job must pass before the PR is ready",
   "hints": [{"match": "ECONNREFUSED", "say": "the e2e suite couldn't reach a service"}]}
 ]},
 "services": {"postgres": {"port": 55432, "start": "...", "ready": "...", "stop": "...",
                           "env": {"DATABASE_URL": "postgres://...:{port}/app"}}},
 "verify": {"url": "http://localhost:3000", "health": "/healthz", "build": "npm ci && npm run build",
            "start": "PORT={app_port} npm start", "env": {"NODE_ENV": "test"}, "timeout": 180,
            "services": {"postgres": {"port": 55532, "persist": "~/.metaloop/app/postgres", "reuse": true,
                                      "seed": "npm run db:seed"}},
            "provides": ["webhooks"]},
 "chain_allow": ["npm test *", "npm run *"],
 "verify_allow": ["psql *"],
 "caps": {"payments": "start the payment provider's CLI listener as a verify service, then requeue the test"},
 "docs": {"mockups": "docs/mockups", "schema": "docs/schema-changes"}
}
```

| Field | What |
|---|---|
| `requires` | Tools the checks need. `check` is a command that exits 0 when the tool is usable (default: the tool is on `PATH`). `who` is `claude` (the orchestrator may install it once the owner says yes) or `owner` (a password, a licence, a sign-in). `skip` names gate steps the owner may leave out instead (`GATE_SKIP`). A service's own `requires` count when a step or the verify loop uses it. |
| `env` | Exported to every gate step and to the verify build and server. |
| `gate.steps` | Run in order from the branch's worktree. See "The gate". |
| `services` | See "Services". |
| `verify` | `url` where the app answers (APP_URL); `health` a path that answers 2xx or 3xx once it is up; `build` and `start` run in the verify worktree with `env` and the services' env; `timeout` seconds to wait for health; `services` a list of names, or names with verify-only overrides; `provides` capabilities this stack gives tests with a `Requires:` line. |
| `chain_allow`, `verify_allow` | Extra commands fix-chain and verify sessions may run (`"npm test *"` becomes `Bash(npm test *)`). Everything else stays denied. |
| `caps` | For each capability a test may require, how the owner makes it available: the ask a blocked test carries. |
| `docs` | Where design chains put mockups and schema-change pages (each folder has a README registry). |

In any command or env value, `{port}` `{slot}` `{dir}` `{id}` `{run}` `{root}` `{app_url}` `{app_port}` are filled in;
nothing else in braces is touched, so shell, JSON and JavaScript in commands are safe. Commands run under bash (Git Bash
on Windows).

## The gate

Each step's `run` is a shell command. A step without `tests` passes on exit code 0; when it fails, the gate stops there
unless the step says `"continue": true`. A step with `tests` is judged by its output:

| `tests` | Reads |
|---|---|
| `dotnet` | `Passed!/Failed! - Failed: n, Passed: n` per test project |
| `pytest` | the `n failed, n passed in 1.2s` line (errors count as failures); `FAILED`/`ERROR` lines for names |
| `jest` | `Tests: n failed, n passed, n total`; `●` lines for names |
| `vitest` | `Tests  n failed \| n passed (n)`; `FAIL` lines for names |
| `go` | counts `--- PASS:` and `--- FAIL:` lines (`go test -v`) |
| `cargo` | every `test result:` line; `test x ... FAILED` for names |
| `rspec` | `n examples, n failures, n pending`; `rspec ./spec/...` for names |
| `maven` | the `Tests run:` total lines (not per class); passed = run - failures - errors - skipped |
| `phpunit` | `OK (n tests` or `Tests: n, ..., Failures: n` |
| an object | your own: `line` (a summary line; every match counts), `passed`, `failed`, `total`, `skipped` (numbers in it, summed), or `count_passed` / `count_failed` (lines to count), and `name` (a failing test's name, group 1) |

A parsed step fails when no summary line is found, when zero tests ran, when it exits non-zero with no failing test (a
crash before the tests), or when more tests failed than `KNOWN_FLAKES` names matched. `KNOWN_PLATFORM_FAILURES` are
reported and not counted. `slots` caps how many chains run the step at once; a step that uses services gets 1 unless it
says, and each slot has its own service instances. `GATE_SKIP=<step>` (the owner's decision only) leaves a step out; the
verdict and the PR body name it with its `skippable` note. `hints` print a line when a failed step's log matches.

## Services

| Field | What |
|---|---|
| `port` | The base port; a gate slot adds its number. A port already in use is an error, never shared. |
| `start` | Left running in the background (its output in `logs/service-<name>.log`). Exiting non-zero fails at once with the log's tail; exiting 0 (a daemon that backgrounds itself) is waited on. |
| `up`, `init`, `ready` | Checks and one-off set-up: wait for `up` (default `ready`), run `init` once, wait for `ready`. Each is a command that exits 0 when true. |
| `stop` | Run on the way out (e.g. `docker rm -f`); whatever `start` left running is then ended. |
| `env` | What the step or the app reads to reach it. |
| `timeout` | Seconds to come up (default 60). |
| `persist`, `seed`, `reuse` | Verify-loop overrides: keep `{dir}` between runs, run `seed` once when it is new, use an instance that already answers `ready`. |
| `requires` | The tools it needs (Docker, or the native server). |

`{dir}` is a fresh folder per instance, removed after (or the `persist` folder). `{id}` is unique per instance, so
container names never collide. To add a service the presets don't have (a message queue, an object store, a provider's
webhook listener), give it a `start`, a `ready` check and the `env` the app reads.
