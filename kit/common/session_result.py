"""Summarise one `claude -p --output-format stream-json` session log for the wrapper:
prints subtype|cost_usd|turns|api_error|first 160 chars of the result, pipe-separated (api_error is empty unless the API
refused the session, e.g. usage_limit_reached)."""
import json, sys

r, frame_error = {}, ""
for line in open(sys.argv[1], encoding="utf8", errors="replace"):
    try:
        j = json.loads(line)
    except ValueError:
        continue
    if j.get("type") == "result":
        r = j
    elif j.get("type") == "assistant" and j.get("error"):
        frame_error = str(j.get("error"))  # some Claude Code versions put usage_limit_reached on the assistant frame
api_error = str(r.get("api_error") or "") or frame_error or ("rate_limit_error" if r.get("api_error_status") == 429 else "")
print("|".join([r.get("subtype", "no-result"), str(round(r.get("total_cost_usd") or 0, 2)), str(r.get("num_turns")),
                 api_error,
                (r.get("result") or "")[:160].replace("\n", " ").replace("|", "/")]))
