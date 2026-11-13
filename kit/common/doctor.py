"""Checks this machine for everything the run needs BEFORE it starts, and says for each missing piece what the run does
without it and who installs it. What the project itself needs (its language toolchain, its databases and services) comes
from the run's project.json (the project profile), so nothing here is tied to a stack. Run it from the run folder after
init_run.py, and again after every install:

  python3 doctor.py            the report
  python3 doctor.py --json     the same, for the orchestrator

Exit 0: nothing blocks the run. Exit 1: something is missing that the run can't do without, or that it can do without
only with fewer checks, which the owner must approve first.

States:
  ok        present and working
  fallback  missing, and the run does the same checks another way (it says how): no decision needed
  skipped   not checked on this machine, by the owner's decision (GATE_SKIP, START_SERVER=0, PLANNER=grill)
  warn      works, but read the note
  missing   blocks the run until it is installed, or until the owner approves the fewer-checks setting in `ask`

`who` says who installs it: "claude" (the orchestrator may run the command once the owner says yes) or "owner" (it
needs the owner's password, a first launch in a window, an Apple ID, a licence or a sign-in: the owner runs it in their
own terminal). This script installs nothing. Loop sessions never install anything either.
"""
import json, os, platform, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project  # noqa: E402
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
PROFILE = project.load()
KIND, OWNER, REPO = CONF.get("KIND", "fix"), CONF.get("OWNER", "the owner"), CONF.get("REPO", ".")
WIN, MAC = os.name == "nt", sys.platform == "darwin"
SPAWN = {"creationflags": 0x08000000} if WIN else {}  # CREATE_NO_WINDOW
SKIP = {s.strip() for s in CONF.get("GATE_SKIP", "").split(",") if s.strip()}
items = []


def add(name, needed_for, state, detail="", fallback="", install="", who="", ask=""):
    items.append(dict(name=name, state=state, detail=detail, fallback=fallback, install=install, who=who, ask=ask,
                      **{"for": needed_for}))


def run(args, cwd=None, timeout=30):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, **SPAWN)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def brew(formula):
    return f"brew install {formula}" if MAC else ""


def ram_gb():
    try:
        if MAC:
            return int(run(["sysctl", "-n", "hw.memsize"])[1]) // 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 2**30
    except (ValueError, OSError, AttributeError):
        return None


# ---------------------------------------------------------------- every run
def common():
    v = run(["claude", "--version"])
    add("claude CLI", "every session", "ok" if v[0] == 0 else "missing", v[1][:60] if v[0] == 0 else "not on PATH",
        install="npm install -g @anthropic-ai/claude-code; then sign in with `claude`", who="claude")
    add("git", "worktrees, branches", "ok" if shutil.which("git") else "missing",
        install="xcode-select --install (a dialog)" if MAC else "install Git for Windows", who="owner")
    py = CONF.get("PYTHON", "python")
    add("python", "every script and hook", "ok" if shutil.which(py) else "missing",
        f"{py}: Python {platform.python_version()}" if shutil.which(py) else f"loop.conf PYTHON={py} is not on PATH",
        install=f"python3 {CONF.get('KIT', '<kit>')}/init_run.py {KIND} {HERE} PYTHON=python3" if shutil.which("python3")
        else ("xcode-select --install (a dialog)" if MAC else "install Python 3"), who="claude" if shutil.which("python3") else "owner")
    profile()
    have_gh = bool(shutil.which("gh"))
    rc, out = run(["gh", "auth", "status"]) if have_gh else (-1, "not installed")
    if rc == 0:
        add("gh", "PRs, CI, review threads", "ok", f"signed in; repo {CONF.get('GH_REPO')}")
    elif KIND == "verify" and CONF.get("GH_REPO"):
        add("gh", "only init_run.py's repo lookup", "fallback", "not installed" if not have_gh else "not signed in",
            fallback=f"GH_REPO={CONF['GH_REPO']} is set, which is all a verify run needs")
    elif have_gh:
        add("gh", "PRs, CI, review threads", "missing", "not signed in", install="gh auth login (a browser sign-in)", who="owner")
    else:
        add("gh", "PRs, CI, review threads", "missing", "not installed",
            install=(brew("gh") or "winget install GitHub.cli") + "; then gh auth login (a browser sign-in)",
            who="claude, then the owner signs in")
    launcher()
    if MAC:
        batt = run(["pmset", "-g", "batt"])[1]
        add("power", "unattended runs", "warn" if "Battery Power" in batt else "ok",
            "on battery: launch.sh refuses an unattended start until the Mac is plugged in; keep the lid open"
            if "Battery Power" in batt else "on mains power; launch.sh runs the loop under caffeinate; keep the lid open",
            fallback="plug the Mac in" if "Battery Power" in batt else "")
        add("macOS permissions", "notifications; raising the run's Chrome", "ok",
            "the first notification and the first raise_chrome.sh each ask once (System Settings: Notifications; Privacy & "
            "Security > Automation). Without them: a terminal bell, the log line and the watcher; the pause message names the window")
    need = 40 if KIND == "fix" else 15
    free = shutil.disk_usage(os.path.dirname(HERE)).free // 2**30
    add("disk", "worktrees and builds", "ok" if free >= need else "missing", f"{free} GB free (needs about {need} GB)",
        install="free some space: retire.sh --all-runs --apply removes merged PRs' worktrees and their builds",
        who="owner")


