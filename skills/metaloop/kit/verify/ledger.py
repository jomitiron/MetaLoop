"""The verify run's durable state. Sessions change ledger.json ONLY through this script.

  python ledger.py next                         next test to work on (an interrupted in_progress one first)
  python ledger.py start ID                     mark ID in_progress
  python ledger.py set ID pass|fail|blocked "one-line result" [--ref REF]... [--evidence PATH]...
  python ledger.py note ID "text"               append a note (findings, records created, partial progress)
  python ledger.py ref ID "Invoice 1042"        record a reference the test created (an id in the app or a third party)
  python ledger.py pause ID "exact ask" --signin   ONLY for the run's pause reason (loop.conf PAUSE_FOR): stops the run
                                                for the owner (writes PAUSED.md)
  python ledger.py needs ID "exact ask"         needs the owner for anything else: recorded as blocked with the ask,
                                                the run goes on; the owner gets every ask at the end
  python ledger.py verify V3 seen|not-seen "what you saw" [--test ID]
  python ledger.py defect ID "title" "observed / expected / evidence"   draft only, never filed by the loop
  python ledger.py show ID                      one item as JSON
  python ledger.py summary [--short]            counts and the non-pass items
  python ledger.py wait SECONDS                 sleep (e.g. for a retry tick), max 900

Wrapper and main session: build SHA · resume ID · skip ID "reason" · requeue ID... · paused-id · remaining · fingerprint ·
session N "end" COST TURNS · report · requires-check "cap,cap"
(requires-check: every todo test whose `Requires:` line names a capability not in the list is recorded blocked with
the ask to make it available, so no session spends itself on it; requeue it once it is there)
"""
import datetime, hashlib, json, os, sys, time

RUN = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(RUN, "ledger.json")
FINAL = {"pass", "fail", "blocked"}
# How the owner makes a capability available, for the asks requires-check records: the project profile's "caps"
# ({"webhooks": "run the provider's CLI listener as a verify service, ..."}). Unknown ones get a generic ask.
try:
    HOW = json.load(open(os.path.join(RUN, "project.json"), encoding="utf8")).get("caps") or {}
except (OSError, ValueError):
    HOW = {}
try:
    CONF = json.load(open(os.path.join(RUN, "loop.json"), encoding="utf8"))
except (OSError, ValueError):
    CONF = {}
OWNER = CONF.get("OWNER", "the owner")
USAGE = __doc__.replace("python ledger.py", CONF.get("PYTHON", "python") + " ledger.py")  # python3 on macOS
PAUSE_FOR = CONF.get("PAUSE_FOR", "a sign-in that needs a person")


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load():
    return json.load(open(PATH, encoding="utf8"))


def save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(d, f, indent=1)
    for _ in range(20):
        try:
            os.replace(tmp, PATH)
            return
        except PermissionError:  # a reader on Windows holds the file for a moment
            time.sleep(0.25)
    raise SystemExit("ledger.json is locked; try again")


def item(d, tid):
    for t in d["tests"] + d["verify"]:
        if t["id"].lower() == tid.lower():
            return t
    raise SystemExit(f"no such id: {tid}")


def opts(args, flag):
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == flag]


def counts(d):
    c = {}
    for t in d["tests"]:
        c[t["status"]] = c.get(t["status"], 0) + 1
    return c


