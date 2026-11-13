"""Build ledger.json from the run's test plan.

  python init_ledger.py "Run title" [--force]

Reads tests/*.md in name order. Each file's first line is the test's heading: "# ID · Title" (or "# ID - Title").
An optional "Hint: ..." line anywhere in the file becomes the ledger hint (shown by `ledger.py next`); use it to say which
steps need the owner and how (pause only for loop.conf PAUSE_FOR, `needs` for everything else).
An optional "Requires: cap, cap" line names what the machine must have for the test to run at all (e.g. webhooks);
the loop records a test whose requirement is missing as blocked before the first session (ledger.py requires-check).
guide/verify.md, if present, holds suspected gaps as table rows "| V1 | what | where | code |"; each becomes a verify item.
A P0 item (baseline the system before the first test) is always first: the runbook says what P0 records.
Refuses to overwrite an existing ledger without --force (a ledger is the run's history).
"""
import datetime, json, os, re, sys

RUN = os.path.dirname(os.path.abspath(__file__))


def main(a):
    if not a:
        print(__doc__); sys.exit(2)
    path = os.path.join(RUN, "ledger.json")
    if os.path.exists(path) and "--force" not in a:
        sys.exit("ledger.json exists; pass --force to rebuild it (requeue tests with ledger.py requeue instead)")
    tests = [{"id": "P0", "title": "Baseline the system before the first test", "hint": ""}]
    tdir = os.path.join(RUN, "tests")
    for name in sorted(os.listdir(tdir)):
        if not name.endswith(".md"):
            continue
        text = open(os.path.join(tdir, name), encoding="utf8").read()
        m = re.match(r"#\s*([A-Za-z0-9]+)\s*[·\-:]\s*(.+)", text.splitlines()[0] if text else "")
        if not m:
            sys.exit(f"tests/{name}: first line must be '# ID · Title'")
        if m.group(1) + ".md" != name:
            sys.exit(f"tests/{name}: heading id {m.group(1)} doesn't match the file name")
        hint = re.search(r"^Hint:\s*(.+)$", text, re.M)
        req = re.search(r"^Requires:\s*(.+)$", text, re.M)
        tests.append({"id": m.group(1), "title": m.group(2).strip(), "hint": hint.group(1).strip() if hint else "",
                      "requires": [r for r in re.split(r"[,\s]+", req.group(1)) if r] if req else []})
    verify = []
    vp = os.path.join(RUN, "guide", "verify.md")
    if os.path.exists(vp):
        verify = [{"id": v, "status": "unchecked", "notes": []}
                  for v in re.findall(r"^\|\s*(V\d+)\s*\|", open(vp, encoding="utf8").read(), re.M)]
    for t in tests:
        t.update(status="todo", result=None, notes=[], refs=[], evidence=[], started=None, finished=None, ask=None)
    ledger = {"run": a[0], "created": datetime.datetime.now().isoformat(timespec="seconds"), "build": None,
              "tests": tests, "verify": verify, "defects": [], "sessions": []}
    json.dump(ledger, open(path, "w", encoding="utf8"), indent=1)
    print(f"ledger.json: {len(tests)} items (P0 + {len(tests) - 1} tests), {len(verify)} verify rows")


if __name__ == "__main__":
    main(sys.argv[1:])
