"""The project profile: `.metaloop/project.json` in the repository a run works on. It says how that project builds, tests
and serves, which background services (databases, caches, queues, listeners) its checks need, and which tools it needs.
Everything stack-specific lives there: the kit assumes no language, framework or database. `init_project.py` writes a
first one from the presets in kit/presets (a stack, and any databases); `init_run.py` copies it into every run folder.

  python project.py check                 validate the run's project.json; exit 1 with the problems
  python project.py get KEY               a value by dotted key (verify.start); lists come out comma-separated
  python project.py exports SECTION       `export` lines for the project's env plus SECTION's env (e.g. verify)

Shape (reference/project.md has it in full):
  requires      [{tool, for, check?, install, who, skip?}]   tools the checks need; `skip` names the gate step the owner
                                                              may leave out instead (GATE_SKIP) when the tool is missing
  env           {VAR: value}                                  every gate step and the verify server
  gate.steps    [{name, run, tests?, slots?, services?, env?, skippable?, continue?, hints?}]
  services      {name: {port?, start?, up?, init?, ready?, stop?, seed?, env?, timeout?, requires?}}
  verify        {url, health, build?, start, env?, services?, provides?, timeout?}
  chain_allow   ["npm test *", ...]                           extra commands fix-chain sessions may run
  verify_allow  ["psql *", ...]                               extra commands verify sessions may run
  caps          {capability: "how the owner makes it available"}
Commands run under bash (Git Bash on Windows). In commands and env values {port} {slot} {dir} {id} {run} {root}
{app_url} {app_port} are filled in; nothing else in braces is touched.
"""
import json, os, re, shlex, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILL_IN = "FILL IN"
VARS = ("port", "slot", "dir", "id", "run", "root", "app_url", "app_port")

# Test-output parsers for gate steps ("tests": "<name>" or an object of the same shape). A step with a parser fails when
# no summary line is found, when zero tests ran, or when more tests failed than known-flake names matched; one without
# a parser passes on exit code 0 alone.
#   line:   a summary line (every match counts: one per test project, module or package)
#   passed / failed / total / skipped:  numbers inside that line, summed (passed = total - failed - skipped when absent)
#   count_passed / count_failed:        instead of a summary line, count these lines across the whole log
#   name:   a failing test's name (group 1), to match KNOWN_FLAKES and KNOWN_PLATFORM_FAILURES
PARSERS = {
    "dotnet": {"line": r"(?:Passed|Failed)!\s*-\s*Failed:\s*\d+,\s*Passed:\s*\d+[^\n]*",
               "failed": r"Failed:\s*(\d+)", "passed": r"Passed:\s*(\d+)",
               "name": r"^\s*Failed\s+([\w.<>`,\[\]()\- ]+?)\s+\["},
    "pytest": {"line": r"^(?:=+ )?(?:no tests ran|\d+ \w+)(?:, \d+ \w+)* in [\d.]+s(?: \([\d:.]+\))?(?: =+)?\s*$",
               "failed": r"(\d+) (?:failed|errors?)\b", "passed": r"(\d+) passed",
               "name": r"^(?:FAILED|ERROR) (\S+)"},
    "jest":   {"line": r"^Tests:\s+.*\btotal\b", "failed": r"(\d+) failed", "passed": r"(\d+) passed",
               "name": r"^\s+●\s+(?!Console\b)(.+?)\s*$"},
    "vitest": {"line": r"^\s*Tests\s+.*\(\d+\)\s*$", "failed": r"(\d+) failed", "passed": r"(\d+) passed",
               "name": r"^\s*(?:FAIL|×)\s+(.+?)\s*$"},
    "go":     {"count_passed": r"^\s*--- PASS: ", "count_failed": r"^\s*--- FAIL: ", "name": r"^\s*--- FAIL: (\S+)"},
    "rspec":  {"line": r"^\d+ examples?, \d+ failures?", "total": r"(\d+) examples?", "failed": r"(\d+) failures?",
               "skipped": r"(\d+) pending", "name": r"^rspec (\S+)"},
    "maven":  {"line": r"^\[(?:INFO|ERROR|WARNING)\] Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+\s*$",
               "total": r"Tests run: (\d+)", "failed": r"(?:Failures|Errors): (\d+)", "skipped": r"Skipped: (\d+)",
               "name": r"^\[ERROR\]\s+(\S+?)(?::\d+)?\s+(?:»|<<<|Time elapsed)"},
    "cargo":  {"line": r"^test result: ", "passed": r"(\d+) passed", "failed": r"(\d+) failed",
               "name": r"^test (\S+) \.\.\. FAILED"},
    "phpunit": {"line": r"^(?:OK \(\d+ tests?|Tests: \d+)", "total": r"(?:OK \((\d+) tests?|Tests: (\d+))",
                "failed": r"(?:Failures|Errors): (\d+)", "skipped": r"Skipped: (\d+)", "name": r"^\d+\) (\S+)"},
}


