"""PostToolUse / PostToolUseFailure hook for every loop session.

1. Keeps every request under 75% of the context window. projected next request = the last request's input (incl. cache)
   + its output + every tool result returned since (summed across parallel calls, x1.25 + 300 for framing).
   Over SOFT_PCT: tells the session to hand off. Over HARD_PCT: ends the session ({"continue": false}) and writes
   state/last_stop.json so the wrapper can say what happened.
2. Ends the session if it isn't on the pinned model and effort (wrong-model).
3. Fails closed: a guard that can't measure stops the session (guard-error).

Configuration comes from the environment the wrapper exports: LOOP_STATE (the folder holding state/ and logs/),
LOOP_MODEL, LOOP_EFFORT, LOOP_CTX_WINDOW, LOOP_SOFT_PCT, LOOP_HARD_PCT.
Needs the session transcript: never run a loop session with --no-session-persistence.
"""
import json, os, sys, time, traceback

STATE_ROOT = os.environ.get("LOOP_STATE") or os.path.dirname(os.path.abspath(__file__))
WINDOW = int(os.environ.get("LOOP_CTX_WINDOW", "1000000"))
SOFT = float(os.environ.get("LOOP_SOFT_PCT", "65")) / 100
HARD = float(os.environ.get("LOOP_HARD_PCT", "72")) / 100
MODEL = os.environ.get("LOOP_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("LOOP_EFFORT", "high")
IMG = 1600  # tokens charged per image block
STATE = os.path.join(STATE_ROOT, "state")
LOG = os.path.join(STATE_ROOT, "logs", "ctx.log")


def log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf8") as f:
        f.write(time.strftime("%H:%M:%S ") + line + "\n")


def last_usage(path):
    size = os.path.getsize(path)
    for back in (8_000_000, size):
        with open(path, "rb") as f:
            f.seek(max(0, size - back))
            lines = f.read().splitlines()
        for raw in reversed(lines):
            if b'"usage"' not in raw:
                continue
            try:
                j = json.loads(raw)
            except ValueError:
                continue
            m = j.get("message") or {}
            u = m.get("usage")
            if j.get("type") != "assistant" or not u or m.get("model") == "<synthetic>" or j.get("isSidechain"):
                continue
            ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            return ctx, u.get("output_tokens", 0), m.get("model", "")
    return None


def est(o):
    if isinstance(o, str):
        if len(o) > 4000 and " " not in o[:3000]:
            return IMG  # base64 payload
        return len(o) // 3 + 1
    if isinstance(o, dict):
        if o.get("type") == "image":
            return IMG
        return sum(est(v) for v in o.values())
    if isinstance(o, list):
        return sum(est(x) for x in o)
    return 1


class Lock:
    """Parallel tool calls fire the hook concurrently; their pending sums must not overwrite each other."""
    def __init__(self, p):
        self.p = p

    def __enter__(self):
        for _ in range(200):
            try:
                os.mkdir(self.p)
                return self
            except FileExistsError:
                time.sleep(0.05)
        return self

    def __exit__(self, *a):
        try:
            os.rmdir(self.p)
        except OSError:
            pass


def stop(reason, d, extra):
    json.dump(dict(reason=reason, session=d.get("session_id"), tool=d.get("tool_name"), at=time.strftime("%Y-%m-%dT%H:%M:%S"), **extra),
              open(os.path.join(STATE, "last_stop.json"), "w", encoding="utf8"))
    print(json.dumps({"continue": False, "stopReason": f"[context guard] {reason}"}))


def main():
    d = json.load(sys.stdin)
    os.makedirs(STATE, exist_ok=True)
    sid, tool, ev = d.get("session_id", "?"), d.get("tool_name", "?"), d.get("hook_event_name", "PostToolUse")

    # Fail closed on a missing level too: nothing else can confirm the effort, and an unconfirmed pin is not a pin. If a
    # Claude Code release stops sending it, every session stops on its first tool call with this reason, loudly.
    effort = (d.get("effort") or {}).get("level")
    if effort is None:
        log(f"{sid[:8]} {tool} STOP no-effort-in-payload")
        return stop(f"the hook payload carries no effort level, so the {EFFORT} pin can't be confirmed (has the hook schema "
                    "changed in this Claude Code version?)", d, {"kind": "wrong-model"})
    if effort != EFFORT:
        log(f"{sid[:8]} {tool} STOP wrong-effort {effort}")
        return stop(f"wrong effort: {effort} (must be {EFFORT})", d, {"kind": "wrong-model"})

    u = last_usage(d["transcript_path"])
    if not u:
        log(f"{sid[:8]} {tool} no usage yet")
        return
    ctx, out, model = u
    if not model.startswith(MODEL):
        log(f"{sid[:8]} {tool} STOP wrong-model {model}")
        return stop(f"wrong model: {model} (must be {MODEL})", d, {"kind": "wrong-model"})

    # x1.25 + 300: the model sees results with framing (tool_use/tool_result blocks, Read line numbers) the raw response lacks
    add = int(est(d.get("tool_response") if "tool_response" in d else d.get("error", "")) * 1.25) + 300
    sf = os.path.join(STATE, f"ctx-{sid}.json")
    with Lock(sf + ".lock"):
        try:
            s = json.load(open(sf, encoding="utf8"))
        except (OSError, ValueError):
            s = {"seen": -1, "pending": 0}
        if s["seen"] != ctx:
            s = {"seen": ctx, "pending": 0}
        s["pending"] += add
        json.dump(s, open(sf, "w", encoding="utf8"))
    projected = ctx + out + s["pending"]
    pct = projected / WINDOW
    action = "ok"
    if pct >= HARD:
        action = "HARD-STOP"
        stop(f"projected context {pct:.1%} >= hard stop {HARD:.0%}", d, {"kind": "hard-cap", "pct": round(pct, 4)})
    elif pct >= SOFT:
        action = "HANDOFF"
        if ev == "PostToolUse":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                f"[context guard] Context is at {pct:.0%} of the window (hand-off at {SOFT:.0%}, forced stop at {HARD:.0%}, limit 75%). "
                "Start nothing new. Finish only the step in flight, record it as the runbook says, "
                "write the hand-off file, then end your reply.")}}))
    log(f"{sid[:8]} {tool[:40]:40} ctx={ctx} out={out} +{add} pend={s['pending']} -> {pct:.1%} {action}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail closed: a guard that cannot measure must not let the session run on unmeasured.
        log("GUARD-ERROR " + traceback.format_exc().replace("\n", " | "))
        try:
            os.makedirs(STATE, exist_ok=True)
            json.dump({"reason": "guard-error", "kind": "guard-error", "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                      open(os.path.join(STATE, "last_stop.json"), "w", encoding="utf8"))
        finally:
            print(json.dumps({"continue": False, "stopReason": "[context guard] guard error: cannot measure context"}))
