#!/usr/bin/env bash
# After a pause for a sign-in: waits until the RUN's Chrome (the debug port in loop.conf) has a tab whose URL matches the
# pattern, then writes RESUME so the loop continues by itself. People often sign in in their own browser by mistake: this
# only fires on the run's Chrome, so it also tells you when that happened (nothing fires).
#   resume_on_signin.sh '<URL regex>'      e.g. 'provider\.example\.com/connected'
# Pick a pattern only the finished step produces (a company id, a dashboard path): a tab left open from an earlier
# sign-in would otherwise match at once and resume the loop before the owner has done anything.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
deadline=$(( $(date +%s) + ${WAIT_HOURS:-4} * 3600 ))
until curl -s "http://127.0.0.1:$CDP_PORT/json" | "$PYTHON" -c "
import json, re, sys
tabs = [t for t in json.load(sys.stdin) if t.get('type') == 'page']
sys.exit(0 if any(re.search(sys.argv[1], t['url']) for t in tabs) else 1)" "$1"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "TIMEOUT: no tab matched '$1' in the run's Chrome. Open tabs:"
        curl -s "http://127.0.0.1:$CDP_PORT/json" | "$PYTHON" -c "import json,sys; [print(' ', t['url'][:120]) for t in json.load(sys.stdin) if t.get('type')=='page']"
        exit 3
    fi
    sleep 10
done
touch "$HERE/RESUME" && echo "matched '$1': RESUME written $(date +%H:%M:%S)"
