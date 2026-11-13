"""State of ONE branch, kept in <worktree>/.fixloop/status.json. Run from the worktree root:  python $FIXLOOP/task.py ...

  show                         the task, phase, notes so far
  phase NAME "what was done"   NAME: red | green | docs | gate | security | pr | ci | design
  note "text"                  progress, decisions, gotchas (keep it short)
  pr NUMBER URL                the PR you opened
  review "comment (who, where, comment id)" "proposed resolution"
                               a review comment that needs action: PROPOSE only, never apply
  ask "Title" "question" "recommended answer" ["other answer" ...]
                               a question for the owner that does NOT stop the chain: it shows on the branch's live page,
                               you carry on with the recommended answer, and the pr phase waits until it is answered
  done TASK "how it was proved"  tick one of the brief's tasks (T1, T2, ...) once the test that proves it passes
  ready "summary"              PR open, CI read, review comments recorded (or a design page pushed) -> the owner decides
  needs "exact ask"            stuck on something only the owner can answer (chain stops)
  block "reason"               cannot proceed for a reason outside the task (chain stops)
  wait SECONDS                 sleep (max 900), e.g. while the gate or CI runs

Main session only: status · pin [BRIEF] (plan or code: the model pin the next session runs on; with BRIEF, for a branch
not started yet, so not signed off) · requeue "why" (back to todo, so the next runner picks it up) · answer Q1 "answer"
(the owner's answer from the live page; the next session reads it as an OWNER ANSWER note)
"""
import contextlib, datetime, json, os, re, sys, time

RUN = os.path.join(os.getcwd(), ".fixloop")
HERE = os.path.dirname(os.path.abspath(__file__))
try:  # the run's interpreter (python3 on macOS), so the usage below names the command the session is allowed to run
    CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
except (OSError, ValueError):
    CONF = {}
PY = CONF.get("PYTHON", "python")
OWNER = CONF.get("OWNER", "the owner")
USAGE = __doc__.replace("python $FIXLOOP", PY + " $FIXLOOP")
PATH = os.path.join(RUN, "status.json")
LOCK = PATH + ".lock"
FINAL = {"awaiting_owner", "needs_owner", "blocked", "done"}
ARGS = {"phase": 1, "note": 1, "pr": 2, "review": 1, "done": 1, "answer": 2, "wait": 1}   # the fewest each command takes


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load():
    return json.load(open(PATH, encoding="utf8"))


def save(d):
    tmp = PATH + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf8"), indent=1)
    for _ in range(20):
        try:
            os.replace(tmp, PATH)
            return
        except PermissionError:  # a reader on Windows holds the file for a moment
            time.sleep(0.25)
    raise SystemExit("status.json is locked; try again")


@contextlib.contextmanager
def locked():
    """Each change reads, changes and writes status.json under this lock. The chain and the main session (an answer, a
    requeue) both change it, and two changes at once would lose one: the owner's answer or the chain's step."""
    for _ in range(240):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            try:
                if time.time() - os.path.getmtime(LOCK) > 30:   # left by a process that was killed holding it
                    os.remove(LOCK)
            except OSError:
                pass
            time.sleep(0.25)
    else:
        raise SystemExit("status.json is locked; try again")
    try:
        yield
    finally:
        os.close(fd)
        os.remove(LOCK)


def wake(slug, line):
    """A line in the run's log that the main session's watcher (wait_chain.sh) wakes on. One line: a newline in a
    chain's text must not add a forged "chain ended" or "STOP" line."""
    one = lambda s: re.sub(r"[\r\n]+", " ", str(s))
    try:
        with open(os.path.join(HERE, "logs", "runner.log"), "a", encoding="utf8") as f:
            f.write(f"[{datetime.datetime.now():%m-%d %H:%M:%S}] [{one(slug)}] {one(line)}\n")
    except OSError:
        pass


def pin(brief, notes):
    """A design branch plans until its sign-off (record_signoff.py notes "SIGNED OFF (" and requeues it to build)."""
    design = re.search(r"^Mode: design\.", brief, re.M)
    return "plan" if design and not any(" SIGNED OFF (" in n for n in notes) else "code"


