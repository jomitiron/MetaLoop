"""One line per branch in a queue (or every worktree under WT_ROOT): status, phase, PR, last note.

  python status.py [queue-file]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
root = CONF["WT_ROOT"]
if len(sys.argv) > 1:
    slugs = [l.strip() for l in open(os.path.join(HERE, sys.argv[1]), encoding="utf8") if l.strip() and not l.startswith("#")]
else:
    slugs = sorted(d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, ".fixloop", "status.json")))
for s in slugs:
    p = os.path.join(root, s, ".fixloop", "status.json")
    if not os.path.exists(p):
        print(f"{s:34} not started"); continue
    d = json.load(open(p, encoding="utf8"))
    pr = f"#{d['pr']['number']}" if d.get("pr") else "-"
    last = (d["notes"][-1] if d["notes"] else "")[20:140]
    print(f"{s:34} {d['status']:15} {str(d.get('phase')):9} {pr:6} reviews={len(d['reviews']):<2} {last}")
