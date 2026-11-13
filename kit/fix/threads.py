"""PR review threads for the MAIN session (chains never post): list, reply, resolve; plus top-level comments.

  python threads.py list PR                    every review thread: id, resolved?, author, path:line, #comment id, first comment
  python threads.py comments PR                top-level PR comments (bot summaries): id, author, first lines
  python threads.py reviews PR                 review bodies longer than a header (bot summaries posted as reviews)
  python threads.py reply THREAD_ID TEXT       reply inside a review thread (the signature line is appended)
  python threads.py resolve THREAD_ID          mark it resolved
  python threads.py comment PR TEXT            a top-level PR comment, e.g. answering a review summary (trailer appended)

Set PYTHONIOENCODING=utf-8 on Windows: bot comments carry emoji the cp1252 console can't print.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
OWNER_REPO = CONF["GH_REPO"]
REPO_OWNER, REPO = OWNER_REPO.split("/")


def pages(text):
    """`gh api --paginate` prints one JSON array per page back to back; join them (a body may itself contain '][')."""
    dec, out, i = json.JSONDecoder(), [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1; continue
        page, i = dec.raw_decode(text, i)
        out += page
    return out


def trailer():
    # Every comment posted through a person's account names the tool, the model and the account it was posted from.
    return f"\n\n— 🤖 {CONF.get('SIGN_TOOL', 'Claude Code')} ({CONF.get('SIGN_MODEL', '')}), via @{CONF.get('GH_LOGIN', '')}"


def signed(text):
    return text if "🤖" in text[-160:] else text.rstrip() + trailer()


def gql(query, **vars):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in vars.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf8")
    if r.returncode:
        raise SystemExit(r.stderr.strip())
    return json.loads(r.stdout)


def threads(pr):
    q = """query($o:String!,$r:String!,$n:Int!,$after:String){repository(owner:$o,name:$r){pullRequest(number:$n){
           reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{
           id isResolved path line comments(first:30){nodes{databaseId author{login} body}}}}}}}"""
    out, after = [], None
    while True:  # every page: a thread past the first 100 must not be silently missed
        page = gql(q, o=REPO_OWNER, r=REPO, n=int(pr), **({"after": after} if after else {}))
        rt = page["data"]["repository"]["pullRequest"]["reviewThreads"]
        out += rt["nodes"]
        if not rt["pageInfo"]["hasNextPage"]:
            return out
        after = rt["pageInfo"]["endCursor"]


def main(a):
    cmd = a[0] if a else "help"
    if cmd == "list":
        for t in threads(a[1]):
            c = t["comments"]["nodes"]
            first = c[0] if c else {}
            print(f"{t['id']} {'RESOLVED' if t['isResolved'] else 'open'} {(first.get('author') or {}).get('login')} "
                  f"{t['path']}:{t['line']} #{first.get('databaseId')} replies={len(c) - 1}")
            print("    " + (first.get("body") or "").replace("\n", " ")[:260])
    elif cmd == "comments":
        r = subprocess.run(["gh", "api", f"repos/{OWNER_REPO}/issues/{a[1]}/comments", "--paginate"],
                           capture_output=True, text=True, encoding="utf8")
        for c in pages(r.stdout):  # --paginate prints one array per page
            print(f"#{c['id']} {c['user']['login']} {c['created_at']}")
            print("    " + c["body"].replace("\n", " ")[:300])
    elif cmd == "reviews":
        r = subprocess.run(["gh", "api", f"repos/{OWNER_REPO}/pulls/{a[1]}/reviews", "--paginate"],
                           capture_output=True, text=True, encoding="utf8")
        for v in pages(r.stdout):
            if len(v.get("body") or "") > 200:
                print(f"#{v['id']} {v['user']['login']} {v['state']}")
                print("    " + v["body"].replace("\n", " ")[:400])
    elif cmd == "reply":
        q = """mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}"""
        gql(q, t=a[1], b=signed(a[2])); print("replied")
    elif cmd == "resolve":
        q = """mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}"""
        gql(q, t=a[1]); print("resolved")
    elif cmd == "comment":
        r = subprocess.run(["gh", "pr", "comment", a[1], "--repo", OWNER_REPO, "--body", signed(a[2])],
                           capture_output=True, text=True, encoding="utf8")
        print(r.stdout.strip() or r.stderr.strip())
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
