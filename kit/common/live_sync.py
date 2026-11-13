"""Keep each live page current from the run's state. Prints the writes for the ArtifactData tool; nothing reaches a page
until the main session writes them, and then marks them written with --done.

  python live_sync.py <slug> [<slug> ...]|verify|--all     the pending writes, as JSON {"pages": [{"slug", "url", "writes",
                                                 "attention"}]}. Write each page's "writes" with ArtifactData (action
                                                 batch, the page's url, at most 50 writes per call, in order)
  python live_sync.py <...> --done                 after every batch succeeded: mark those writes as written
  python live_sync.py --attention                  the main window's lines, one per thing a page needs the owner for, each
                                                   with its link: post these, and nothing else about a chain, in the chat

--all is every page recorded with live_page.py --url. Every write creates a new document (a new state, a new line, a new
question), so no write needs a version and none can race the owner's answers on the page. The page shows the newest state.
The writes are kept in live/<slug>.pending.json and offered again until --done.
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
LIVE = os.path.join(HERE, "live")
OWNER = CONF.get("OWNER", "the owner")
TS = r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)"
BUILD = [("red", "Failing test"), ("green", "Fix"), ("docs", "Docs"), ("gate", "Full test run"),
         ("security", "Security review"), ("pr", "Pull request"), ("ci", "CI and review")]
DESIGN = [("design", "Draft the page")]
READY = (None, "Ready for you")


def jload(path, default):
    try:
        return json.load(open(path, encoding="utf8"))
    except (OSError, ValueError):
        return default


def read(path):
    try:
        return open(path, encoding="utf8").read()
    except OSError:
        return ""


def urls():
    return jload(os.path.join(LIVE, "urls.json"), {})


def humanize(slug):
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w)


def plain(text):
    """A task.py note, as the owner reads it on the page."""
    m = re.match(r"\[(\w+)\]\s*(.*)", text, re.S)
    if m:
        name = dict(BUILD + DESIGN).get(m.group(1), m.group(1))
        return (m.group(2).strip() or f"Started: {name}"), ""
    for pre, say, tone in (("awaiting_owner: ", "Ready for you: ", "ok"), ("needs_owner: ", "Needs you: ", "warn"),
                           ("blocked: ", "Stopped: ", "warn"), ("requeued: ", "Back in the queue: ", "")):
        if text.startswith(pre):
            return say + text[len(pre):], tone
    m = re.match(r"asked (Q\d+): (.*)", text)
    if m:
        return f"Asked you {m.group(1)}: {m.group(2)}", "warn"
    m = re.match(r"OWNER ANSWER (\S+) \([^)]*\): (.*?)(\. If that isn't what you carried on with.*)?$", text, re.S)
    if m:
        return f"You answered {m.group(1)}: {m.group(2)}", "ok"
    m = re.match(r"SIGNED OFF (\([^)]*\)): (.*?)\. Mode is now BUILD", text, re.S)
    if m:
        return f"Design signed off {m.group(1)}: {m.group(2)}", "ok"
    m = re.match(r"APPROVED REVIEW ITEMS (.*?) (\([^)]*\))", text)
    if m:
        return f"Review items {m.group(1)} approved {m.group(2)}", "ok"
    if text.startswith("REVIEW ITEMS DECIDED"):
        return "Review comments decided: nothing to change", "ok"
    m = re.match(r"task (T\d+) done: (.*)", text)
    if m:
        return f"Task {m.group(1)} done" + (f": {m.group(2)}" if m.group(2) else ""), "ok"
    return text, ""


def chain(slug, recs=None):
    """The page's content for one chain: its state, its lines, its questions and its review items (each with a key)."""
    fl = os.path.join(CONF["WT_ROOT"], slug, ".fixloop")
    if not os.path.exists(os.path.join(fl, "status.json")) and os.path.exists(os.path.join(HERE, "retired", slug, "status.json")):
        fl = os.path.join(HERE, "retired", slug)   # merged: retire.sh removed the worktree and kept its state here
    brief = read(os.path.join(fl, "brief.md")) or read(os.path.join(HERE, "briefs", f"{slug}.md"))
    d = jload(os.path.join(fl, "status.json"), {"status": "todo", "phase": None, "pr": None, "notes": [], "reviews": []})
    notes, st = d.get("notes", []), d.get("status", "todo")
    design = re.search(r"^Mode: design\.", brief, re.M) and not any(" SIGNED OFF (" in n for n in notes)
    defs = (DESIGN if design else BUILD) + [READY]
    when = {}
    for n in notes:
        m = re.match(TS + r"\s+\[(\w+)\]", n)
        if m:
            when[m.group(2)] = m.group(1)
    phases = [p for p, _ in defs][:-1]   # READY has no phase: a chain with none yet hasn't started
    cur = (len(defs) if st == "done" else len(defs) - 1 if st == "awaiting_owner"
           else phases.index(d["phase"]) if d.get("phase") in phases else -1)
    steps = [{"name": name, "t": when.get(p, "") if p else "",
              "state": "done" if i < cur else ("held" if st in ("blocked", "needs_owner") else "now") if i == cur else "todo"}
             for i, (p, name) in enumerate(defs)]
    step = defs[cur][1] if 0 <= cur < len(defs) else ""
    asks = d.get("asks", [])
    waiting = [q for q in asks if q["status"] == "open"]
    summary = d.get("summary", "")
    holding = summary.startswith("holding the pull request")
    badge = {"todo": ("draft", "Back in the queue" if notes else "Queued"), "needs_owner": ("warn", "Needs you"),
             "awaiting_owner": ("warn", "Ready for you"), "blocked": ("draft", "Stopped"), "done": ("ok", "Done")}.get(st)
    if st == "in_progress":
        at = f" · {step}" if step else ""
        badge = ("warn", f"Needs you{at}") if waiting else ("info", f"Working{at}")
    badge = badge or ("draft", st)
    nxt = defs[cur + 1][1] if cur < len(defs) - 1 else ""
    quiet = {"todo": "Waiting for a free slot.", "blocked": f"Stopped: {summary}. The main session is looking at it.",
             "done": "Done.", "awaiting_owner": f"Ready for you: {summary}"}.get(st)
    if st == "in_progress" and not waiting:
        quiet = f"Nothing needs you. Next: {nxt}." if nxt else "Nothing needs you."
    done = set(d.get("tasks_done", []))
    tasks = [{"id": t, "text": x, "test": p, "done": t in done}
             for t, x, p in re.findall(r"^- (T\d+) · (.+?) · proved by: (.+)$", brief, re.M)]
    runs = [l.split("|") for l in read(os.path.join(fl, "state", "sessions.txt")).splitlines() if l.count("|") >= 3]
    cost = sum(float(r[2]) for r in runs if re.match(r"^\d+(\.\d+)?$", r[2] or ""))
    title = (re.search(r"^Title: (.+)$", brief, re.M) or [None, humanize(slug)])[1].strip()
    times = [m.group(1) for m in (re.match(TS, n) for n in notes) if m]
    answered = {q["id"]: q.get("answer", "") for q in asks if q["status"] == "answered"}
    cards = [dict(id=q["id"], kind="ask", title=q["title"], question=q["question"], options=q["options"],
                  recommend=q.get("recommend", "a"), at=q["at"]) for q in asks]
    for i, n in enumerate(notes):   # a stop with `needs` that isn't the hold for an open question: its summary is the ask
        m = re.match(TS + r"\s+needs_owner: (.*)", n, re.S)
        if m and not m.group(2).startswith("holding the pull request"):
            cards.append(dict(id=f"needs-{i}", kind="needs", title="The Chain Needs You", question=m.group(2), options=[],
                              recommend="", at=m.group(1)))
            if st != "needs_owner" or any(o.startswith(f"OWNER ANSWER needs-{i}") for o in (x[20:] for x in notes[i + 1:])):
                answered.setdefault(f"needs-{i}", "answered")
    items = []
    for k, r in enumerate(d.get("reviews", []), 1):
        rec = (recs or {}).get(str(k))
        if rec is None:
            continue   # each item goes up with the main session's recommendation, in plain words
        rec = rec if isinstance(rec, dict) else {"rec": rec}
        who, _, what = r["comment"].partition(":")
        items.append(dict(id=f"r{k}", n=k, who=re.sub(r"\s*#\d+$", "", who.strip()), what=rec.get("what") or what.strip(),
                          proposal=rec.get("proposal") or r.get("proposal", ""), rec=rec.get("rec", "Owner's call")))
    state = dict(title=title, kind="chain", branch=d.get("branch") or f"{CONF.get('BRANCH_PREFIX', '')}{CONF.get('SLUG_PREFIX', '')}{slug}",
                 pr=d.get("pr"), badge={"tone": badge[0], "text": badge[1]}, quiet=quiet, steps=steps, tasks=tasks,
                 counts=None, started=times[0] if times else "", at=times[-1] if times else "", sessions=len(runs),
                 cost=round(cost, 2), answered=answered, holding=holding)
    events = []
    for i, n in enumerate(notes):
        m = re.match(TS + r"\s+(.*)", n, re.S)
        events.append((f"n{i}", m.group(1) if m else "", *plain(m.group(2) if m else n)))
    lines = []
    for q in waiting:
        lines.append(f"Needs you · {slug}: {q['title']}")
    if st == "needs_owner" and not holding:
        lines.append(f"Needs you · {slug}: {summary}")
    if st == "awaiting_owner":
        lines.append(f"Ready · {slug}: {summary}")
    return state, events, cards, items, lines


