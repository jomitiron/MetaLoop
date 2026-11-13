"""The hand-off from EGM (Google's Elephant-Goldfish Model) to the fix loop: an approved EGM design doc becomes the plan the
orchestrator fans out into parallel chains, and the fan-out is checked before anyone signs it off.

  python egm_plan.py import   <design.md> plan.json [--as-decisions]   the design's goals, journeys, files and checks
  python egm_plan.py check    plan.json                                 is the fan-out sound? (sign_plan.py runs it too)
  python egm_plan.py render   plan.json fanout.md                       the fan-out as a document, for the Goldfish review
  python egm_plan.py boundary plan.json <slug>                          what a chain changed outside its files

Every command takes --repo DIR and --base BRANCH (default: REPO and BASE from loop.json beside this script).

EGM plans (brainstorm, draft, review, resolve: the design doc's Detailed Implementation Plan lists every file to create or
change and how to verify it). The orchestrator then draws the plan's branches from it, as for any fix run, each with:
  "files":      the design's files this branch creates or changes (its binding boundary; a design glob covers a match)
  "cujs":       the design's journeys it delivers ("CUJ1", ...)
  "depends_on": slugs it builds on, which must be in an earlier wave
and its tasks, each with the test that proves it. `check` refuses until every design file has an owner, no two branches
of a wave own the same file, every journey is delivered, and the design the plan was imported from is the one on
origin/<base> (chains branch from there and read it as their spec).
"""
import argparse, datetime, fnmatch, hashlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def conf():
    try:
        return json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
    except (OSError, ValueError):
        return {}


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True)
    return r.returncode, r.stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------------------- the design doc

PLACEHOLDER = re.compile(r"^\[.*\]$")


def sections(text, level):
    """{lowercased heading: body} for the headings of one level (## or ###), in order."""
    out, name, buf = [], None, []
    mark = "#" * level + " "
    for line in text.splitlines():
        if line.startswith(mark) and not line.startswith(mark + "#"):
            if name is not None:
                out.append((name, "\n".join(buf)))
            name, buf = line[len(mark):].strip(), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        out.append((name, "\n".join(buf)))
    return out


def find(secs, *starts):
    return find_named(secs, *starts)[1]


def find_named(secs, *starts):
    for name, body in secs:
        if any(name.lower().startswith(s) for s in starts):
            return name, body
    return "", ""


def plan_entries(plan):
    """The Detailed Implementation Plan's `#### <n>. \`path\` (Action[, Phase N])` entries, under `### Target Files`
    or under `### Phase <n>: ...` headings, with the ### heading each sits under."""
    entries, group, cur = [], "", None
    for line in plan.splitlines():
        if line.startswith("### "):
            group, cur = line[4:].strip(), None
        elif line.startswith("#### "):
            cur = {"name": line[5:].strip(), "group": group, "body": []}
            entries.append(cur)
        elif cur is not None:
            cur["body"].append(line)
    return [e for e in entries if not e["group"].lower().startswith("verification")]


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def bullets(body):
    """Top-level bullets or numbered items, a continuation line joined to its item."""
    items = []
    for line in strip_comments(body).splitlines():
        m = re.match(r"^(?:[*-]|\d+\.)\s+(.*)$", line)
        if m:
            items.append(m.group(1).strip())
        elif items and line.startswith("  ") and line.strip():
            items[-1] += " " + line.strip()
    return [i for i in items if i and not PLACEHOLDER.match(i) and not re.match(r"^(Goal|Non-Goal) \d+$", i)]


def field(body, label):
    """The text of a `*   **Label**: text` bullet, continuation lines included."""
    for item in bullets(body):
        m = re.match(r"^\*\*" + re.escape(label) + r"\*\*\s*:?\s*(.*)$", item, flags=re.I)
        if m:
            return m.group(1).strip()
    return ""