def main(a):
    sys.stdout.reconfigure(encoding="utf-8")   # a note or question with "→" must not crash `show` on Windows (cp1252)
    if not a:
        print(USAGE); return
    if a[0] == "pin" and len(a) > 1:  # the runner, for a queued branch with no worktree yet
        print(pin(open(a[1], encoding="utf8").read(), [])); return
    if not os.path.exists(PATH):
        raise SystemExit("no .fixloop/status.json here: run from the worktree root")
    cmd = a[0]
    if len(a) - 1 < ARGS.get(cmd, 0):
        raise SystemExit(f"{cmd} is missing an argument\n{USAGE}")
    if cmd == "show":
        d = load()
        print(f"{d['slug']} [{d['status']}] phase={d['phase']} pr={d.get('pr') or '-'}")
        for n in d["notes"][-12:]:
            print("  -", n)
        if d["reviews"]:
            print("  reviews recorded:", len(d["reviews"]))
        for q in d.get("asks", []):
            print(f"  {q['id']} [{q['status']}] {q['title']}: " +
                  (f"answered: {q['answer']}" if q["status"] == "answered" else f"carrying on with: {q['options'][0]['text']}"))
        if d.get("tasks_done"):
            print("  tasks done:", ", ".join(d["tasks_done"]))
        return
    if cmd == "wait":
        s = min(int(a[1]), 900); time.sleep(s); print(f"waited {s}s"); return
    if cmd == "status":
        print(load()["status"]); return
    if cmd == "pin":
        print(pin(open(os.path.join(RUN, "brief.md"), encoding="utf8").read(), load()["notes"])); return
    with locked():
        d = load()
        change(cmd, a, d)
        save(d)
    print("ok")


def change(cmd, a, d):
    if cmd == "phase":
        waiting = [q["id"] for q in d.get("asks", []) if q["status"] == "open"]
        if a[1] == "pr" and waiting:  # the owner may still answer differently: nothing is published on an assumption
            raise SystemExit(f"{', '.join(waiting)} still open: {OWNER} hasn't answered. Hold the pull request: finish this "
                             f"session with task.py needs \"holding the pull request until {OWNER} answers {', '.join(waiting)}\"")
        d["phase"] = a[1]; d["status"] = "in_progress"
        d["notes"].append(f"{now()} [{a[1]}] {a[2] if len(a) > 2 else ''}")
    elif cmd == "note":
        d["notes"].append(f"{now()} {a[1]}")
    elif cmd == "pr":
        d["pr"] = {"number": int(a[1]), "url": a[2]}
        d["notes"].append(f"{now()} PR #{a[1]} opened")
    elif cmd == "review":
        d["reviews"].append({"comment": a[1], "proposal": a[2] if len(a) > 2 else "", "at": now()})
    elif cmd == "ask":
        if len(a) < 5:
            raise SystemExit('ask needs a title, the question, the recommended answer and at least one other answer')
        asks = d.setdefault("asks", [])
        qid = f"Q{len(asks) + 1}"
        asks.append({"id": qid, "title": a[1], "question": a[2], "recommend": "a", "at": now(), "status": "open",
                     "options": [{"key": chr(97 + i), "text": t} for i, t in enumerate(a[3:])]})
        d["notes"].append(f"{now()} asked {qid}: {a[1]} (carrying on with: {a[3]})")
        wake(d["slug"], f"chain asks: {d['slug']} {qid} · {a[1]}")
    elif cmd == "answer":
        q = next((q for q in d.get("asks", []) if q["id"] == a[1]), None)
        if not q:
            raise SystemExit(f"no question {a[1]} on this branch")
        q.update(status="answered", answer=a[2], answered=now())
        d["notes"].append(f"{now()} OWNER ANSWER {a[1]} ({OWNER}): {a[2]}. If that isn't what you carried on with, "
                          "redo that part first (test first).")
    elif cmd == "done":
        d.setdefault("tasks_done", [])
        if a[1] not in d["tasks_done"]:
            d["tasks_done"].append(a[1])
        d["notes"].append(f"{now()} task {a[1]} done: {a[2] if len(a) > 2 else ''}")
    elif cmd in ("ready", "needs", "block"):
        d["status"] = {"ready": "awaiting_owner", "needs": "needs_owner", "block": "blocked"}[cmd]
        d["summary"] = a[1] if len(a) > 1 else ""
        d["notes"].append(f"{now()} {d['status']}: {d['summary']}")
    elif cmd == "requeue":
        d["status"] = "todo"; d["notes"].append(f"{now()} requeued: {a[1] if len(a) > 1 else ''}")
    else:
        raise SystemExit(f"unknown command {cmd}\n{USAGE}")


if __name__ == "__main__":
    main(sys.argv[1:])
