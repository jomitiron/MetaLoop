# The orchestrator's procedures

Everything the main session does, in the order it comes up. Commands run from the fix run folder unless noted.

## Watching (always)

- Every long process gets a background watcher the moment it starts, re-armed after every event: `wait_verify.sh`,
  `wait_chain.sh`, `wait_gate.sh <slug>`, `wait_ci.sh <PR>...`. Use the harness's background tasks, never `nohup ... &`
  (an untracked job never tells you it finished). One watcher per item you will act on separately: a combined watcher
  delays the first push until the slowest is done.
- Launch loops with `<run>/launch.sh` (a minimised mintty window on Windows, a detached tmux session under caffeinate
  on macOS), never a window that grabs focus: it takes the owner's keystrokes. On macOS, tell the owner how to watch it
  (`tmux attach -t <name>`, leave with Ctrl-b d).
- When you've been quiet a while, say in a line what you're doing.
- Every time a watcher returns, before anything else: sync the live pages and post the attention lines ("Live Pages"
  below). The chat never carries a chain's question itself, only its link.

## Missing dependencies (set-up, before the first start)

`doctor.py` in the run folder checks the machine; nothing is installed without the owner's yes, and never mid-run.

1. Run it (`--json` for the details). Items: **ok**; **fallback** (the same checks another way: tell the owner in a
   line, no decision); **skipped** (already the owner's decision); **warn** (read the
   note: on battery, data in a temp folder, too many chains for the memory); **missing** (blocks the start).
