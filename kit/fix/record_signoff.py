"""Record the owner's design sign-off on each design branch: the README row(s) say SIGNED OFF with the chosen options,
the branch gets a "SIGNED OFF ..." note (the runbook's trigger to build) and goes back to todo. Commits and pushes.

  python record_signoff.py <signoffs.json> <queue-out.txt> <YYYY-MM-DD> [--dry-run]

--dry-run prints each README row as it would read and changes nothing (no file, commit, push or note).

signoffs.json: {"<slug>": "M1-A, M2-C (why), M3-A; Q1: <how the open question was settled>"}
Only ever run this on an explicit sign-off. A bare "done" or "looks good" with no comments on the pages is not one: ask.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
signoffs = json.load(open(sys.argv[1], encoding="utf8"))
date = sys.argv[3]
dry = "--dry-run" in sys.argv
owner = CONF.get("OWNER", "the owner")
queue = []


def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf8")


for slug, choices in signoffs.items():
    wt = os.path.join(CONF["WT_ROOT"], slug)
    branch = f"{CONF['BRANCH_PREFIX']}{CONF.get('SLUG_PREFIX', '')}{slug}"
    changed = []
    for readme, kind in ((f"{CONF.get('MOCKUPS_DIR', 'docs/mockups')}/README.md", "ux"),
                         (f"{CONF.get('SCHEMA_DIR', 'docs/schema-changes')}/README.md", "schema")):
        p = os.path.join(wt, readme)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in s else "\n"
        lines = s.split(nl)
        own_row = re.compile(r"\[[^\]]*" + re.escape(slug) + r"\.(html|md)\]")  # the row whose page link is this branch's
        for i, ln in enumerate(lines):
            if not own_row.search(ln):
                continue
            if kind == "ux":
                new = re.sub(r"\*\*PROPOSED: awaiting sign-off \([^)]*\)\.?\*\*",
                             f"**SIGNED OFF, {owner}, {date}: {choices}. Building** on `{branch}`.", ln, count=1)
            else:
                new = re.sub(r"\*\*Proposed\*\*|\| Proposed \|",
                             lambda m: (f"**Signed off, {owner}, {date} ({choices})**" if m.group(0).startswith("**")
                                        else f"| Signed off, {owner}, {date} ({choices}) |"), ln, count=1)
            if new != ln:
                lines[i] = new
                changed.append(readme)
                if dry:
                    print(f"{slug} {readme}: {new[:300]}")
        if readme in changed and not dry:
            open(p, "w", encoding="utf-8", newline="").write(nl.join(lines))
    if not changed:
        print(f"{slug}: NO README ROW CHANGED: check the row by hand"); continue
    if dry:
        continue
    sh(["git", "add", *sorted(set(changed))], wt)
    c = sh(["git", "commit", "-q", "-m", f"docs: {slug} design signed off by {owner} ({date})\n\n"
            "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"], wt)
    p = sh(["git", "push", "-q", "origin", branch], wt) if c.returncode == 0 else None
    if c.returncode != 0 or p.returncode != 0:
        # The sign-off must be on the branch before the chain builds from it: nothing is noted or queued.
        err = (c.stderr if c.returncode != 0 else p.stderr).strip()[:300]
        print(f"{slug}: NOT QUEUED: {'commit' if c.returncode != 0 else 'push'} failed: {err}"); continue
    note = (f"SIGNED OFF ({owner}, {date}): {choices}. Mode is now BUILD: build exactly the signed-off page(s) on this branch, "
            "following the runbook section 'When the owner has signed off the design'.")
    sh([sys.executable, os.path.join(HERE, "task.py"), "note", note], wt)
    sh([sys.executable, os.path.join(HERE, "task.py"), "requeue", "build the signed-off design"], wt)
    queue.append(slug)
    print(f"{slug}: {', '.join(sorted(set(changed)))} committed, pushed, queued")
if dry:
    print("dry run: nothing written")
else:
    open(os.path.join(HERE, sys.argv[2]), "w", encoding="utf8").write("\n".join(queue) + ("\n" if queue else ""))
    print(f"queued {len(queue)} in {sys.argv[2]}")
