"""Create a run folder for one loop from this kit: copies the scripts, renders the templates, writes loop.conf / loop.json.

  python init_run.py verify <run-dir> [KEY=VALUE ...]     a live-verify (QA) loop
  python init_run.py fix    <run-dir> [KEY=VALUE ...]     a fix loop (parallel branch chains)

Run it from a shell inside the repository (Git Bash on Windows). Every KEY can be overridden (see DEFAULTS); the
platform-dependent defaults (PYTHON, CHROME, MAX_PAR) are picked for the machine it runs on, BASE is the repository's
default branch, and APP_URL comes from the project profile. The profile (.metaloop/project.json, or PROJECT=<path>) says
how this project builds, tests and serves: it is copied into the run as project.json, and its chain_allow /
verify_allow commands are added to the sessions' permissions. init_project.py writes a first one from the presets. Re-running on an existing
run folder refreshes the scripts and keeps the run's state (ledger, statuses, logs, briefs) and its settings: loop.conf,
hand edits included, changes only by the KEY=VALUEs passed. A rendered template the run edited by hand (runbook.md,
settings.json) is kept, and the new render is written beside it as <name>.new.
"""
import hashlib, json, os, re, shlex, shutil, subprocess, sys

KIT = os.path.dirname(os.path.abspath(__file__))
WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"