2. For each missing item:
   - `who: claude`: batch them into ONE question (install all as listed, recommended / leave one out and take its
     fallback, which the question names / stop). On a yes, run exactly the listed commands, then re-run the doctor.
   - `who: owner` (a password, a first launch in a window, an Apple ID, a licence, a sign-in): give the exact commands
     in one block to run in their own terminal; never run sudo, accept a licence or sign in for them. Re-run the doctor
     when they say it's done.
   - An `ask` (`GATE_SKIP=<step>`, `START_SERVER=0`, `PLANNER=grill`): fewer checks, so only on the owner's explicit
     decision, with what it costs in the question (e.g. "CI's integration job runs that suite instead"; "the loop tests
     the app someone else runs"). Recommend installing over skipping when the install is the owner's to do once. On a yes: `init_run.py ...
     KEY=VALUE`, and a dated line in the runbook's hard rules.
3. Start only when the doctor exits 0 and `./preflight.sh` prints `ok` (a fix run with design branches: `./preflight.sh
   plan` too).
4. Mid-run, a service the run started that stops (Docker, a database server, the run's Chrome) shows as its own state
   ("postgres did not come up", "the run's Chrome is not running"), not as test failures: restart it (it is already
   installed and local) and requeue. Anything new to install goes back through step 2.

## Planning (Every Fix Run)

With `PLANNER=egm` (the default) EGM designs the work and the orchestrator fans the approved design out:
[egm.md](egm.md) has that procedure. Steps 1 to 3 below (verify, investigate, classify) come first either way and feed
EGM's brainstorm; steps 4 and 5 (grilling rounds, drawing up the plan) are the `PLANNER=grill` way; step 6 (sign-off)
applies to both.

Plan on the plan pin (`PLAN_MODEL` at `PLAN_EFFORT`, default Opus 5.5 at xhigh): set this session to it (`/model`,
`/effort`) before triage, and start the investigation agents on it. Switch back to the owner's choice once the plan is
signed off. A run that starts from a list of tickets instead of a verify run plans the same way: no chain starts before
`sign_plan.py`.

1. **Verify before escalating.** A defect a loop session drafted is a lead, not a finding: read the later sessions' notes
   and the code before calling it a bug, and never "restore" data on the strength of one session's guess.
2. **Investigate by area** with parallel read-only agents (this skill directs them), each writing its
   findings with file:line evidence to a file.
3. **Classify each defect:** BUG (fix it), DECISION (the owner chooses the behaviour), GUIDE (the test plan is wrong). Give
   each a gate: none, decision, mockup (any pixel a user sees changes), schema (any stored field, collection or index
   changes; fields never stored need no page).
4. **Grill, in rounds, on the plan page** (the `grilling` skill). The decisions form a tree; a
   round is its frontier: every question whose prerequisites are settled, each a `decisions` entry with `round`, a short
   `title` (Every Word Capitalized), `context` (what happened, with real ids from the run, and where in the process it
   bites), `options` and the `recommend`ed one. Group questions by situation: one situation is one question whose
   options are whole outcomes. A choice with one sensible answer is stated as the plan, not asked. Facts are yours to
   find (dispatch a read-only agent); only decisions go to the owner.
   - `plan_page.py plan.json plan.html "<Title>"`, publish to the same URL each round, and post one line in the chat:
     "Round N is ready: <k> questions → <link>". The page's "Send This Round To Claude" wakes you.
   - Read the answers: `ArtifactData` list, collection `answers` (doc ids `d<n>`). Record each as the decision's
     `"decided"` (a note can amend the option; keep its words). Write a reply in `replies/d<n>` when an answer needs one.
   - the `domain-modeling` skill as the answers land: each decision worth keeping goes into
     the feature's decisions log as a D-numbered entry; each term the owner settled goes into `docs/glossary.md`.
   - Recompute the frontier and publish the next round, until it is empty: nothing left silently assumed.
5. **Draw up the plan** on the same page: branches by wave (wave 1 = no gate, wave 2 = mockup-gated, wave 3 =
   schema-gated; a branch that depends on another waits for it), each with a `title`, its binding `scope` and its
   `tasks`: every outcome the branch delivers, each with the test that proves it (a design branch's tasks are what its
   page must show). A branch with no tasks is not planned yet.
6. **Sign-off.** The page's Sign Off button (collection `signoff`, doc `plan`) or the owner's own words; never a bare
   "done" with nothing answered. Then `sign_plan.py plan.json "<when>" "<who>"`: it refuses while a decision is open or
   a branch has no tasks, and `make_briefs.py` refuses until it has run.

## Decisions After The Plan

- A question that comes up mid-run and isn't a chain's goes on the plan page as a new round, never into a pop-up.
- A follow-up that changes a branch's scope goes into that branch's brief or a note before it starts.
- Reply on each comment thread with what you recorded, then resolve it. A thread that was already answered once needs
  `acknowledge_duplicate` for a reply that adds a new decision.
- Record every decision in the plan (`"decided"`), the feature's decisions log in the repo when the branch ships, and
  memory when it is a standing rule.

## Live Pages

Every chain, and the verify loop, has a live page: the owner's one place to see it, answer it and ask it things. The main
window carries none of that conversation. A message there scrolls away; the page keeps an unanswered question on top.

1. **Publish before the start.** `live_page.py <slug> ...` (the verify run: `live_page.py verify`) writes
   `live/<slug>.live.html` in the run folder and prints the capabilities. Publish each with the Artifact tool (that
   file, those capabilities, icon `pulse`), then `live_page.py --url <slug> <url>`. Never copy a page into the repo:
   `*.live.html` is ignored, and the pages hold run state.
2. **Sync whenever a watcher returns.** `live_sync.py --all` prints each page's pending writes; write them with
   `ArtifactData` (action `batch`, the page's url, up to 50 per call, in order), then `live_sync.py --all --done`. Every
   write creates a document, so no versions are needed. Nothing reaches a page you don't write.
3. **Post the attention lines.** `live_sync.py --attention` prints one line per thing a page needs the owner for
   ("Needs you · <slug>: <one line> → <link>", "Ready · <slug>: ... → <link>"). Post exactly those, and post them again
   in every status update until each is answered.
4. **Relay what the owner does on a page.** Only the owner can write a page's answers, approvals and sign-off (the
   capabilities the scripts print make them owner-only); anyone the page is shared with can read it and Ask Claude. A Send to Claude from a page wakes you; otherwise read the page's
   `answers` and `approvals` when you sync. An answer to a chain's question: `task.py answer Q1 "<answer>"` in its
   worktree, and if the chain stopped holding its PR, `task.py requeue "answered"` and queue it. An answer to a `needs`
   stop: `task.py note "OWNER ANSWER needs-<n> (<owner>): <answer>"`, requeue. A verify ask: requeue the test with the
   answer as a note. Then write `replies/<id>` saying what you did with it.
5. **Answer every question** sent from a page, in its thread and in `replies` (a free question gets a `q-<n>` doc with
   `question`, `where`, `text`, `at`), from the chain's notes, HANDOFF.md, commits and logs. Check every claim first.
6. **Ten watches at most.** A session watches at most 10 artifacts. Stop watching a chain's page once its PR merges
   (`ArtifactComments` watch, `on: false`); for pages beyond ten, read their `answers` and comments on every sync.

## Design and schema pages

1. Read the chain's page in full (the Artifact tool requires it for files you didn't write).
2. `fix_page.py <page>`: removes a document skeleton of its own, enforces the 16px phone gutter, checks the title and the
   dark-mode tokens. Fix anything else by hand.
3. **Cross-check overlaps**: two pages that change the same row or screen must agree; add a note to both and an option
   that says it once.
4. Publish. Schema pages are markdown: `md_to_page.py <slug> <md path> "<Title>" <out.html>`, then publish the HTML.
   Pages that link each other: publish one, put its URL into the other, publish that, then republish the first.
5. `post_publish.sh <slug> <page> <url> "<choices; open>"` after the publish returns (never in parallel with it: it refuses
   anything that isn't an artifact URL). It links the README row, commits, pushes and logs the page in `design-pages.md`.
6. Send the owner every link with its open questions in one message. A session can watch only 10 artifacts; beyond that,
   read comments (`ArtifactComments read`) when the owner says they've commented.
7. **Sign-off must be explicit.** If the owner says "done" and the pages have no comments, ask: sign off all as
   recommended, or comment first. Then `record_signoff.py signoffs.json queue-build.txt <date>` (try `--dry-run` first) and
   start the build queue.

## Review Comments, On Each Chain's Page

1. When a chain ends `awaiting_owner` with review items, read every proposal (`task.py show`, `status.json` reviews).
2. Set your own recommendation per item in `live/<slug>.recs.json`: `{"1": {"rec": "Apply", "what": "...", "proposal":
   "..."}}`, rec **Apply** (as proposed), **Reply only** (no change, with the reason) or **Owner's call** (say what you
   recommend). `what` and `proposal` restate the bot's words as what the user or the system sees: who is affected, what
   they see, the fix in one line. Wording a signed-off page doesn't settle is always Owner's call.
3. Sync: each item goes up on the chain's page with its recommendation. Post its "Ready" line. The owner approves all as
   recommended on the page, or adds a note to change one.
4. From the page's `approvals` (and any note), write `approvals.json` and run `approve.py approvals.json
   queue-review.txt "<how approved>"`, then start the runner on the queue. Answer the PRs whose items are all reply-only
   straight away.
5. As each chain ends:
   - `answer.py <PR> <slug> --map`; items with no comment id map to NO THREAD: match those by the thread text
     (`threads.py list <PR>`).
   - Write the replies from what the chain actually pushed (`git log` in the worktree): "Fixed in <sha> (failing test first
     in <sha>): ..." or "No change, by <owner>'s decision: <reason>". **Check every claim** (a test you say exists, a line
     you quote) before posting; if you got one wrong, post a correction on the thread.
   - `answer.py <PR> <slug> replies/<PR>.json` replies and resolves; the signature line is added.
   - Bot review summaries list findings outside the diff: read `threads.py comments` and `threads.py reviews`, and answer
     each summary with `threads.py comment`, or the owner sees unresolved comments with every thread resolved.
   - Check `gh pr view <PR> --json mergeable` and report the PR ready to merge.

## Tickets

Out-of-scope findings, "its own ticket" decisions and follow-ups go into the team's issue tracker (through the repo's
own tickets skill or CLI, if it has one): dedupe first, set the status and type, propose a priority with a one-line
reason, say the scope. Chains can't reach the tracker: file what their notes name. Keep a `followups.md` in
the run for what isn't a ticket yet.

## Merging and integrating

- The owner merges (branch protection; the auto-mode classifier blocks Claude from admin-merging, and that is not to be
  worked around). Batch merge requests: one message listing every ready PR.
- After every merge batch, first `retire.sh --apply`: each merged PR's worktree and branch go as it merges, not at the
  end of the run. A worktree is 5+ GB of builds; left to the close, they outlived their runs and filled the disk.
- After merges, for every open PR:
  1. `gh pr view <n> --json mergeable,mergeStateStatus` (UNKNOWN means GitHub is still computing: ask again).
  2. `merge_base.sh <slug>`. Clean: check the shared files it prints for semantic clashes and build. Conflicts:
     - Two sides added different members, rows or sections at the same spot: keep both; when the conflict sits mid-method,
       the shared closing lines must close each side's member.
     - One side moved code the other side changed (a call moved into a service, a release added on the old path): carry
       the change to the new place, and retire tests that pinned the old place with a replacement at the new one.
     - Read every auto-merged hunk in the conflicted files: an inserted line can reference a variable that doesn't exist
       in its new scope and still merge cleanly.
     - Use CRLF-agnostic matching when scripting a resolution, and write resolution scripts to a file (shell escaping of
       `\r` and `\n` inside heredocs corrupts them).
  3. `merge_base.sh <slug> --commit "<what conflicted and how it was resolved>"` starts the gate; `wait_gate.sh <slug>`;
     a known-flaky failure is confirmed by running it alone. Push, `wait_ci.sh <PR>`, report.
- A PR merged earlier may make a still-open one fail to compile without any textual conflict: re-merge and build before
  telling the owner it is ready.
- Verify after a batch merges that each merged PR's last commit is its head (nothing pushed after the merge was lost).

## Re-verify and close

- Requeue the verify tests the merged fixes cover; leave tests whose other defects are still open. Notes on each requeued
  test say what merged, what the guide now expects, and what is known-pending and how to judge it.
- New failures from the re-run go back to triage with the run's evidence.
- `retire.sh --apply` once more (state copied to `<run>/retired/`); remove the verify worktree and any base worktree
  (`git worktree remove`), which it never touches. Stop runner windows.
- PRs still open at the close merge later, with no session watching: say so in the hand-off. The next run's
  `retire.sh --all-runs --apply` retires them, and every earlier run's other late merges.
- Save to memory what changed how you or the owner work (a rule, a correction), not what the repo already records.
