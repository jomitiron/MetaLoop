"""Background services a project's checks need (a database, a cache, a queue, a webhook listener), as project.json
"services" declares them. Nothing here knows any particular one: kit/presets/services has Postgres, MySQL, MongoDB,
Redis and SQLite, each in Docker or native, to start from.

The gate starts a fresh instance per test slot for each step that names a service, on `port` + slot, and removes it
after: two chains never share one, so suites with fixed database names can't clobber each other. The verify loop starts
the app's own for the length of the run, with these per-use overrides (project.json verify.services as an object):
  persist   a folder for {dir} that is kept between runs (data survives, as a container's volume would)
  seed      a command run once, when the persist folder is new (load the test data the app's sign-in needs)
  reuse     true: an instance already answering `ready` is used as it is, never started twice

  python services.py up [--for verify] [--state DIR] [NAME...]   start (or reuse); export lines on stdout
  python services.py env [--state DIR]                          export lines for what `up` started
  python services.py down [--state DIR]                         stop what `up` started (persist folders are kept)

A service's lifecycle: `start` (left running in the background, its output in logs/service-<name>.log), wait for `up`
(default: `ready`), run `init` once, wait for `ready`, then `seed` on a new persist folder. Stopping runs `stop` and
then ends whatever `start` left running. Every check is a command that exits 0 when true, under bash.
"""
import json, os, shlex, shutil, signal, socket, subprocess, sys, tempfile, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project  # noqa: E402

WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000
SPAWN = {"creationflags": NO_WINDOW} if WINDOWS else {}
BASH = shutil.which("bash") or "bash"
MARKER = ".metaloop-ready"  # in a persist folder: started (and seeded) once already


class ServiceError(Exception):
    pass