def digest(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sh(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def fwd(p):
    return os.path.abspath(p).replace("\\", "/")


def ram_gb():
    try:
        if MAC:
            return int(sh("sysctl", "-n", "hw.memsize")) // 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 2**30
    except (ValueError, OSError, AttributeError):
        return None


def read_conf(path):
    """A run's current settings from its loop.conf (the file the shell scripts read, hand edits included)."""
    conf = {}
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.rstrip("\n"))
            if m:
                conf[m.group(1)] = (shlex.split(m.group(2)) or [""])[0]
    except (OSError, ValueError):
        pass
    return conf


def platform_defaults():
    """What differs by machine. Windows keeps the values the kit always had."""
    if WINDOWS:
        return {}
    ram = ram_gb()
    return {
        "PYTHON": "python3" if shutil.which("python3") else "python",   # macOS has no `python`
        "CHROME": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" if MAC
                  else (shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"),
        # a full build and test run per chain: about 8 GB of memory each before the machine swaps
        "MAX_PAR": str(max(1, min(5, ram // 8))) if ram else "3",
    }


def platform_fixups(out_name, text):
    """Windows can't start npx (a .cmd shim) directly as an MCP server: there it goes through `cmd /c`."""
    if out_name == "mcp.json" and WINDOWS:
        d = json.loads(text)
        for server in d["mcpServers"].values():
            if server.get("command") == "npx":
                server["command"], server["args"] = "cmd", ["/c", "npx"] + server["args"]
        text = json.dumps(d, indent=2) + "\n"
    return text


def default_branch():
    """origin's default branch (what PRs target), else main."""
    ref = sh("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return ref.split("/", 1)[1] if ref.startswith("origin/") else "main"


def project_fixups(out_name, text, kind, prof):
    """The project's own commands go into the sessions' allow-lists: chain_allow for fix chains, verify_allow for the
    verify loop. "npm test *" becomes Bash(npm test *); a tool name (mcp__..., Bash(...)) goes in as it is."""
    extra = prof.get("chain_allow" if kind == "fix" else "verify_allow") or []
    if out_name != "settings.json" or not extra:
        return text
    d = json.loads(text)
    allow = d["permissions"]["allow"]
    for e in extra:
        rule = e if e.startswith(("Bash(", "mcp__")) or re.fullmatch(r"[A-Z]\w*(\(.*\))?", e) else f"Bash({e})"
        if rule not in allow:
            allow.append(rule)
    return json.dumps(d, indent=2) + "\n"


def write(path, text):
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    if path.endswith((".sh", ".py")):  # a fresh file has no exec bit, and ./preflight.sh must run on macOS too
        os.chmod(path, 0o755)


DEFAULTS = {
    # every model call in the loop: pinned, verified by the preflight and by the context guard on every tool call.
    # Two pins: code (build sessions, and the verify loop) and plan (a design branch's sessions until its sign-off)
    "MODEL": "claude-opus-5-5",            # canonical id the guard checks
    "MODEL_ARG": "claude-opus-5-5[1m]",    # what claude -p is given (1M window)
    "EFFORT": "high",                       # the verify loop's default is xhigh (KIND_DEFAULTS)
    "PLAN_MODEL": "claude-opus-5-5",
    "PLAN_MODEL_ARG": "claude-opus-5-5[1m]",
    "PLAN_EFFORT": "xhigh",
    "CTX_WINDOW": "1000000",
    "SOFT_PCT": "65",                       # hand-off
    "HARD_PCT": "72",                       # forced stop; must stay below the 75% ceiling
    "BUDGET_PER_SESSION": "150",            # USD, a runaway guard, not a forecast
    "MAX_SESSIONS": "10",                   # per chain (fix) / per invocation (verify: raise it)
    "MAX_PAR": "5",                         # fix chains at once
    "BASE": "",                             # empty: the repository's default branch (origin/HEAD)
    "BRANCH_PREFIX": "ai-work/",
    "SLUG_PREFIX": "",                      # e.g. "qb-fix-" -> ai-work/qb-fix-<slug>
    "OWNER": "the owner",                   # the human whose decisions the loop waits for (name them)
    # fix runs: who plans. egm = Google's Elephant-Goldfish Model designs and reviews (brainstorm, draft, Goldfish review),
    # egm_plan.py turns the approved design into the plan's branches; grill = grilling rounds on the plan page
    "PLANNER": "egm",
    "PYTHON": "python",                     # the interpreter every script, hook and allow-list entry names
    # gate: tests that fail only under shared load / on this platform's checkout; each must still pass when run alone
    "KNOWN_FLAKES": "",                     # comma-separated test names, as the test runner prints a failure
    # gate: tests that fail on this platform EVERY time and pass on CI (Linux): reported, not counted, never re-run alone
    "KNOWN_PLATFORM_FAILURES": "",
    # gate: steps NOT run on this machine (names from project.json gate.steps), only ever on the owner's explicit decision
    # (doctor.py says when one is needed); the verdict and every PR body name them, with the step's "skippable" note
    "GATE_SKIP": "",
    # the project profile: how this project builds, tests and serves (relative to the repo, or absolute)
    "PROJECT": ".metaloop/project.json",
    # where design chains put mockups and schema-change pages, each folder with a README registry of its pages
    # (empty: the profile's docs.mockups / docs.schema, else docs/mockups and docs/schema-changes)
    "MOCKUPS_DIR": "",
    "SCHEMA_DIR": "",
    # live pages: with no chain event, the watcher still wakes the main session this often (minutes) when a chain's state
    # changed, so progress reaches each chain's live page; anything that needs the owner wakes it at once. 0 = never
    "LIVE_SYNC_MIN": "10",
    "SIGN_TOOL": "Claude Code",
    "SIGN_MODEL": "Opus 5.5",
    # verify loop
    "APP_URL": "",                          # empty: the project profile's verify.url
    "CDP_PORT": "9333",
    "CHROME": "/c/Program Files/Google/Chrome/Application/chrome.exe",
    "START_SERVER": "1",                    # 1 = the loop starts the app (project.json verify) from VERIFY_WORKTREE
    "PAUSE_FOR": "a sign-in that needs a person (OAuth consent, MFA, captcha)",
    # verify: capabilities this machine has beyond what the loop detects (and project.json verify.provides), for tests
    # with a `Requires:` line
    "HAVE_CAPS": "",
}
# per kind of run: the verify loop drives the live app in long browser sessions, where care is worth the extra effort
KIND_DEFAULTS = {"verify": {"EFFORT": "xhigh"}}


def main(a):
    if len(a) < 2 or a[0] not in ("verify", "fix"):
        print(__doc__); sys.exit(2)
    kind, run = a[0], fwd(a[1])
    over = dict(x.split("=", 1) for x in a[2:])
    # The MAIN checkout (the common .git's parent), not whichever worktree this runs in: worktrees get retired.
    common = sh("git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    repo = fwd(os.path.dirname(common) if common.endswith(".git") else (sh("git", "rev-parse", "--show-toplevel") or os.getcwd()))
    conf = dict(DEFAULTS)
    conf.update(platform_defaults())
    conf.update(KIND_DEFAULTS.get(kind, {}))
    conf.update(REPO=repo, RUN_NAME=os.path.basename(run))
    conf["WT_ROOT"] = fwd(os.path.join(os.path.dirname(run), conf["RUN_NAME"] + "-wt"))  # short paths: Windows MAX_PATH
    conf["VERIFY_WORKTREE"] = fwd(os.path.join(os.path.dirname(run), conf["RUN_NAME"] + "-target"))
    # A re-run keeps every setting the run already has, hand edits to loop.conf included, and changes only the KEY=VALUEs
    # passed now. (A kit default that changed since reaches an existing run only when it is passed.)
    conf.update(read_conf(os.path.join(run, "loop.conf")))
    conf.update(KIND=kind, RUN=run, KIT=fwd(KIT))
    conf.update(over)
    if not conf.get("BASE"):
        conf["BASE"] = default_branch()
    prof_path = conf["PROJECT"] if os.path.isabs(conf["PROJECT"]) else os.path.join(repo, conf["PROJECT"])
    try:
        prof_text = open(prof_path, encoding="utf-8").read()
        prof = json.loads(prof_text)
    except FileNotFoundError:
        prof, prof_text = {}, ""
        print(f"note: no project profile at {prof_path}: doctor.py will block the run until there is one "
              f"(write it with {conf.get('PYTHON', 'python')} {fwd(KIT)}/init_project.py --stack <stack>)")
    except ValueError as e:
        sys.exit(f"{prof_path} is not valid JSON: {e}")
    docs = prof.get("docs") or {}
    conf["MOCKUPS_DIR"] = conf.get("MOCKUPS_DIR") or docs.get("mockups") or "docs/mockups"
    conf["SCHEMA_DIR"] = conf.get("SCHEMA_DIR") or docs.get("schema") or "docs/schema-changes"
    if not conf.get("APP_URL"):
        conf["APP_URL"] = (prof.get("verify") or {}).get("url") or "http://localhost:3000"
    if not conf.get("GH_REPO"):
        conf["GH_REPO"] = sh("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    if not conf.get("GH_LOGIN"):
        conf["GH_LOGIN"] = sh("gh", "api", "user", "-q", ".login")
    if not conf["GH_REPO"]:
        sys.exit("gh could not name the repository (gh auth status?); pass GH_REPO=owner/name")
    if not (0 < float(conf["SOFT_PCT"]) < float(conf["HARD_PCT"]) < 75):
        sys.exit("thresholds must satisfy 0 < SOFT_PCT < HARD_PCT < 75")

    os.makedirs(os.path.join(run, "state"), exist_ok=True)
    marks = os.path.join(run, "state", "rendered.json")  # hash of each template's last render, to tell hand edits apart
    try:
        rendered = json.load(open(marks, encoding="utf-8"))
    except (OSError, ValueError):
        rendered = {}
    kept = []
    for sub in ("common", kind):
        src = os.path.join(KIT, sub)
        for name in os.listdir(src):
            p = os.path.join(src, name)
            if os.path.isdir(p) or name.startswith("__"):
                continue
            if name.endswith(".template"):
                out_name = name[: -len(".template")]
                out = os.path.join(run, out_name)
                text = open(p, encoding="utf-8").read()
                text = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: conf.get(m.group(1), m.group(0)), text)
                left = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text)))
                if left:
                    sys.exit(f"{name}: no value for {left}")
                text = project_fixups(out_name, platform_fixups(out_name, text), kind, prof)
                # A render the run has edited by hand (the runbook usually is) is kept: the new render goes beside it.
                if os.path.exists(out) and digest(open(out, encoding="utf-8").read()) not in (rendered.get(out_name), digest(text)):
                    write(out + ".new", text)
                    kept.append(out_name)
                else:
                    write(out, text)
                    rendered[out_name] = digest(text)
            elif ".example" in name:  # starting points the run owns: copied once, never overwritten
                dst = os.path.join(run, name)
                if not os.path.exists(dst):
                    write(dst, open(p, encoding="utf-8").read())
            elif name.endswith((".sh", ".py", ".ps1", ".json", ".md")):
                # LF always: a CRLF checkout (core.autocrlf) would break every shell script under Git Bash
                write(os.path.join(run, name), open(p, encoding="utf-8").read())
            else:
                shutil.copy(p, os.path.join(run, name))
    if prof:
        write(os.path.join(run, "project.json"), prof_text)  # the repo's file as it is
    for d in ("logs", "state", "handoffs", "live") + (("briefs", "replies", "locks") if kind == "fix" else ("tests", "guide", "evidence")):
        os.makedirs(os.path.join(run, d), exist_ok=True)
    with open(os.path.join(run, "loop.conf"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# Written by init_run.py; sourced by the loop scripts. Edit here or re-run init_run.py with KEY=VALUE "
                "(a re-run keeps every setting here, hand edits included, and changes only what it is passed).\n")
        for k, v in sorted(conf.items()):
            f.write(f"{k}={shlex.quote(v)}\n")  # a value with a quote or $ must not break (or run inside) the sourced file
    json.dump(conf, open(os.path.join(run, "loop.json"), "w", encoding="utf-8"), indent=1)
    json.dump(rendered, open(marks, "w", encoding="utf-8"), indent=1)
    for name in kept:
        print(f"KEPT your edited {name}; the kit's current render is {name}.new: diff the two and merge what you need")
    if kind == "fix":
        exclude = os.path.join(sh("git", "rev-parse", "--git-common-dir") or ".git", "info", "exclude")
        try:
            lines = open(exclude, encoding="utf-8").read().splitlines() if os.path.exists(exclude) else []
            if ".fixloop/" not in lines:
                open(exclude, "a", encoding="utf-8").write("\n.fixloop/\n")
        except OSError:
            print("note: add .fixloop/ to .git/info/exclude yourself")
    print(f"{kind} run ready in {run}")
    print(f"next: {conf['PYTHON']} {run}/doctor.py (what this machine is missing, and the way out for each); read the kit "
          "README section for this kind; then " +
          (f"write tests/*.md and run {conf['PYTHON']} init_ledger.py" if kind == "verify"
           else (f"design it with EGM (/egm:egm-brainstorm, /egm:egm-draft, /egm:egm-review) and merge the approved "
                 f"design, then {conf['PYTHON']} egm_plan.py import <design> plan.json, draw up the branches, "
                 f"{conf['PYTHON']} egm_plan.py check plan.json, review the fan-out (reference/egm.md), "
                 f"sign it off on its page ({conf['PYTHON']} plan_page.py, {conf['PYTHON']} sign_plan.py), "
                 f"then {conf['PYTHON']} make_briefs.py plan.json" if conf.get("PLANNER", "egm") == "egm"
                 else f"grill the plan onto its page ({conf['PYTHON']} plan_page.py), sign it off ({conf['PYTHON']} "
                      f"sign_plan.py), then {conf['PYTHON']} make_briefs.py plan.json")))


if __name__ == "__main__":
    main(sys.argv[1:])
