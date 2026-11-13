"""Record the owner's sign-off of the plan page in plan.json. make_briefs.py writes no brief before it.

  python sign_plan.py plan.json "<when, e.g. 2026-11-07 14:05>" "<who>"

Only on an explicit sign-off: the page's Sign off button (its signoff doc in the page's database) or the owner's own
words. Refuses while a decision is undecided or a branch has no tasks: planning means every question answered and every
branch broken into tasks, each with the test that proves it. A plan imported from an EGM design (egm_plan.py import)
must also pass egm_plan.py check: the approved design on the base, every design file owned, no file shared within a wave,
every journey delivered.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egm_plan  # noqa: E402


def main(a):
    if len(a) < 3:
        print(__doc__); sys.exit(2)
    path, when, who = a[0], a[1], a[2]
    plan = json.load(open(path, encoding="utf8"))
    problems = [f"decision {d.get('n')} ({d.get('title')}) is undecided" for d in plan.get("decisions", []) if not d.get("decided")]
    problems += [f"branch {b['slug']} has no tasks" for b in plan.get("branches", []) if not b.get("tasks")]
    problems += [f"branch {b['slug']} task {t.get('id')} has no test that proves it"
                 for b in plan.get("branches", []) if b.get("mode", "build") == "build" for t in b.get("tasks", []) if not t.get("test")]
    if plan.get("design"):
        c = egm_plan.conf()
        problems += egm_plan.check(plan, c.get("REPO", "."), c.get("BASE", "develop"))
    if problems:
        raise SystemExit("not signed off: " + "; ".join(problems))
    plan["signed_off"] = {"at": when, "by": who}
    json.dump(plan, open(path, "w", encoding="utf8"), indent=1, ensure_ascii=False)
    print(f"{path}: signed off {when} by {who}; next: make_briefs.py {path} --wave 1")


if __name__ == "__main__":
    main(sys.argv[1:])
