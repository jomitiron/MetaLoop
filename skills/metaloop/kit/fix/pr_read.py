"""Read-only view of a PR for chain sessions. Chains may not call `gh api`, because any `gh api` allow can write (a method
or field flag after the path turns a read into a POST, PUT or merge). Every call here is a GET.

  python pr_read.py <PR> comments     inline review comments: id, author, path:line, body
  python pr_read.py <PR> reviews      review bodies (bot summaries posted as reviews)
  python pr_read.py <PR> issue        top-level PR comments (bot summaries posted as comments)
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))["GH_REPO"]
PATHS = {"comments": "pulls/{n}/comments", "reviews": "pulls/{n}/reviews", "issue": "issues/{n}/comments"}


def pages(text):
    """`gh api --paginate` prints one JSON array per page back to back; join them (a body may itself contain '][')."""
    dec, out, i = json.JSONDecoder(), [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1; continue
        page, i = dec.raw_decode(text, i)
        out += page
    return out


def main(a):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # bot comments carry emoji a cp1252 console can't print
    if len(a) != 2 or a[1] not in PATHS or not a[0].isdigit():
        print(__doc__); sys.exit(2)
    r = subprocess.run(["gh", "api", "--method", "GET", "--paginate", f"repos/{REPO}/{PATHS[a[1]].format(n=a[0])}"],
                       capture_output=True, text=True, encoding="utf8")
    if r.returncode:
        sys.exit(r.stderr.strip())
    items = pages(r.stdout)
    for c in items:
        where = f" {c.get('path')}:{c.get('line') or c.get('original_line')}" if c.get("path") else ""
        state = f" {c['state']}" if c.get("state") else ""
        print(f"#{c['id']} {c['user']['login']}{state}{where}")
        body = (c.get("body") or "").strip()
        print("    " + body.replace("\n", "\n    ")[:4000] if body else "    (no body)")


if __name__ == "__main__":
    main(sys.argv[1:])
