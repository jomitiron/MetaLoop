"""Record the owner's review-item approvals on each branch and queue the chains that have items to apply.

  python approve.py <approvals.json> <queue-out.txt> "<how the owner approved, e.g. 'Approve all as recommended', 11 Oct>"

approvals.json: {"<slug>": {"apply": "1, 2, 4", "note": "Item 3: no change. Item 4 wording approved: '...'"}}
A slug with an empty "apply" gets the note only (reply-only PRs: the main session answers their threads itself).
Each applying branch gets an "APPROVED REVIEW ITEMS ..." note (the runbook's trigger) and goes back to todo.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
approvals = json.load(open(sys.argv[1], encoding="utf8"))
how = sys.argv[3]
queue = []
for slug, v in approvals.items():
    wt = os.path.join(CONF["WT_ROOT"], slug)
    items = v.get("apply", "").strip()
    extra = v.get("note", "").strip()
    if items:
        note = f"APPROVED REVIEW ITEMS {items} ({CONF.get('OWNER')}, {how}): apply exactly these, as their recorded proposals describe. {extra}".strip()
        cmds = [["note", note], ["requeue", f"apply approved review items {items}"]]
        queue.append(slug)
    else:
        cmds = [["note", f"REVIEW ITEMS DECIDED ({CONF.get('OWNER')}, {how}): nothing to apply. {extra}".strip()]]
    for c in cmds:
        r = subprocess.run([sys.executable, os.path.join(HERE, "task.py"), *c], cwd=wt, capture_output=True, text=True)
        if r.returncode:
            print(slug, "FAILED", c[0], r.stderr[-200:])
    print(f"{slug}: {'apply ' + items if items else 'reply only'}")
open(os.path.join(HERE, sys.argv[2]), "w", encoding="utf8").write("\n".join(queue) + ("\n" if queue else ""))
print(f"queued {len(queue)} in {sys.argv[2]}")
