#!/usr/bin/env bash
# After a design page is published as an Artifact: link the artifact in the page's README row, commit, push, log it.
#   post_publish.sh <slug> <page path in the repo> <artifact url> "<choices / open questions>"
# Run it AFTER the Artifact call returns, never in parallel with it: it refuses anything that isn't a real artifact URL.
set -eu
slug=$1 page=$2 url=$3 note=$4
case "$url" in https://claude.ai/artifact/[A-Za-z0-9]*|https://claude.ai/code/artifact/[A-Za-z0-9-]*) ;;
    *) echo "refused: '$url' is not an artifact URL" >&2; exit 2 ;; esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
cd "$WT_ROOT/$slug"
base=$(basename "$page")
case "$page" in
  "$MOCKUPS_DIR"/*) readme="$MOCKUPS_DIR/README.md"; rel=${page#"$MOCKUPS_DIR"/} ;;
  "$SCHEMA_DIR"/*) readme="$SCHEMA_DIR/README.md"; rel=$base ;;
  *) echo "no README registry for $page" >&2; exit 2 ;;
esac
"$PYTHON" - "$readme" "$base" "$rel" "$url" <<'PY'
import sys
p, base, rel, url = sys.argv[1:]
s = open(p, encoding="utf-8", newline="").read()
if url in s:
    print("README already links", url); sys.exit()
link = f"[{base}]({rel})"
if link in s:
    s = s.replace(link, f"{link} · [artifact]({url})", 1)
else:  # the row names the page another way: put the link after its first mention
    i = s.find(base)
    if i < 0:
        sys.exit(f"no README row mentions {base}")
    j = s.find(")", i)
    s = s[:j + 1] + f" · [artifact]({url})" + s[j + 1:]
for stale in (" · artifact: to be published", " · artifact: pending"):
    s = s.replace(stale, "")
open(p, "w", encoding="utf-8", newline="").write(s)
print("README row linked")
PY
git add -A "$page" "$readme"
git commit -q -m "docs: $slug design page links its artifact

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push -q origin "${BRANCH_PREFIX}${SLUG_PREFIX}${slug}"
echo "| $slug | $page | $url | $note |" >> "$HERE/design-pages.md"
echo "pushed $(git rev-parse --short HEAD)"
