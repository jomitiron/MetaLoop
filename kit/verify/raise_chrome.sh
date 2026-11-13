#!/usr/bin/env bash
# Brings the RUN's Chrome to the front, on the tab whose URL contains the text if one is given. Use it when a pause needs
# the owner in that window: people otherwise reach for their own browser.
#   raise_chrome.sh [tab-url-text]           e.g. raise_chrome.sh intuit.com
# The tab is chosen over the run's debug port on every platform. Windows: raise_chrome.ps1 brings the window up. macOS:
# System Events does, by the process id; the first time, macOS asks to let this terminal control System Events
# (Privacy & Security > Automation). Without that the tab is still active: tell the owner which window it is.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/loop.conf"
source "$HERE/platform.sh"
PROFILE="$HERE/chrome-profile"
if [ "$PLATFORM" = windows ]; then
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/raise_chrome.ps1")" \
        -Profile "$(cygpath -w "$PROFILE")" -Port "$CDP_PORT" -TabUrlContains "${1:-}"
fi
if [ -n "${1:-}" ]; then
    id=$(curl -s "http://127.0.0.1:$CDP_PORT/json" | "$PYTHON" -c "
import json, sys
tabs = [t for t in json.load(sys.stdin) if t.get('type') == 'page' and sys.argv[1] in t.get('url', '')]
print(tabs[0]['id'] if tabs else '')" "$1" 2>/dev/null)
    [ -n "$id" ] && curl -s "http://127.0.0.1:$CDP_PORT/json/activate/$id" >/dev/null
fi
pid=$(chrome_main_pid "$PROFILE")
[ -n "$pid" ] || { echo "the run's Chrome is not running"; exit 1; }
if [ "$PLATFORM" = mac ] && osascript -e "tell application \"System Events\" to set frontmost of (first process whose unix id is $pid) to true" >/dev/null 2>&1; then
    echo "raised the run's Chrome (pid $pid)${1:+, tab matching '$1'}"
else
    echo "the tab is active, but the window could not be raised (macOS: allow this terminal to control System Events in"
    echo "Privacy & Security > Automation). Tell $OWNER: the Chrome window using the profile $PROFILE (pid $pid)."
fi