def verify():
    d = jload(os.path.join(HERE, "ledger.json"), {"tests": []})
    tests = d.get("tests", [])
    c = {"pass": 0, "fail": 0, "blocked": 0, "running": 0, "todo": 0}
    for t in tests:
        k = {"in_progress": "running", "resumed": "todo", "awaiting_human": "running"}.get(t["status"], t["status"])
        c[k] = c.get(k, 0) + 1
    paused = os.path.exists(os.path.join(HERE, "PAUSED.md")) or any(t["status"] == "awaiting_human" for t in tests)
    now = next((t for t in tests if t["status"] in ("in_progress", "awaiting_human")), None)
    needs = [t for t in tests if t["status"] == "blocked" and t.get("needs_owner")]
    if paused:
        badge = ("warn", "Needs you · sign-in")
    elif not c["todo"] and not c["running"]:
        badge = ("ok", "Done")
    else:
        badge = ("warn" if needs else "info", f"Running · {now['id']}" if now else "Running")
    nxt = next((t["id"] for t in tests if t["status"] == "todo"), "")
    quiet = None if paused else ("Every test is recorded." if badge[1] == "Done" else f"Nothing needs you. Next: {nxt}." if nxt else "")
    times = sorted(x for t in tests for x in (t.get("started"), t.get("finished")) if x)
    state = dict(title=f"{humanize(CONF.get('RUN_NAME', 'verify'))} Verify Loop", kind="verify", branch=CONF.get("BASE", ""),
                 pr=None, badge={"tone": badge[0], "text": badge[1]}, quiet=quiet, steps=[], tasks=[], counts=c,
                 started=times[0] if times else "", at=times[-1] if times else "", sessions=len(d.get("sessions", [])),
                 cost=round(sum(float(s.get("cost") or 0) for s in d.get("sessions", []) if isinstance(s, dict)), 2),
                 answered={}, holding=False)
    said = {"pass": ("passed", "ok"), "fail": ("failed", "warn"), "blocked": ("set aside", "")}
    events = []
    for t in tests:
        if t.get("started"):
            events.append((f"{t['id']}@s{t['started']}", t["started"], f"Started {t['id']} · {t['title']}", ""))
        if t["status"] in said and t.get("finished"):
            word, tone = said[t["status"]]
            events.append((f"{t['id']}@{t['finished']}", t["finished"], f"{t['id']} {word}: {t.get('result') or ''}".rstrip(": "), tone))
    events.sort(key=lambda e: e[1])
    cards = [dict(id=f"{t['id']}@{t['finished']}", kind="needs", title=f"{t['id']} · {t['title']}", question=t["ask"],
                  options=[], recommend="", at=t["finished"]) for t in needs]
    if now and now["status"] == "awaiting_human":
        cards.append(dict(id=f"{now['id']}@signin@{now.get('started')}", kind="signin", title=f"Sign In For {now['id']}",
                          question=now.get("ask") or read(os.path.join(HERE, "PAUSED.md")), options=[], recommend="",
                          at=now.get("started") or ""))
    lines = [f"Needs you · verify: sign in for {now['id']}: {now.get('ask') or ''}".rstrip(": ")] if paused and now else []
    lines += [f"Needs you · verify: {t['id']}: {t['ask']}" for t in needs]
    return state, events, cards, [], lines


