"""Write a chain's live page (or the verify run's) into <run>/live/<slug>.live.html. The page lives in the run folder,
outside the repo, and is never committed (the repo ignores *.live.html). It draws itself from its own database, which
live_sync.py fills, so it is published once and stays current without a republish.

  python live_page.py <slug> [<slug> ...]       one page per chain of a fix run (publish a wave's pages before it starts)
  python live_page.py verify                    the verify run's page (from the verify run folder)
  python live_page.py --url <slug> <url>        record where a page was published (live/urls.json): live_sync.py writes to
                                                it and the main window's lines link to it

Publish each page with the Artifact tool: file_path <run>/live/<slug>.live.html, the capabilities this prints, icon
"pulse"; then --url with the URL the publish returns. Every chain's conversation with the owner happens on its page: the
main window only posts the link when the page needs the owner.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
LIVE = os.path.join(HERE, "live")
# Owner-only writes: the chain's state, lines, questions, review items and Claude's answers come from the owner's session
# (ArtifactData), and the answers and approvals are the owner's decisions, relayed to the chains as such. Anyone the page
# is shared with can read it and Ask Claude.
CAPS = {"db": {"rules": [{"path": p, "read": "view", "write": "owner"}
                         for p in ("state", "events", "asks", "reviews", "replies", "answers", "approvals")]},
        "comments": {}, "user": {}}


def title_of(slug):
    if slug == "verify" and CONF.get("KIND") == "verify":
        name = CONF.get("RUN_NAME", "verify")
        return " ".join(w.capitalize() for w in re.split(r"[-_]+", name) if w) + " Verify Loop"
    for p in (os.path.join(CONF.get("WT_ROOT", ""), slug, ".fixloop", "brief.md"), os.path.join(HERE, "briefs", f"{slug}.md")):
        try:
            m = re.search(r"^Title: (.+)$", open(p, encoding="utf8").read(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).strip()
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w)


def render(slug):
    title = title_of(slug)
    config = {"slug": slug, "title": title, "kind": "verify" if slug == "verify" and CONF.get("KIND") == "verify" else "chain",
              "run": CONF.get("RUN_NAME", ""), "owner": CONF.get("OWNER", "the owner"),
              "syncMin": int(CONF.get("LIVE_SYNC_MIN", "10") or 0)}
    html = open(os.path.join(HERE, "live_page.html"), encoding="utf8").read()
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (html.replace("__TITLE__", esc(title))
                .replace("/*__TWO_WAY__*/", open(os.path.join(HERE, "two_way.js"), encoding="utf8").read())
                .replace("__CONFIG__", json.dumps(config).replace("</", "<\\/")))
    out = os.path.join(LIVE, f"{slug}.live.html")
    open(out, "w", encoding="utf8", newline="\n").write(html)
    return out


def main(a):
    if not a:
        print(__doc__); sys.exit(2)
    sys.stdout.reconfigure(encoding="utf-8")   # redirected on Windows, stdout is cp1252
    os.makedirs(LIVE, exist_ok=True)
    if a[0] == "--url":
        if len(a) < 3:
            print(__doc__); sys.exit(2)
        path = os.path.join(LIVE, "urls.json")
        try:
            known = json.load(open(path, encoding="utf8"))
        except (OSError, ValueError):
            known = {}
        known[a[1]] = a[2]
        json.dump(known, open(path, "w", encoding="utf8"), indent=1)
        print(f"{a[1]}: {a[2]} (then live_sync.py {a[1]} for its first writes)")
        return
    for slug in a:
        print(f"{slug}: {render(slug)}")
    print("publish each with these capabilities, icon \"pulse\", then live_page.py --url <slug> <url>:")
    print(json.dumps(CAPS))


if __name__ == "__main__":
    main(sys.argv[1:])
