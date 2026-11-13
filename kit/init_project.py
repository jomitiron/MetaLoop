"""Write a project's profile, .metaloop/project.json, from the kit's presets: one stack, and any databases or services its
tests and its running app need. Run it from inside the project's repository; commit the result.

  python init_project.py --list
  python init_project.py --stack node --db postgres
  python init_project.py --stack python --db postgres --db redis --via native
  python init_project.py --stack go --db mongodb --out .metaloop/project.json --force

--via docker (default) runs each database in a container (Docker must be running); --via native runs the locally
installed server. Either way the gate gives every test slot its own instance on its own port, and the verify loop keeps
its own between runs (data in ~/.metaloop/<project>/<service>, seeded once by the command you fill in).

Whatever a preset can't know (how this app starts, how its test data is loaded) is left as FILL IN: doctor.py blocks
the run until each one is filled in or deleted. reference/project.md describes every field.
"""
import argparse, json, os, subprocess, sys

KIT = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(KIT, "presets")


def presets(kind):
    d = os.path.join(PRESETS, kind)
    return {f[:-5]: json.load(open(os.path.join(d, f), encoding="utf8")) for f in sorted(os.listdir(d)) if f.endswith(".json")}


def repo_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else os.getcwd()


def compose(stack, dbs, via, name):
    stacks, services = presets("stacks"), presets("services")
    if stack not in stacks:
        raise SystemExit(f"no stack preset {stack!r}: one of {', '.join(stacks)}")
    p = json.loads(json.dumps(stacks[stack]))
    notes = [f"stack: {p.pop('about', stack)}"]
    p["services"], p.setdefault("verify", {})["services"] = {}, {}
    exported = {}
    for db in dbs:
        if db not in services:
            raise SystemExit(f"no service preset {db!r}: one of {', '.join(services)}")
        pre = services[db]
        spec = pre.get("any") or pre.get(via)
        if not spec:
            raise SystemExit(f"{db} has no {via} preset")
        for var in spec.get("env", {}):
            if var in exported:
                notes.append(f"WARNING: {db} and {exported[var]} both export {var}: rename one in services.{db}.env")
            exported[var] = db
        p["services"][db] = spec
        p["verify"]["services"][db] = json.loads(json.dumps(pre.get("verify") or {}).replace("{project}", name))
        notes.append(f"{db}: {pre.get('about', '')}" + ("" if pre.get("any") else f" ({via})"))
    for step in p.get("gate", {}).get("steps", []):
        if step.pop("db", False) and dbs:
            step["services"] = list(dbs)
    if not dbs:
        del p["services"]
        del p["verify"]["services"]
    p.setdefault("verify_allow", [])
    p.setdefault("caps", {})
    return p, notes


def main():
    ap = argparse.ArgumentParser(description="Write .metaloop/project.json from the kit's presets.")
    ap.add_argument("--list", action="store_true", help="list the stack and service presets")
    ap.add_argument("--stack")
    ap.add_argument("--db", action="append", default=[], help="a database or service (repeatable)")
    ap.add_argument("--via", choices=("docker", "native"), default="docker")
    ap.add_argument("--out")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.list or not a.stack:
        for kind in ("stacks", "services"):
            print(f"{kind}:")
            for k, v in presets(kind).items():
                print(f"  {k:12} {v.get('about', '')}")
        if not a.list:
            print("\nusage: init_project.py --stack <stack> [--db <service>]... [--via docker|native]")
        return
    root = repo_root()
    out = a.out or os.path.join(root, ".metaloop", "project.json")
    if os.path.exists(out) and not a.force:
        raise SystemExit(f"{out} exists: edit it, or pass --force to write a new one over it")
    p, notes = compose(a.stack, a.db, a.via, os.path.basename(root) or "project")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf8", newline="\n") as f:
        json.dump(p, f, indent=1, ensure_ascii=False)
        f.write("\n")
    fill = [line for line in json.dumps(p, indent=1).splitlines() if "FILL IN" in line]
    print(f"wrote {out}")
    for n in notes:
        print(f"  {n}")
    if fill:
        print(f"\n{len(fill)} thing(s) to fill in (doctor.py blocks the run until each is filled in or deleted):")
        for line in fill:
            print("  " + line.strip()[:150])
    print("\nnext: check the commands against how this repo really builds and tests, commit the file, then init_run.py")


if __name__ == "__main__":
    main()