def page(slug):
    """The writes this page still needs, from what was last marked written, and its attention lines."""
    sync = jload(os.path.join(LIVE, f"{slug}.sync.json"), {"events": 0, "keys": [], "states": 0, "state": "", "asks": [], "reviews": []})
    if slug == "verify" and CONF.get("KIND") == "verify":
        state, events, cards, items, lines = verify()
    else:
        state, events, cards, items, lines = chain(slug, jload(os.path.join(LIVE, f"{slug}.recs.json"), {}))
    peers = [{"slug": s, "url": u} for s, u in sorted(urls().items()) if s != slug]
    writes, new = [], json.loads(json.dumps(sync))
    keys = set(sync["keys"])
    for key, at, text, tone in events:
        if key in keys:
            continue
        new["events"] += 1; new["keys"].append(key)
        writes.append({"op": "set", "collection": "events", "doc_id": f"e{new['events']:06d}",
                       "data": {"seq": new["events"], "at": at, "text": text, "tone": tone}})
    for q in cards:
        if q["id"] not in sync["asks"]:
            new["asks"].append(q["id"])
            writes.append({"op": "set", "collection": "asks", "doc_id": q["id"], "data": q})
    current = {q["id"] for q in cards}
    for qid in sync["asks"]:   # a card the run no longer needs (a sign-in done, a set-aside test requeued) leaves the page
        if qid not in current:
            state["answered"].setdefault(qid, "signed in" if "@signin@" in qid else "answered")
    for r in items:
        if r["id"] not in sync["reviews"]:
            new["reviews"].append(r["id"])
            writes.append({"op": "set", "collection": "reviews", "doc_id": r["id"], "data": r})
    state["peers"] = peers   # in the hash: a page published later reaches the pages with nothing else new
    h = hashlib.sha1(json.dumps(state, sort_keys=True).encode("utf8")).hexdigest()
    if h != sync["state"]:
        new["states"] += 1; new["state"] = h
        writes.append({"op": "set", "collection": "state", "doc_id": f"s{new['states']:06d}",
                       "data": dict(state, seq=new["states"])})
    return writes, new, lines


