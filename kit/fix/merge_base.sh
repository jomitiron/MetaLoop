#!/usr/bin/env bash
# After the owner merges PRs: bring one open branch up to date with the base.
#   merge_base.sh <slug>                 fetch + merge origin/BASE; prints the conflicted files (exit 3) or the clean merge
#   merge_base.sh <slug> --commit "why"  after you resolved every conflict: commit the merge with attribution, start the gate
# Never push before the gate (or, for a clean re-merge, at least the build and the area's tests) has passed.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
cd "$WT_ROOT/$1" || { echo "no worktree for $1"; exit 2; }
attribution="Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
if [ "${2:-}" = "--commit" ]; then
    git rev-parse -q --verify MERGE_HEAD >/dev/null || { echo "no merge in progress"; exit 2; }
    markers=$( { git diff --name-only --diff-filter=U; git diff --name-only HEAD; } | sort -u |
               while IFS= read -r f; do [ -f "$f" ] && grep -lE '^(<<<<<<<|>>>>>>>)( |$)' "$f"; done)
    [ -z "$markers" ] || { echo "still conflicted (markers left):"; echo "$markers"; exit 3; }
    git add -u   # stages the resolved files (tracked only: stray untracked files stay out); merge-added files are staged
    left=$(git diff --name-only --diff-filter=U)
    [ -z "$left" ] || { echo "still unmerged: $left"; exit 3; }
    git commit -q -m "Merge origin/$BASE into $(git branch --show-current)

${3:-}

$attribution" && git log --oneline -1 | cat
    "$PYTHON" "$HERE/gate.py" --start | head -1
    exit 0
fi
[ -z "$(git status --porcelain | grep -v '^??')" ] || { echo "working tree not clean:"; git status --short | head; exit 2; }
git fetch -q origin "$BASE"
before=$(git rev-parse HEAD)
if git merge --no-edit "origin/$BASE" >/dev/null 2>&1; then
    if [ "$(git rev-parse HEAD)" = "$before" ]; then
        echo "already up to date with origin/$BASE: nothing merged"; exit 0
    fi
    if ! git rev-parse -q --verify HEAD^2 >/dev/null; then
        echo "fast-forwarded to origin/$BASE (the branch had no commits of its own): $(git log --oneline -1 | cat)"; exit 0
    fi
    # Only a real merge commit made just now gets its message replaced.
    git commit -q --amend -m "Merge origin/$BASE into $(git branch --show-current)

$attribution"
    echo "clean merge: $(git log --oneline -1 | cat)"
    echo "files the branch shares with what landed (check them for semantic clashes):"
    mb=$(git merge-base HEAD^1 "origin/$BASE")
    comm -12 <(git diff --name-only "$mb" HEAD^1 | sort) <(git diff --name-only "$mb" "origin/$BASE" | sort)
else
    echo "CONFLICTS in:"; git diff --name-only --diff-filter=U; exit 3
fi