def parse_design(text):
    text = strip_comments(text)
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "")
    m = re.search(r"\*\*Status:\*\*\s*\[?([A-Za-z ]+?)\]?\s*$", text, flags=re.M)
    status = m.group(1).strip() if m else ""
    top = sections(text, 2)
    questions = []
    for item in bullets(find(top, "open questions")):
        q = re.match(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$", item)
        name, body = (q.group(1), q.group(2)) if q else ("Question", item)
        if body.strip().lower() in ("", "none", "none.") or PLACEHOLDER.match(body.strip()):
            continue
        questions.append({"title": name.strip(), "text": body.strip()})
    cujs = []
    for name, body in sections(find(top, "critical user journeys"), 3):
        m = re.match(r"^CUJ\s*(\d+)\s*:?\s*(.*)$", name, flags=re.I)
        if not m or PLACEHOLDER.match(m.group(2).strip()):
            continue
        cujs.append({"id": f"CUJ{m.group(1)}", "title": m.group(2).strip(),
                     "given": field(body, "Given"), "when": field(body, "When"), "then": field(body, "Then")})
    plan = find(top, "detailed implementation plan")
    files, unpathed = [], []
    for e in plan_entries(plan):
        m = re.match(r"^(?:\d+\.\s*)?`([^`]+)`\s*(?:\(([^)]*)\))?", e["name"])
        if not m:
            unpathed.append(re.sub(r"^\d+\.\s*", "", e["name"]))
            continue
        if PLACEHOLDER.match(m.group(1)):
            continue
        paren = m.group(2) or ""
        action = next((w.capitalize() for w in re.findall(r"[A-Za-z]+", paren)
                       if w.lower() in ("create", "modify", "delete")), "Modify")
        phase = re.search(r"phase\s*(\w+)", paren, flags=re.I) or re.match(r"phase\s*(\w+)", e["group"], flags=re.I)
        body = "\n".join(e["body"])
        f = {"path": m.group(1).strip(), "action": action,
             "scope": field(body, "Type / Scope"), "changes": field(body, "Proposed Changes")}
        if phase:
            f["phase"] = phase.group(1)
        files.append(f)
    verify = bullets(find(sections(plan, 3), "verification plan"))
    # "## Goals" and "## Non-Goals", or one "## Goals & Non-Goals" (or "Goals vs. Non-Goals") with ### subsections
    name, body = find_named(top, "goals")
    if "non" in name.lower():
        sub = sections(body, 3)
        goals, non_goals = bullets(find(sub, "goals", "in-scope")), bullets(find(sub, "non-goals", "out-of-scope"))
    else:
        goals, non_goals = bullets(body), bullets(find(top, "non-goals"))
    return {"title": title, "status": status, "goals": goals, "non_goals": non_goals, "questions": questions,
            "cujs": cujs, "files": files, "unpathed": unpathed, "verify": verify}


# ------------------------------------------------------------------------------------------------------------------ import

def rel_to_repo(path, repo):
    a, r = os.path.realpath(path), os.path.realpath(repo)
    return os.path.relpath(a, r).replace("\\", "/") if (a + os.sep).startswith(r + os.sep) else path.replace("\\", "/")


def cmd_import(a, c):
    data = open(a.design, "rb").read()
    d = parse_design(data.decode("utf8"))
    path = rel_to_repo(a.design, a.repo)
    problems = []
    if d["status"].lower() != "approved":
        problems.append(f"its Status is '{d['status'] or 'missing'}', not Approved: the owner approves the design in EGM "
                        "(after /egm:egm-review and /egm:egm-resolve) before it fans out")
    if not d["files"]:
        problems.append("its Detailed Implementation Plan lists no target files: chains need a file boundary "
                        "(review it with the implementation_readiness Goldfish)")
    if d["questions"] and not a.as_decisions:
        problems.append(f"it has {len(d['questions'])} open question(s) ({'; '.join(q['title'] for q in d['questions'])}): "
                        "settle them in EGM, or pass --as-decisions to put them on the plan page as round 1")
    if problems:
        raise SystemExit(f"{a.design} can't fan out yet: " + "; ".join(problems))
    try:
        plan = json.load(open(a.plan, encoding="utf8"))
    except FileNotFoundError:
        plan = {"title": d["title"], "owner": c.get("OWNER", "the owner"), "defects": [], "decisions": [], "branches": [],
                "signed_off": None}
    digest = sha(data)
    prev = plan.get("design") or {}
    if prev and prev.get("sha256") != digest and plan.get("signed_off"):
        plan["signed_off"] = None
        print(f"the design changed since {plan.get('owner', 'the owner')} signed the plan off: sign-off cleared, "
              "check the branches against it and sign off again")
    gh = c.get("GH_REPO")
    plan["design"] = {"path": path, "sha256": digest, "title": d["title"], "status": d["status"], "planner": "egm",
                      "imported": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "url": f"https://github.com/{gh}/blob/{a.base}/{path}" if gh else ""}
    for k in ("goals", "non_goals", "cujs", "files", "unpathed", "verify"):
        plan[k] = d[k]
    if a.as_decisions:
        have = {x.get("source_question") for x in plan.get("decisions", [])}
        n = max([x.get("n", 0) for x in plan.get("decisions", [])] + [0])
        for q in d["questions"]:
            if q["title"] in have:
                continue
            n += 1
            plan.setdefault("decisions", []).append({
                "n": n, "round": 1, "title": q["title"], "context": q["text"] + f" (open question in {path})",
                "options": [], "recommend": None, "decided": None, "source_question": q["title"]})
    json.dump(plan, open(a.plan, "w", encoding="utf8"), indent=1, ensure_ascii=False)
    print(f"{a.plan}: imported {path} ({d['title']}): {len(d['files'])} files, {len(d['cujs'])} journeys, "
          f"{len(d['verify'])} verification steps" + (f", {len(d['questions'])} open questions as decisions" if a.as_decisions and d["questions"] else ""))
    if d["unpathed"]:
        print(f"warning: {len(d['unpathed'])} plan entries name no single file ({'; '.join(d['unpathed'])}): no branch can own "
              "them, so check refuses until the design lists their exact paths (EGM's readiness standard asks for them)")
    print("next: draw up the branches (files, cujs, depends_on, wave, tasks with tests), then egm_plan.py check")


# ------------------------------------------------------------------------------------------------------------------- check

def owns(branch_file, design_file):
    """A branch owns a design file it names, or a match of a design glob (generated output whose names aren't known)."""
    return branch_file == design_file or ("*" in design_file and fnmatch.fnmatch(branch_file, design_file))


def check(plan, repo, base, fetch=True):
    """The problems that keep this fan-out from being signed off; [] when it is sound."""
    design = plan.get("design")
    if not design:
        return []
    problems = []
    path = design["path"]
    if fetch:  # best effort: a just-merged design PR is on GitHub before it is in origin/<base> here
        try:
            subprocess.run(["git", "-C", repo, "fetch", "-q", "origin", base], capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            pass
    code, on_base = git(repo, "show", f"origin/{base}:{path}")
    if code != 0:
        problems.append(f"the design {path} is not on origin/{base}: chains branch from there and read it as their spec, "
                        "so merge the design's PR first")
    elif sha(on_base) != design["sha256"]:
        problems.append(f"the design on origin/{base} is not the one this plan was imported from: "
                        f"re-run egm_plan.py import {path} and check the branches against it")
    else:
        status = parse_design(on_base.decode("utf8"))["status"]
        if status.lower() != "approved":
            problems.append(f"the design's Status on origin/{base} is '{status}', not Approved")
    problems += [f"the design's plan entry '{u}' names no file: list its exact paths in the design (then review, "
                 "approve and re-import)" for u in plan.get("unpathed", [])]
    branches = plan.get("branches", [])
    if not branches:
        return problems + ["no branches drawn up yet"]
    slugs = {b["slug"]: b for b in branches}
    design_files = [f["path"] for f in plan.get("files", [])]
    owners = {f: [] for f in design_files}
    for b in branches:
        build = b.get("mode", "build") == "build"
        if build and not b.get("files"):
            problems.append(f"branch {b['slug']} names no files: give it its share of the design's files")
        for f in b.get("files", []):
            hits = [d for d in design_files if owns(f, d)]
            if not hits:
                problems.append(f"branch {b['slug']} changes {f}, which the design doesn't list: add it to the design "
                                "(and review again) or take it out of the branch")
            for d in hits:
                if b not in owners[d]:
                    owners[d].append(b)
        for dep in b.get("depends_on", []):
            if dep not in slugs:
                problems.append(f"branch {b['slug']} depends on {dep}, which isn't a branch")
            elif slugs[dep].get("wave", 1) >= b.get("wave", 1):
                problems.append(f"branch {b['slug']} (wave {b.get('wave', 1)}) depends on {dep} (wave "
                                f"{slugs[dep].get('wave', 1)}): a dependency goes in an earlier wave")
    for f, bs in owners.items():
        if not bs:
            problems.append(f"no branch builds {f}")
        for i, x in enumerate(bs):
            for y in bs[i + 1:]:
                if x.get("wave", 1) == y.get("wave", 1):
                    problems.append(f"{f} is in both {x['slug']} and {y['slug']} (wave {x.get('wave', 1)}): branches of a "
                                    "wave run at once, so one file has one owner per wave")
                else:
                    early, late = sorted((x, y), key=lambda b: b.get("wave", 1))
                    if early["slug"] not in late.get("depends_on", []):
                        problems.append(f"{f} is in {early['slug']} and in {late['slug']}, which doesn't depend on it")
    cuj_ids = {j["id"] for j in plan.get("cujs", [])}
    delivered = {j for b in branches for j in b.get("cujs", [])}
    problems += [f"no branch delivers {j}" for j in sorted(cuj_ids - delivered)]
    problems += [f"a branch delivers {j}, which the design doesn't have" for j in sorted(delivered - cuj_ids)]
    return problems


def cmd_check(a, c):
    plan = json.load(open(a.plan, encoding="utf8"))
    if not plan.get("design"):
        print(f"{a.plan} has no EGM design (not imported with egm_plan.py import): nothing to check")
        return
    problems = check(plan, a.repo, a.base, fetch=not a.no_fetch)
    if problems:
        print(f"{a.plan}: the fan-out isn't ready ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    b = plan["branches"]
    waves = sorted({x.get("wave", 1) for x in b})
    print(f"{a.plan}: ok: {len(plan.get('files', []))} files and {len(plan.get('cujs', []))} journeys over {len(b)} "
          f"branches in wave(s) {', '.join(map(str, waves))}; next: egm_plan.py render, the fan-out review, sign-off")


# ------------------------------------------------------------------------------------------------------------------ render

def cmd_render(a, c):
    plan = json.load(open(a.plan, encoding="utf8"))
    d = plan.get("design")
    if not d:
        raise SystemExit(f"{a.plan} has no EGM design: run egm_plan.py import first")
    actions = {f["path"]: f.get("action", "Modify") for f in plan.get("files", [])}
    cujs = {j["id"]: j for j in plan.get("cujs", [])}
    out = [f"# Fan-out plan: {plan.get('title') or d['title']}", "",
           f"*   **Design:** `{d['path']}` ({d['status']}, sha256 {d['sha256'][:12]})",
           f"*   **Owner:** {plan.get('owner', 'the owner')}",
           f"*   **Base:** `{a.base}` (every branch starts from it; a wave starts once the waves it depends on merged)", "",
           "This document splits the approved design into branches that separate sessions build at the same time, each in",
           "its own worktree, with only its brief and the design to go on. Review the split, not the design.", ""]
    if plan.get("goals"):
        out += ["## Goals (from the design)", ""] + [f"*   {g}" for g in plan["goals"]] + [""]
    if plan.get("non_goals"):
        out += ["## Non-Goals (from the design)", ""] + [f"*   {g}" for g in plan["non_goals"]] + [""]
    out += ["## Waves", ""]
    by_wave = {}
    for b in plan.get("branches", []):
        by_wave.setdefault(b.get("wave", 1), []).append(b)
    for w in sorted(by_wave):
        out += [f"### Wave {w}", ""]
        for b in by_wave[w]:
            out += [f"#### `{b['slug']}`: {b.get('title', '')} ({b.get('mode', 'build')})", ""]
            if b.get("scope"):
                out += [f"*   **Scope:** {b['scope']}"]
            out += [f"*   **Files:** " + (", ".join(f"`{f}` ({actions.get(f, 'match')})" for f in b.get("files", [])) or "none")]
            out += [f"*   **Journeys:** " + (", ".join(f"{j} ({cujs[j]['title']})" if j in cujs else j for j in b.get("cujs", [])) or "none")]
            out += [f"*   **Depends on:** " + (", ".join(f"`{x}`" for x in b.get("depends_on", [])) or "nothing")]
            out += ["*   **Tasks:**"] + [f"    *   {t['id']}: {t['text']} (proved by `{t.get('test') or '?'}`)"
                                       for t in b.get("tasks", [])] + [""]
    out += ["## File ownership", "", "| File | Action | Branch (wave) |", "|---|---|---|"]
    for f in plan.get("files", []):
        bs = [b for b in plan.get("branches", []) if any(owns(x, f["path"]) for x in b.get("files", []))]
        out.append(f"| `{f['path']}` | {f.get('action', 'Modify')}{' (phase ' + f['phase'] + ')' if f.get('phase') else ''} | " +
                   (", ".join(f"`{b['slug']}` ({b.get('wave', 1)})" for b in bs) or "**none**") + " |")
    out += ["", "## Journey coverage", "", "| Journey | Delivered by |", "|---|---|"]
    for j in plan.get("cujs", []):
        bs = [b["slug"] for b in plan.get("branches", []) if j["id"] in b.get("cujs", [])]
        out.append(f"| {j['id']}: {j['title']} | " + (", ".join(f"`{s}`" for s in bs) or "**none**") + " |")
    if plan.get("verify"):
        out += ["", "## Verification (from the design)", ""] + [f"*   {v}" for v in plan["verify"]]
    problems = check(plan, a.repo, a.base, fetch=False)
    out += ["", "## Mechanical check", ""] + ([f"*   {p}" for p in problems] or ["*   None: egm_plan.py check passes."])
    open(a.out, "w", encoding="utf8", newline="\n").write("\n".join(out) + "\n")
    print(f"written {a.out}: {len(plan.get('branches', []))} branches, {len(problems)} check problem(s); review it with "
          f"/egm:egm-review-loop (reviewers {HERE}/fanout_readiness.md and implementation_readiness, standard "
          f"{HERE}/fanout-readiness-standard.md, context: the design and the code it names)")


# ---------------------------------------------------------------------------------------------------------------- boundary

def cmd_boundary(a, c):
    plan = json.load(open(a.plan, encoding="utf8"))
    b = next((x for x in plan.get("branches", []) if x["slug"] == a.slug), None)
    if not b:
        raise SystemExit(f"no branch {a.slug} in {a.plan}")
    wt = a.worktree or os.path.join(c.get("WT_ROOT", ""), a.slug)
    code, out = git(wt, "diff", "--name-only", f"origin/{a.base}...HEAD")
    if code != 0:
        raise SystemExit(f"can't diff {wt} against origin/{a.base}")
    changed = [p for p in out.decode("utf8").splitlines() if p and not p.startswith(".fixloop/")]
    inside = [p for p in changed if any(p == f or fnmatch.fnmatch(p, f) for f in b.get("files", []))]
    rest = [p for p in changed if p not in inside]
    tests = [p for p in rest if re.search(r"(^|[/_.-])tests?([/_.-]|$)|Tests?\b|\.test\.|\.spec\.", p)]
    outside = [p for p in rest if p not in tests]
    print(f"{a.slug}: {len(changed)} files changed, {len(inside)} in its boundary")
    if tests:
        print("  tests outside the design's list (expected; check they test this branch):")
        print("".join(f"    {p}\n" for p in tests), end="")
    if outside:
        print("  OUTSIDE the boundary (another branch's file, or one the design missed):")
        print("".join(f"    {p}\n" for p in outside), end="")
        sys.exit(1)


def main(argv):
    c = conf()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=c.get("REPO", "."))
    ap.add_argument("--base", default=c.get("BASE", "develop"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import"); p.add_argument("design"); p.add_argument("plan"); p.add_argument("--as-decisions", action="store_true")
    p = sub.add_parser("check"); p.add_argument("plan"); p.add_argument("--no-fetch", action="store_true")
    p = sub.add_parser("render"); p.add_argument("plan"); p.add_argument("out")
    p = sub.add_parser("boundary"); p.add_argument("plan"); p.add_argument("slug"); p.add_argument("--worktree")
    a = ap.parse_args(argv)
    {"import": cmd_import, "check": cmd_check, "render": cmd_render, "boundary": cmd_boundary}[a.cmd](a, c)


if __name__ == "__main__":
    main(sys.argv[1:])