def main(a):
    if not a:
        print(__doc__); sys.exit(2)
    sys.stdout.reconfigure(encoding="utf-8")   # redirected on Windows, stdout is cp1252: no "→", no "·" in some notes
    os.makedirs(LIVE, exist_ok=True)
    known = urls()
    if a[0] == "--attention":
        for slug, url in sorted(known.items()):
            for line in page(slug)[2]:
                print(f"{line} → {url}")
        return
    done = "--done" in a
    slugs = sorted(known) if "--all" in a else [s for s in a if not s.startswith("--")]
    out = []
    for slug in slugs:
        pend = os.path.join(LIVE, f"{slug}.pending.json")
        if done:
            p = jload(pend, None)
            if p:
                json.dump(p["sync"], open(os.path.join(LIVE, f"{slug}.sync.json"), "w", encoding="utf8"), indent=1)
                os.remove(pend)
                print(f"{slug}: {len(p['writes'])} writes marked written")
            continue
        writes, new, lines = page(slug)
        json.dump({"writes": writes, "sync": new}, open(pend, "w", encoding="utf8"), indent=1, ensure_ascii=False)
        out.append({"slug": slug, "url": known.get(slug), "writes": writes, "attention": lines})
    if not done:
        print(json.dumps({"pages": out}, ensure_ascii=False, indent=1))
        missing = [p["slug"] for p in out if not p["url"]]
        if missing:
            print(f"not published yet (live_page.py, then --url): {', '.join(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
