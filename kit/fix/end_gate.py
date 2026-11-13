"""Stop hook for branch sessions: a session may not end until this session's progress is in .fixloop/status.json and
.fixloop/HANDOFF.md is written, unless the task reached a final state. Blocks once per stop attempt."""
import json, os, sys, time

RUN = os.environ.get("LOOP_STATE") or os.path.join(os.getcwd(), ".fixloop")
FINAL = {"awaiting_owner", "needs_owner", "blocked", "done"}


def mtime(p):
    return os.path.getmtime(p) if os.path.exists(p) else 0


def main(d):
    if d.get("stop_hook_active"):
        return
    try:
        start = float(open(os.path.join(RUN, "state", "session_start")).read().strip())
    except (OSError, ValueError):
        start = time.time() - 86400
    try:
        status = json.load(open(os.path.join(RUN, "status.json"), encoding="utf8"))["status"]
    except (OSError, ValueError, KeyError):
        status = "?"
    if status in FINAL:
        return
    missing = []
    if mtime(os.path.join(RUN, "status.json")) < start:
        missing.append("record this session's progress with python $FIXLOOP/task.py phase/note")
    if mtime(os.path.join(RUN, "HANDOFF.md")) < start:
        missing.append("write .fixloop/HANDOFF.md in the runbook's format")
    if missing:
        print(json.dumps({"decision": "block", "reason": "[end gate] Before ending: " + "; ".join(missing) + ". Then end your reply."}))


if __name__ == "__main__":
    raw = sys.stdin.read()
    try:
        main(json.loads(raw))
    except Exception as e:
        # Fail closed, once: a gate that cannot check blocks the first stop attempt (stop_hook_active lets the second through,
        # so a broken gate can't trap the session).
        os.makedirs(os.path.join(RUN, "logs"), exist_ok=True)
        with open(os.path.join(RUN, "logs", "end-gate-error.log"), "a", encoding="utf8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {e!r}\n")
        if '"stop_hook_active": true' not in raw.replace('":true', '": true'):
            print(json.dumps({"decision": "block", "reason": f"[end gate] could not check this session's work ({e!r}). "
                              "Before ending: record this session's progress with task.py and write .fixloop/HANDOFF.md. Then end your reply."}))