def listening(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def sh(cmd, timeout=30, env=None, cwd=None):
    try:
        r = subprocess.run([BASH, "-c", cmd], capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
                           stdin=subprocess.DEVNULL, **SPAWN)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def kill_group(pid):
    if not pid:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(int(pid), sig)
        except (OSError, ValueError):
            return
        for _ in range(20):
            try:
                os.killpg(int(pid), 0)
            except OSError:
                return
            time.sleep(0.5)


class Service:
    """One instance of one service. Use as a context manager (the gate) or start()/stop() (the verify loop)."""

    def __init__(self, name, spec, slot=0, state=None, logs=None, run=None, root=None, record=None):
        self.name, self.spec, self.slot = name, spec, slot
        self.state = state or tempfile.gettempdir()
        self.logs = logs or self.state
        self.vars = dict(slot=slot, run=run or "", root=root or "", id=f"{name}-{slot}-{uuid.uuid4().hex[:8]}",
                         port=int(spec["port"]) + slot if spec.get("port") else None, dir=None)
        self.pid, self.started, self.reused, self.temp_dir, self.proc = None, False, False, None, None
        self.last_check = None  # (key, rc, output) of the latest up/ready check, for the error when it never passes
        if record:  # rebuilt from services.json, to stop it
            self.vars.update(record["vars"])
            self.pid, self.started, self.temp_dir = record.get("pid"), record.get("started"), record.get("temp_dir")
            self.reused = record.get("reused", False)

    def cmd(self, key):
        return project.fill(self.spec[key], **self.vars) if self.spec.get(key) else ""

    def check(self, key, timeout=20):
        c = self.cmd(key)
        if not c:
            return False
        rc, out = sh(c, timeout=timeout, cwd=self.vars["dir"] or None)
        self.last_check = (key, rc, out)
        return rc == 0

    def wait(self, key, secs):
        end = time.time() + secs
        while time.time() < end:
            # a check that hangs (a port that accepts and never answers) must not outlast the wait itself
            if self.check(key, timeout=max(1, min(20, end - time.time()))):
                return True
            rc = self.proc.poll() if self.proc else None
            if rc not in (None, 0):  # it died; exit 0 is a start command that daemonised, so keep waiting
                raise ServiceError(f"{self.name}'s start command exited {rc}: {self.log_tail()}")
            time.sleep(1)
        return False

    def why_not(self):
        """What a service that never came up looked like: the last check, the port, the start command, its log."""
        bits = []
        if self.last_check:
            key, rc, out = self.last_check
            bits.append(f"its {key} check last exited {rc}" + (f" ({out[-200:]})" if out else ""))
        if self.vars["port"]:
            bits.append(f"port {self.vars['port']} " + ("accepts connections" if listening(self.vars["port"]) else "is not open"))
        if self.proc:
            rc = self.proc.poll()
            bits.append("the start command is still running" if rc is None else f"the start command exited {rc}")
        bits.append(f"log: {self.log_tail()}")
        return "; ".join(bits)

    def log_tail(self):
        try:
            lines = open(os.path.join(self.logs, f"service-{self.name}.log"), encoding="utf8", errors="replace").read().strip().splitlines()
            return " | ".join(lines[-3:])[-400:] or "(no output)"
        except OSError:
            return "(no log)"

    def env(self):
        return {k: project.fill(str(v), **self.vars) for k, v in (self.spec.get("env") or {}).items()}

    def start(self):
        spec, timeout = self.spec, int(self.spec.get("timeout", 60))
        persist = spec.get("persist")
        self.vars["dir"] = os.path.abspath(os.path.expanduser(persist)) if persist else None
        if spec.get("reuse") and spec.get("ready"):
            if self.vars["dir"] is None:
                self.vars["dir"] = self.state
            if self.check("ready"):
                self.reused = True
                return self.env()
        if self.vars["port"] and listening(self.vars["port"]):
            raise ServiceError(f"{self.name}: port {self.vars['port']} is already taken by another program: give the "
                               f"service another port in project.json (services.{self.name}.port)")
        new = False
        if persist:  # new until a start has finished (seed included): a container's data lives in a volume, not here
            new = not os.path.exists(os.path.join(self.vars["dir"], MARKER))
            os.makedirs(self.vars["dir"], exist_ok=True)
        else:
            os.makedirs(self.state, exist_ok=True)
            self.vars["dir"] = self.temp_dir = tempfile.mkdtemp(prefix=f"svc-{self.name}-", dir=self.state)
        try:
            if spec.get("start"):
                os.makedirs(self.logs, exist_ok=True)
                log = open(os.path.join(self.logs, f"service-{self.name}.log"), "a", encoding="utf8")
                detach = {"creationflags": NO_WINDOW | 0x00000200} if WINDOWS else {"start_new_session": True}
                self.proc = subprocess.Popen([BASH, "-c", self.cmd("start")], stdout=log, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, cwd=self.vars["dir"], **detach)
                self.pid = self.proc.pid
                self.started = True
            if spec.get("ready"):
                if not self.wait("up" if spec.get("up") else "ready", timeout):
                    raise ServiceError(f"{self.name} did not come up within {timeout}s: {self.why_not()}")
                if spec.get("init"):
                    rc, out = sh(self.cmd("init"), timeout=timeout, cwd=self.vars["dir"])
                    if rc != 0:
                        raise ServiceError(f"{self.name}: init failed: {out[-300:]}")
                    if not self.wait("ready", timeout):
                        raise ServiceError(f"{self.name} was initialised but never became ready within {timeout}s: "
                                           f"{self.why_not()}")
            if new and spec.get("seed"):
                env = dict(os.environ, **self.env())
                root = self.vars["root"]  # the app's checkout, where its migrations and seed scripts live
                rc, out = sh(self.cmd("seed"), timeout=int(spec.get("seed_timeout", 600)), env=env,
                             cwd=root if root and os.path.isdir(root) else self.vars["dir"])
                if rc != 0:
                    raise ServiceError(f"{self.name}: seeding the new data in {self.vars['dir']} failed: {out[-300:]}")
        except BaseException:
            self.stop()
            if new and persist and not spec.get("start", "").lstrip().startswith("docker"):
                shutil.rmtree(self.vars["dir"], ignore_errors=True)  # half-made data would never be seeded again
            raise
        if persist:
            open(os.path.join(self.vars["dir"], MARKER), "w").write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
        return self.env()

    def stop(self):
        if self.reused:
            return
        if self.started and self.spec.get("stop"):
            sh(self.cmd("stop"), timeout=60, cwd=self.vars["dir"] if self.vars["dir"] and os.path.isdir(self.vars["dir"]) else None)
        kill_group(self.pid)
        self.pid = None
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def record(self):
        return {"name": self.name, "vars": self.vars, "pid": self.pid, "started": self.started,
                "temp_dir": self.temp_dir, "reused": self.reused}

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()


# ---------------------------------------------------------------------------------------------- the verify loop's CLI

def records_path(state):
    return os.path.join(state, "services.json")


def exports(env):
    return "\n".join(f"export {k}={shlex.quote(v)}" for k, v in env.items())


def main(a):
    if not a or a[0] not in ("up", "env", "down"):
        print(__doc__); sys.exit(2)
    cmd, use, state, names = a[0], None, os.path.join(HERE, "state"), []
    i = 1
    while i < len(a):
        if a[i] == "--for":
            use, i = a[i + 1], i + 2
        elif a[i] == "--state":
            state, i = os.path.abspath(a[i + 1]), i + 2
        else:
            names.append(a[i]); i += 1
    p = project.load()
    conf = {}
    try:
        conf = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
    except (OSError, ValueError):
        pass
    try:
        recs = json.load(open(records_path(state), encoding="utf8"))
    except (OSError, ValueError):
        recs = []
    if cmd == "up":
        names = names or (project.verify_services(p) if use == "verify" else [])
        env, out = {}, []
        for n in names:
            spec = project.service_spec(p, n, use)
            if not spec:
                sys.exit(f"FAIL: no service {n} in project.json")
            s = Service(n, spec, state=state, logs=os.path.join(HERE, "logs"), run=HERE, root=conf.get("VERIFY_WORKTREE"))
            try:
                env.update(s.start())
            except ServiceError as e:
                for r in out:
                    Service(r["name"], project.service_spec(p, r["name"], use), record=r).stop()
                sys.exit(f"FAIL: {e}")
            out.append(s.record())
            print(f"# {n}: {'reusing the one already running' if s.reused else 'started'}"
                  + (f" on :{s.vars['port']}" if s.vars["port"] else "") + (f", data in {s.vars['dir']}" if spec.get("persist") else ""),
                  file=sys.stderr)
        os.makedirs(state, exist_ok=True)
        json.dump(out, open(records_path(state), "w", encoding="utf8"), indent=1)
        json.dump(env, open(os.path.join(state, "services.env.json"), "w", encoding="utf8"), indent=1)
        print(exports(env))
    elif cmd == "env":
        try:
            print(exports(json.load(open(os.path.join(state, "services.env.json"), encoding="utf8"))))
        except (OSError, ValueError):
            pass
    else:
        for r in recs:
            Service(r["name"], project.service_spec(p, r["name"], use or "verify"), record=r).stop()
        for f in (records_path(state), os.path.join(state, "services.env.json")):
            if os.path.exists(f):
                os.remove(f)


if __name__ == "__main__":
    main(sys.argv[1:])