def main(a):
    if not a:
        print(USAGE)
        return
    cmd, d = a[0], load()

    if cmd == "next":
        pending = [t for t in d["tests"] if t["status"] in ("in_progress", "resumed")] or \
                  [t for t in d["tests"] if t["status"] == "todo"]
        if not pending:
            waiting = [t["id"] for t in d["tests"] if t["status"] == "awaiting_human"]
            print("NONE: every test is recorded." if not waiting else f"NONE runnable; awaiting {OWNER}: {waiting}")
            return
        t = pending[0]
        print(f"{t['id']} [{t['status']}] {t['title']}")
        print(f"file: tests/{t['id']}.md" if t["id"] != "P0" else "file: runbook.md section 'P0'")
        if t.get("hint"):
            print(f"hint: {t['hint']}")
        if t["notes"]:
            print("notes so far:\n  - " + "\n  - ".join(t["notes"][-8:]))
        return

    if cmd == "start":
        t = item(d, a[1])
        t["status"], t["started"] = "in_progress", t["started"] or now()
    elif cmd == "set":
        t, st = item(d, a[1]), a[2]
        if st not in FINAL:
            raise SystemExit(f"status must be one of {sorted(FINAL)}")
        t.update(status=st, result=a[3] if len(a) > 3 else "", finished=now())
        t["refs"] += opts(a, "--ref")
        t["evidence"] += opts(a, "--evidence")
    elif cmd == "note":
        item(d, a[1])["notes"].append(f"{now()} {a[2]}")
    elif cmd == "ref":
        item(d, a[1])["refs"].append(a[2])
    elif cmd == "needs":
        t = item(d, a[1])
        t.update(status="blocked", result=f"needs {OWNER}: {a[2]}", ask=a[2], needs_owner=True, finished=now())
    elif cmd == "pause":
        if "--signin" not in a:
            raise SystemExit(f"REFUSED: the run pauses ONLY for {PAUSE_FOR} (add --signin). For anything else use: "
                             "python ledger.py needs ID \"exact ask\" (recorded as blocked; the run goes on).")
        t = item(d, a[1])
        t.update(status="awaiting_human", ask=a[2])
        t["notes"].append(f"{now()} paused for {OWNER}: {a[2]}")
        open(os.path.join(RUN, "PAUSED.md"), "w", encoding="utf8").write(f"# {t['id']} · {t['title']}\n\n{a[2]}\n")
    elif cmd == "verify":
        v = item(d, a[1])
        if a[2] not in ("seen", "not-seen"):
            raise SystemExit("verify status must be seen or not-seen")
        v["status"] = a[2]
        test = opts(a, "--test")
        v["notes"].append(f"{now()} {('[' + test[0] + '] ') if test else ''}{a[3] if len(a) > 3 else ''}")
    elif cmd == "defect":
        d["defects"].append({"test": a[1], "title": a[2], "detail": a[3] if len(a) > 3 else "", "at": now(), "filed": False})
    elif cmd == "show":
        print(json.dumps(item(d, a[1]), indent=1))
        return
    elif cmd == "summary":
        c = counts(d)
        print(" · ".join(f"{k} {v}" for k, v in sorted(c.items())) + f" · of {len(d['tests'])}")
        if "--short" not in a:
            for t in d["tests"]:
                if t["status"] in ("fail", "blocked", "awaiting_human", "in_progress"):
                    print(f"  {t['id']} {t['status']}: {t['result'] or t['ask'] or ''}")
            seen = [v["id"] for v in d["verify"] if v["status"] == "seen"]
            print(f"  verify seen: {seen or 'none'} · defects drafted: {len(d['defects'])}")
        return
    elif cmd == "wait":
        time.sleep(min(int(a[1]), 900))
        print(f"waited {min(int(a[1]), 900)}s")
        return
    # ---- wrapper and main session
    elif cmd == "build":
        d["build"] = a[1]
    elif cmd == "resume":
        t = item(d, a[1])
        t["status"] = "resumed"
        t["notes"].append(f"{now()} {OWNER} finished the human step")
    elif cmd == "requeue":  # after the owner clears an ask, or to re-verify after fixes merge: the old result is kept as a note
        for tid in a[1:]:
            t = item(d, tid)
            t["notes"].append(f"{now()} requeued; earlier result: {t['result']}")
            t.update(status="todo", result=None, ask=None, needs_owner=False, finished=None)
    elif cmd == "skip":
        t = item(d, a[1])
        t.update(status="blocked", result=a[2], finished=now())
    elif cmd == "paused-id":
        print(next((t["id"] for t in d["tests"] if t["status"] == "awaiting_human"), ""))
        return
    elif cmd == "remaining":
        print(sum(1 for t in d["tests"] if t["status"] not in FINAL))
        return
    elif cmd == "fingerprint":
        # "<results>:<notes>": results, references and drafted defects are progress; the timestamped notes every session
        # adds are counted apart, so a run of sessions that only take notes can be told from one that moves tests on
        strip = lambda xs: [{k: v for k, v in x.items() if k != "notes"} for x in xs]
        h = lambda o: hashlib.sha1(json.dumps(o, sort_keys=True).encode()).hexdigest()[:12]
        print(h([strip(d["tests"]), strip(d["verify"]), d["defects"]]) + ":" + h([x["notes"] for x in d["tests"] + d["verify"]]))
        return
    elif cmd == "requires-check":
        have = {c.strip() for c in (a[1] if len(a) > 1 else "").split(",") if c.strip()}
        hit = []
        for t in d["tests"]:
            missing = [r for r in t.get("requires", []) if r not in have]
            if t["status"] == "todo" and missing:
                ask = "; ".join(HOW.get(r, f"make '{r}' available on this machine (or, if it already is, add it to "
                                           "loop.conf HAVE_CAPS), then requeue this test") for r in missing)
                t.update(status="blocked", result=f"needs {OWNER}: requires {', '.join(missing)}, not available on this machine",
                         ask=ask, needs_owner=True, finished=now())
                hit.append(t["id"])
        save(d)
        print(f"blocked up front, requirement missing: {' '.join(hit)}" if hit else "ok")
        return
    elif cmd == "session":
        d["sessions"].append({"n": int(a[1]), "end": a[2], "cost_usd": a[3], "turns": a[4], "at": now()})
    elif cmd == "report":
        c = counts(d)
        print(f"# {d.get('run', 'Live verify')}: results\n\nBuild {d['build']} · {now()} · " +
              " · ".join(f"{k} {v}" for k, v in sorted(c.items())) + "\n")
        print("| Test | Result | Summary | References |\n|---|---|---|---|")
        for t in d["tests"]:
            print(f"| {t['id']} {t['title']} | {t['status']} | {(t['result'] or t['ask'] or '').replace('|', '/')} | {', '.join(t['refs'])} |")
        asks = [t for t in d["tests"] if t.get("needs_owner")]
        if asks:
            print(f"\n## Needs {OWNER} (blocked; do these, then requeue the tests)\n")
            for t in asks:
                print(f"- **{t['id']}** {t['title']}: {t['ask']}")
        if d["verify"]:
            print("\n## Verify list\n")
            for v in d["verify"]:
                print(f"- {v['id']} {v['status']}: {' / '.join(v['notes'])}")
        print("\n## Defects drafted (not filed)\n")
        for x in d["defects"]:
            print(f"- [{x['test']}] {x['title']}: {x['detail']}")
        return
    else:
        raise SystemExit(f"unknown command {cmd}\n{USAGE}")
    save(d)
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1:])