def path(p=None):
    return p or os.path.join(HERE, "project.json")


def load(p=None):
    """The profile, or {} when the run has none."""
    try:
        return json.load(open(path(p), encoding="utf8"))
    except FileNotFoundError:
        return {}


def fill(text, **values):
    """Fill the known {var} placeholders; leave every other brace alone (shell, JSON and JS use them)."""
    for k in VARS:
        if k in values and values[k] is not None:
            text = text.replace("{" + k + "}", str(values[k]))
    return text


def parser(spec):
    if isinstance(spec, str):
        return PARSERS.get(spec)
    return spec if isinstance(spec, dict) else None


def _num(rx, text):
    total = 0
    for m in re.finditer(rx, text, re.M):
        g = next((x for x in m.groups() if x), None) if m.groups() else None
        total += int(g) if g else 0
    return total


def parse_tests(text, spec):
    """{summary, passed, failed, failed_tests} from a test step's log; passed/failed are None when it can't tell."""
    p = parser(spec) or {}
    names = []
    if p.get("name"):
        names = sorted({m.group(1).strip() for m in re.finditer(p["name"], text, re.M)})
    if "count_passed" in p or "count_failed" in p:
        passed = len(re.findall(p.get("count_passed", r"(?!x)x"), text, re.M))
        failed = len(re.findall(p.get("count_failed", r"(?!x)x"), text, re.M))
        return {"summary": f"{passed} passed, {failed} failed (counted)", "passed": passed, "failed": failed,
                "failed_tests": names}
    # the whole line each match sits on: the counts a pattern didn't reach (", 2 pending") still count
    lines = [text[text.rfind("\n", 0, m.start()) + 1:(text.find("\n", m.end()) + 1 or len(text) + 1) - 1].strip()
             for m in re.finditer(p.get("line", r"(?!x)x"), text, re.M)]
    if not lines:
        return {"summary": None, "passed": None, "failed": None, "failed_tests": names}
    joined = "\n".join(lines)
    failed = _num(p["failed"], joined) if p.get("failed") else 0
    if p.get("passed"):
        passed = _num(p["passed"], joined)
    else:
        passed = _num(p.get("total", r"(?!x)x"), joined) - failed - (_num(p["skipped"], joined) if p.get("skipped") else 0)
    return {"summary": lines[-1] if len(lines) == 1 else f"{lines[-1]} (+{len(lines) - 1} more)", "passed": max(passed, 0),
            "failed": failed, "failed_tests": names}