# ---------------------------------------------------------------- the project profile (every stack-specific need)
def profile():
    """The project profile says what this project needs; check it, then every tool it names."""
    where = CONF.get("PROJECT", ".metaloop/project.json")
    if not PROFILE:
        return add("project profile", "the gate, the verify server, the project's tools", "missing",
                   f"no {where} in the repository (the run has no project.json)",
                   install=f"{CONF.get('PYTHON', 'python3')} {CONF.get('KIT', '<kit>')}/init_project.py --stack <stack> "
                           f"[--db <service>] in the repo (--list shows the presets), fill in what it marks, commit it, "
                           f"then init_run.py {KIND} {HERE} again", who="claude")
    probs = project.problems(PROFILE, KIND)
    add("project profile", "the gate, the verify server, the project's tools", "missing" if probs else "ok",
        "; ".join(probs)[:400] if probs else f"{where}: " + (f"{len((PROFILE.get('gate') or {}).get('steps') or [])} gate steps"
        if KIND == "fix" else f"serves on {CONF.get('APP_URL')}"),
        install=f"edit {where} in the repository, then init_run.py {KIND} {HERE} again" if probs else "", who="claude")
    for r in project.requirements(PROFILE, KIND):
        tool, steps = r.get("tool", "?"), [x for x in (r.get("skip") or "").split(",") if x]
        if KIND == "verify" and CONF.get("START_SERVER", "1") != "1":  # the app runs elsewhere: nothing to build or serve
            add(tool, r.get("for", ""), "skipped", f"START_SERVER=0: the run uses the app already on {CONF.get('APP_URL')}")
            continue
        if steps and set(steps) <= SKIP:
            add(tool, r.get("for", ""), "skipped", f"not checked on this machine by {OWNER}'s decision (GATE_SKIP={','.join(steps)})")
            continue
        have = run(["bash", "-c", r["check"]], cwd=REPO)[0] == 0 if r.get("check") else bool(shutil.which(tool))
        add(tool, r.get("for", ""), "ok" if have else "missing", "" if have else "not found on this machine",
            fallback=(f"fewer checks, only on {OWNER}'s OK: GATE_SKIP={','.join(steps)} leaves out the gate step(s) that "
                      "need it (the verdict and every PR body say so)") if steps else "",
            install=r.get("install", f"install {tool}"), who=r.get("who", "owner"),
            ask=f"GATE_SKIP={','.join(steps)}" if steps else "")


def launcher():
    if WIN:
        add("mintty", "the loop's window", "ok" if shutil.which("mintty") else "missing", install="use Git Bash (it ships mintty)", who="owner")
    elif shutil.which("tmux"):
        add("tmux", "launch.sh: runs the loop detached", "ok")
    elif shutil.which("screen"):
        add("tmux", "launch.sh: runs the loop detached", "fallback", "not installed",
            fallback="GNU screen (ships with macOS) runs it detached instead (watch: screen -r <name>)", install=brew("tmux"), who="claude")
    else:
        add("tmux", "launch.sh: runs the loop detached", "missing", "neither tmux nor screen", install=brew("tmux"), who="claude")


