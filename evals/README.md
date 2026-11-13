# Evals

Behaviour checks for the skill: given a request phrased the way a person would type it, does Claude pick up MetaLoop
and do what SKILL.md says? Each case is a folder with a `prompt.md` (the request) and `graders/` (what a good answer
must do), run with Claude Code's `claude plugin eval`.

| Case | Checks that the skill |
|---|---|
| `offers-loop-for-wide-work` | loads for wide, overnight work and offers the loop: phases, owner gates, the set-up questions in one batch with recommendations, nothing started unasked |
| `small-fix-stays-normal` | stays out of the way for a one-line fix |
| `plans-with-egm-first` | plans with EGM (design, Goldfish review, approval), then the fan-out check and the owner's sign-off, before any brief or chain |
| `refuses-colliding-split` | won't sign off or start a wave where two branches own the same file, and fixes the split |
| `bare-done-is-not-signoff` | doesn't take a bare "done" on design pages as a sign-off |
| `owner-merges` | leaves merging to the owner and says what it does after |
| `sets-up-the-stack-it-sees` | sets a Node + Postgres repo up with the matching presets (`init_project.py --stack node --db postgres`) |
| `chain-question-stays-on-its-page` | sends a chain's question to the owner as one line with its live page link, not pasted into the chat |

## Run them

From the repository root (the plugin; the skill is `metaloop:metaloop`):

```bash
claude plugin eval . --judge-model sonnet
```

Every case runs 3 times with the skill and 3 times without it (the baseline), so the report shows how much the skill
changes the answer (Δ), not only whether it passes. A full run is 48 agent runs plus judge calls; a quick pass:

```bash
claude plugin eval . --runs 1 -j 4 --judge-model sonnet --max-cost-usd 10
```

One case, or a tag:

```bash
claude plugin eval . --case owner-merges --runs 1
```

```bash
claude plugin eval . --tag gates
```

The report (`evals/results/<time>/report.html`, ignored by git) has each run's answer and every grader's verdict.
Exit code 0 means every case scored 1.0 with the skill.

## Reading the results

- `skill-fired` is reported as an indicator, not scored, in a run with a baseline: it says whether Claude loaded the
  skill from its description. A case that fails because the skill never loaded points at SKILL.md's `description`.
- A case that loads the skill and still fails points at the part of SKILL.md (or the reference it names) that should
  have steered that answer.
- `llm` graders are judged by a model voting three times on the rubric in the grader's file; `regex` graders are
  exact. Use `--judge-model sonnet`: the default judge (Haiku) misread correct multi-step answers in this suite, for
  example taking read-only checks of the defects for fixes starting early, and failed runs that were right.
- Keep each `llm` grader to one question. A long rubric with several conditions is judged less reliably than two or
  three short graders, with the order or exact wording checked by a `regex` grader where it can be.

## Adding a case

`claude plugin eval init --bare <name>` writes a blank `prompt.md` and `graders/criteria.md`. Phrase the prompt the way
a person would type it (don't name the skill), give the context it needs in the prompt itself, and write graders as
PASS / FAIL conditions. Cases here allow only read-only tools (`Read`, `Glob`, `Grep`, `Skill`), so a run can't change
anything.
