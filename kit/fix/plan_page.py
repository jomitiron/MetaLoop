"""Render plan.json as the plan page: where the owner answers each grilling round, reads the plan it becomes (branches by
wave, each broken into tasks with the test that proves it), and signs it off. Published as an Artifact with the
capabilities this prints; re-render and republish to the same URL whenever plan.json changes (a new round, a decision
recorded, the branches drawn up). The owner's answers and sign-off live in the page's database, so they survive it.

  python plan_page.py plan.json <out.html> "<Title, 2-4 words>"

plan.json: decisions carry "round" (1, 2, ...; the open round is the lowest with an undecided decision) and "decided"
once the owner's answer is recorded; branches carry "title" and "tasks" [{"id", "text", "test"}]. Read the answers with
ArtifactData (collection "answers", ids d<n>), record each as the decision's "decided", and on the page's sign-off
(collection "signoff", doc "plan") run sign_plan.py.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Owner-only writes: Claude's answers, and the owner's own answers and sign-off (the plan's decisions are the owner's).
CAPS = {"db": {"rules": [{"path": p, "read": "view", "write": "owner"} for p in ("replies", "answers", "signoff")]},
        "comments": {}, "user": {}}


def main(a):
    if len(a) < 3:
        print(__doc__); sys.exit(2)
    plan = json.load(open(a[0], encoding="utf8"))
    title = a[2]
    html = open(os.path.join(HERE, "plan_page.html"), encoding="utf8").read()
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (html.replace("__TITLE__", esc(title))
                .replace("/*__TWO_WAY__*/", open(os.path.join(HERE, "two_way.js"), encoding="utf8").read())
                .replace("__PLAN__", json.dumps(dict(plan, page_title=title), ensure_ascii=False).replace("</", "<\\/")))
    open(a[1], "w", encoding="utf8", newline="\n").write(html)
    dec = plan.get("decisions", [])
    open_n = sum(1 for d in dec if not d.get("decided"))
    rounds = sorted({d.get("round", 1) for d in dec if not d.get("decided")})
    print(f"written: {len(dec)} decisions ({open_n} open{', round ' + str(rounds[0]) if rounds else ''}), "
          f"{len(plan.get('branches', []))} branches")
    print("publish with these capabilities (icon \"plan\" on the first publish):")
    print(json.dumps(CAPS))


if __name__ == "__main__":
    main(sys.argv[1:])