# ---------------------------------------------------------------- fix runs
def fix():
    if (ram := ram_gb()) is not None:
        rec, par = max(1, min(5, ram // 8)), int(CONF.get("MAX_PAR", "5"))
        add("memory", "parallel chains", "warn" if par > rec else "ok", f"{ram} GB for MAX_PAR={par}" +
            (f": that many full builds at once will swap; use {rec}" if par > rec else ""),
            fallback=f"init_run.py fix {HERE} MAX_PAR={rec}" if par > rec else "")
    try:
        import markdown  # noqa: F401
        add("markdown (Python)", "schema-change pages (md_to_page.py)", "ok")
    except ImportError:
        add("markdown (Python)", "schema-change pages (md_to_page.py)", "warn", "not installed: every other step runs; schema pages wait",
            install=f"{CONF.get('PYTHON', 'python3')} -m pip install --user markdown", who="claude")
    egm()


def egm():
    """PLANNER=egm: the orchestrator designs with Google's EGM plugin (brainstorm, draft, Goldfish review) before the
    fan-out. Only the main session needs it; chains never run EGM."""
    need = "planning (PLANNER=egm): design, Goldfish review, fan-out review"
    if CONF.get("PLANNER", "egm") != "egm":
        add("EGM plugin", need, "skipped", f"PLANNER={CONF.get('PLANNER')}: the plan page's grilling rounds plan this run")
        return
    ids = []
    try:
        r = subprocess.run(["claude", "plugin", "list", "--json"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL, **SPAWN)
        ids = [p.get("id", "") for p in json.loads(r.stdout) if p.get("enabled", True)] if r.returncode == 0 else []
    except (OSError, ValueError, AttributeError, TypeError, subprocess.TimeoutExpired):
        pass
    found = [i for i in ids if i.split("@")[0] == "egm"]
    add("EGM plugin", need, "ok" if found else "missing", found[0] if found else "not installed or not enabled",
        fallback="PLANNER=grill: plan with grilling rounds on the plan page instead (no Goldfish review)",
        install="claude plugin marketplace add google/elephant-goldfish-model && claude plugin install egm@egm "
                "(then start a new session)", who="claude", ask="PLANNER=grill")


# ---------------------------------------------------------------- verify runs
def verify():
    if CONF.get("START_SERVER", "1") == "1" and not (PROFILE.get("verify") or {}).get("start"):
        add("app start command", "the app under test", "missing", "project.json has no verify.start",
            fallback=f"START_SERVER=0: test an app someone runs elsewhere, on {CONF.get('APP_URL')}",
            install="add verify.start (and verify.build, verify.health) to the project profile", who="claude",
            ask="START_SERVER=0")
    chrome = CONF.get("CHROME", "")
    add("Chrome", "the shared browser every session drives", "ok" if os.path.exists(chrome) else "missing",
        chrome if os.path.exists(chrome) else f"CHROME={chrome} doesn't exist",
        fallback=f"Chrome for Testing in the run folder: npx @puppeteer/browsers install chrome@stable --path {HERE}/chrome-bin, "
                 f"then init_run.py verify {HERE} CHROME=<the path it prints>",
        install=brew("--cask google-chrome") or "install Google Chrome", who="claude")
    add("node / npx", "the Chrome DevTools MCP", "ok" if shutil.which("npx") else "missing", install=brew("node") or "install Node.js", who="claude")
    add("curl", "health checks, the Chrome debug port", "ok" if shutil.which("curl") else "missing", install=brew("curl"), who="claude")


def main(a):
    common()
    fix() if KIND == "fix" else verify()
    blocking = [i for i in items if i["state"] == "missing"]
    if "--json" in a:
        print(json.dumps({"kind": KIND, "run": HERE, "ok": not blocking, "items": items}, indent=1))
    else:
        host = f"macOS {platform.mac_ver()[0]}" if MAC else platform.platform()
        print(f"Doctor: {KIND} run '{CONF.get('RUN_NAME')}' on {host} ({platform.machine()})\n")
        for i in items:
            print(f"  {i['state'].upper():9} {i['name']:20} {i['detail']}".rstrip())
            if i["fallback"] and i["state"] != "ok":
                print(f"  {'':9} {'':20} {'instead' if i['state'] == 'fallback' else 'without it'}: {i['fallback']}")
            if i["install"] and i["state"] != "ok":
                print(f"  {'':9} {'':20} install ({i['who']}): {i['install']}")
        print()
        if blocking:
            print(f"BLOCKED by {len(blocking)}: " + "; ".join(i["name"] for i in blocking))
            asks = [i["ask"] for i in blocking if i["ask"]]
            if asks:
                print(f"  {OWNER} may instead approve fewer checks: " + ", ".join(asks) + f" (init_run.py {KIND} {HERE} KEY=VALUE)")
        else:
            print("Nothing blocks the run. Next: ./preflight.sh")
    sys.exit(1 if blocking else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
