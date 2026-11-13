"""Reply to and resolve a PR's review threads item by item: each review item a chain recorded is matched to its threads by
the comment ids in the item's text (chains are told to include them).

  python answer.py <PR> <slug> --map               which threads each item maps to, and open threads no item maps to
  python answer.py <PR> <slug> replies/<PR>.json   {"1": "text", "2": "text", ...}: reply to every thread of each item
                                                   and resolve it (threads.py appends the signature line)

Write each reply from the recorded proposal plus what the chain actually pushed: "Fixed in <sha> (failing test first in
<sha>): ..." or "No change, by <owner>'s decision: <reason>". Check every claim against the branch before posting.
An item whose comment ids are missing maps to NO THREAD: match those threads by their text and reply with threads.py.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))


def main(a):
    if len(a) < 3:
        print(__doc__); sys.exit(2)
    pr, slug, arg = a[0], a[1], a[2]
    reviews = json.load(open(os.path.join(CONF["WT_ROOT"], slug, ".fixloop", "status.json"), encoding="utf8"))["reviews"]
    out = subprocess.run([sys.executable, os.path.join(HERE, "threads.py"), "list", pr], capture_output=True, text=True,
                         encoding="utf8", env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
    threads = re.findall(r"^(PRRT_\S+) (open|RESOLVED) \S+ \S+ #(\d+)", out, re.M)
    by_comment = {cid: (tid, state) for tid, state, cid in threads}
    state_of = {tid: state for tid, state, _ in threads}

    mapping = {}
    for i, r in enumerate(reviews, 1):
        ids = set(re.findall(r"(\d{9,})", r["comment"])) & set(by_comment)
        mapping[i] = sorted(by_comment[c][0] for c in ids)
    used = {t for ts in mapping.values() for t in ts}
    unmapped = [(tid, cid) for tid, st, cid in threads if tid not in used and st == "open"]

    if arg == "--map":
        for i, ts in mapping.items():
            print(i, ts or "NO THREAD", "|", reviews[i - 1]["comment"][:110])
        print("open threads no item maps to:", unmapped or "none")
        return
    replies = json.load(open(arg, encoding="utf8"))
    for k, text in replies.items():
        for tid in mapping.get(int(k), []):
            if state_of.get(tid) == "RESOLVED":
                print(k, tid, "already resolved, skipped"); continue
            for cmd in (["reply", tid, text], ["resolve", tid]):
                r = subprocess.run([sys.executable, os.path.join(HERE, "threads.py"), *cmd], capture_output=True, text=True,
                                   encoding="utf8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                print(k, tid, cmd[0], (r.stdout.strip() or r.stderr.strip())[:120])
                if r.returncode != 0:  # a thread is never resolved without its answer
                    print(k, tid, "REPLY FAILED: left open" if cmd[0] == "reply" else "RESOLVE FAILED: still open"); break
    print("open threads no item maps to:", unmapped or "none")


if __name__ == "__main__":
    main(sys.argv[1:])