def problems(p, kind=None):
    """What keeps this profile from driving a run (kind: fix, verify or None for both)."""
    out = []
    if not p:
        return ["no project profile (.metaloop/project.json): write one with init_project.py"]
    services = p.get("services") or {}
    steps = (p.get("gate") or {}).get("steps") or []
    if kind in (None, "fix"):
        if not steps:
            out.append("gate.steps is empty: the gate has nothing to run")
        seen = set()
        for s in steps:
            n = s.get("name")
            if not n or not s.get("run"):
                out.append(f"a gate step needs a name and a run command: {s}")
            if n in seen:
                out.append(f"two gate steps are named {n}")
            seen.add(n)
            if s.get("tests") and not parser(s["tests"]):
                out.append(f"gate step {n}: unknown tests parser {s['tests']!r} (one of {', '.join(PARSERS)}, or an object)")
            out += [f"gate step {n} uses service {x}, which services doesn't define" for x in s.get("services", []) if x not in services]
    if kind in (None, "verify"):
        v = p.get("verify") or {}
        out += [f"verify uses service {x}, which services doesn't define" for x in verify_services(p) if x not in services]
        if v and not v.get("url"):
            out.append("verify.url is missing (where the app under test answers)")
    for name, svc in services.items():
        if svc.get("start") and not svc.get("ready"):
            out.append(f"service {name} starts something but has no ready check")
    out += [f"{k} still says {FILL_IN}: {v[:80]}" for k, v in flat(p) if isinstance(v, str) and FILL_IN in v
            and (kind is None or not k.startswith("verify" if kind == "fix" else "gate"))]
    return out


def flat(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from flat(v, f"{prefix}{k}.")
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from flat(v, f"{prefix}{i}.")
    else:
        yield prefix.rstrip("."), d


def verify_services(p):
    """The verify loop's services: verify.services is a list of names, or {name: overrides} (persist, seed, reuse)."""
    v = (p.get("verify") or {}).get("services") or []
    return list(v) if isinstance(v, (list, dict)) else []


def service_spec(p, name, use=None):
    """A service's spec, with the verify loop's overrides when use == 'verify'."""
    spec = dict((p.get("services") or {}).get(name) or {})
    v = (p.get("verify") or {}).get("services")
    if use == "verify" and isinstance(v, dict) and isinstance(v.get(name), dict):
        spec.update(v[name])
    return spec


def requirements(p, kind):
    """Every tool this kind of run needs: the profile's own, and those of the services it uses."""
    reqs = list(p.get("requires") or [])
    used = set(verify_services(p)) if kind == "verify" else \
        {x for s in (p.get("gate") or {}).get("steps") or [] for x in s.get("services", [])}
    for name in sorted(used):
        for r in service_spec(p, name).get("requires") or []:
            r = dict(r, **{"for": r.get("for") or f"the {name} service"})
            if kind == "fix" and "skip" not in r:  # a service only a skippable step uses can be left out with it
                users = [s for s in p["gate"]["steps"] if name in s.get("services", [])]
                if users and all(s.get("skippable") for s in users):
                    r["skip"] = ",".join(s["name"] for s in users)
            reqs.append(r)
    out = {}
    for r in reqs:  # one line per tool: two databases in Docker need Docker once
        key = r.get("tool")
        if key in out:
            out[key]["for"] = ", ".join(dict.fromkeys(out[key].get("for", "").split(", ") + [r.get("for", "")]))
            if "skip" in out[key] and "skip" not in r:
                del out[key]["skip"]  # another user can't be skipped, so neither can the tool
        else:
            out[key] = dict(r)
    return list(out.values())


def get(p, key):
    cur = p
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    if isinstance(cur, (list, dict)):
        return ",".join(str(x) for x in cur)
    return "" if cur is None else str(cur)


def exports(p, section, **values):
    env = dict(p.get("env") or {})
    env.update((p.get(section) or {}).get("env") or {})
    return "\n".join(f"export {k}={shlex.quote(fill(str(v), **values))}" for k, v in env.items())


def main(a):
    if not a:
        print(__doc__); sys.exit(2)
    p = load()
    if a[0] == "check":
        probs = problems(p, a[1] if len(a) > 1 else None)
        for x in probs:
            print(f"  - {x}")
        print("project.json: ok" if not probs else f"project.json: {len(probs)} problem(s)")
        sys.exit(1 if probs else 0)
    if a[0] == "get":
        print(get(p, a[1]))
    elif a[0] == "exports":
        conf = {}
        try:
            conf = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
        except (OSError, ValueError):
            pass
        url = conf.get("APP_URL", "")
        port = re.search(r":(\d+)", url.split("//", 1)[-1])
        print(exports(p, a[1], app_url=url, app_port=port.group(1) if port else "", run=HERE,
                      root=conf.get("VERIFY_WORKTREE", "")))
    else:
        print(__doc__); sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
