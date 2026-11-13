"""Stop hook for verify sessions: a session may not end until this session's work is in the ledger and HANDOFF.md exists.
Blocks once per stop attempt (stop_hook_active lets the second attempt through)."""
import json, os, subprocess, sys, time

RUN = os.environ.get("LOOP_STATE") or os.path.dirname(os.path.abspath(__file__))


def mtime(name):
    p = os.path.join(RUN, name)
    return os.path.getmtime(p) if os.path.exists(p) else 0


def main(d):
    if d.get("stop_hook_active"):
        return
    try:
        start = float(open(os.path.join(RUN, "state", "session_start")).read().strip())
    except (OSError, ValueError):
        start = time.time() - 86400
    remaining = int(subprocess.run([sys.executable, os.path.join(RUN, "ledger.py"), "remaining"],
                                   capture_output=True, text=True).stdout.strip() or "1")
    if remaining == 0:
        return
    missing = []
    if mtime("ledger.json") < start:
        missing.append("record this session's results with ledger.py (set / note / needs / pause)")
    if mtime("HANDOFF.md") < start:
        missing.append("write HANDOFF.md in the format the runbook gives")
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
                              "Before ending: record this session's results with ledger.py and write HANDOFF.md. Then end your reply."}))
