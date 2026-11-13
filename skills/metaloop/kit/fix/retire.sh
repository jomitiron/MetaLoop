#!/usr/bin/env bash
# Retire spent worktrees and branches (a merged PR's worktree is gigabytes of builds). Lists every worktree under WT_ROOT with its PR state; with --apply,
# removes the worktree and deletes the local branch for each MERGED or CLOSED PR (the remote branch is GitHub's to delete).
# Before removing, it copies the branch's .fixloop/status.json, brief, session list and session logs to <run>/retired/<slug>/
# for the record; the chain's live page reads them from there (live_sync.py), so it keeps showing the merged chain.
# Run it after every merge batch, not once at the end: PRs merge after a run closes, and each worktree holds 5+ GB of builds.
# Never removed: uncommitted changes (untracked files included), commits the PR's head doesn't have, and a worktree on no
# branch (a base or verify target: remove it by hand when its run closes).
#   retire.sh                        list
#   retire.sh --apply                remove merged/closed ones
#   retire.sh --all-runs [--apply]   the same for every fix run beside this one, so a later run retires an earlier run's
#                                    late merges (each keeps its own loop.conf and retired/)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=; ALL=
for a in "$@"; do
    case "$a" in --apply) APPLY=--apply ;; --all-runs) ALL=1 ;; *) echo "usage: retire.sh [--all-runs] [--apply]" >&2; exit 2 ;; esac
done
if [ -n "$ALL" ]; then
    fetched=
    for run in "$(dirname "$HERE")"/*/; do
        [ -f "$run/loop.conf" ] && [ -f "$run/fixloop.sh" ] || continue
        repo=$(source "$run/loop.conf"; echo "$REPO")
        if [ -n "$APPLY" ] && [[ "$fetched" != *"|$repo|"* ]]; then   # runs often share a repo: fetch it once
            git -C "$repo" fetch -q origin 2>/dev/null; fetched+="|$repo|"
        fi
        echo "== $(basename "$run")"
        RUN_DIR="${run%/}" FETCHED=1 bash "${BASH_SOURCE[0]}" $APPLY
    done
    exit 0
fi
RUN_DIR="${RUN_DIR:-$HERE}"
source "$RUN_DIR/loop.conf"
# Only removal needs the PR's head locally (it may have been pushed from elsewhere); a listing stays offline.
[ -z "$APPLY" ] || [ -n "${FETCHED:-}" ] || git -C "$REPO" fetch -q origin 2>/dev/null
for wt in "$WT_ROOT"/*/; do
    [ -d "$wt/.git" ] || [ -f "$wt/.git" ] || continue
    wt="${wt%/}"; slug=$(basename "$wt"); br=$(git -C "$wt" branch --show-current)
    [ -n "$br" ] || { echo "$slug  (no branch)  kept: a base or verify target"; continue; }
    read -r st num head <<<"$(gh pr list --repo "$GH_REPO" --head "$br" --state all --json number,state,headRefOid \
        --jq 'if length == 0 then "" else (.[0] | "\(.state) #\(.number) \(.headRefOid)") end' 2>/dev/null)"
    dirty=$(git -C "$wt" status --porcelain | wc -l)   # untracked files count: a new file never committed is work too
    echo "$slug  $br  ${st:-no PR} $num  uncommitted=$dirty"
    case "$st" in MERGED|CLOSED)
        [ -n "$APPLY" ] || continue
        [ "$dirty" -eq 0 ] || { echo "   kept: uncommitted changes"; continue; }
        git -C "$wt" merge-base --is-ancestor HEAD "$head" 2>/dev/null || { echo "   kept: commits the PR doesn't have"; continue; }
        mkdir -p "$RUN_DIR/retired/$slug/state" && cp -r "$wt/.fixloop/status.json" "$wt/.fixloop/brief.md" "$wt/.fixloop/logs" "$RUN_DIR/retired/$slug/" 2>/dev/null
        cp "$wt/.fixloop/state/sessions.txt" "$RUN_DIR/retired/$slug/state/" 2>/dev/null
        # core.longpaths: without it Windows stops at the first path past MAX_PATH in obj/ and leaves the builds behind.
        if err=$(git -C "$REPO" -c core.longpaths=true worktree remove --force "$wt" 2>&1); then
            git -C "$REPO" branch -D "$br" >/dev/null && echo "   retired (state kept in retired/$slug)"
        else
            echo "   kept: $(head -1 <<<"$err")"   # a running build or server holds a file: stop it and run again
        fi ;;
    esac
done
