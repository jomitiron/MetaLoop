# Platform helpers for the loop scripts: sourced, never run. The kit was first written for Windows with Git Bash; on
# macOS (and Linux) the same calls go to the native tools. Every Windows branch is the code the scripts had before.
#   source "$HERE/platform.sh"          (after loop.conf, so the run's PYTHON wins)
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) PLATFORM=windows ;;
    Darwin) PLATFORM=mac ;;
    *) PLATFORM=linux ;;
esac
PLATFORM_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The run's Python is loop.conf PYTHON. A run folder made before that key existed: python on Windows, python3 elsewhere
# (macOS has no `python`).
if [ -z "${PYTHON:-}" ]; then
    if [ "$PLATFORM" = windows ] || ! command -v python3 >/dev/null 2>&1; then PYTHON=python; else PYTHON=python3; fi
fi

# Git Bash's cygpath turns /c/... paths into Windows ones for Windows tools. A POSIX path needs no conversion.
if ! command -v cygpath >/dev/null 2>&1; then
    cygpath() { printf '%s\n' "${@: -1}"; }
fi

sha1() { if command -v sha1sum >/dev/null 2>&1; then sha1sum; else shasum -a 1; fi; }

# A toast on Windows, a notification on macOS, notify-send on Linux when it's there. Never fails, never waits.
platform_notify() {
    case "$PLATFORM" in
        windows) powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$PLATFORM_HERE/notify.ps1")" "$1" "$2" >/dev/null 2>&1 & ;;
        mac) osascript -e 'on run argv' -e 'display notification (item 2 of argv) with title (item 1 of argv)' -e 'end run' \
                 "$1" "${2:- }" >/dev/null 2>&1 & ;;
        *) if command -v notify-send >/dev/null 2>&1; then notify-send "$1" "$2" >/dev/null 2>&1 & fi ;;
    esac
}

# The PID listening on a TCP port, or nothing. (BSD netstat has no -o, so on macOS the Windows form always said "free".)
port_pid() {
    if [ "$PLATFORM" = windows ]; then
        netstat -ano | tr -d '\r' | awk -v p=":$1" '$1=="TCP" && $4=="LISTENING" && $2 ~ (p "$") {print $5; exit}'
    else
        lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1
    fi
}

# Stop a process and its children.
kill_tree() {
    if [ "$PLATFORM" = windows ]; then
        taskkill //PID "$1" //T //F >/dev/null 2>&1
    else
        pkill -TERM -P "$1" >/dev/null 2>&1; kill -TERM "$1" >/dev/null 2>&1
    fi
}

# The run's Chrome is the one started with the run's profile (--user-data-dir); its main process has no --type= flag.
chrome_main_pid() {  # <profile dir>   (POSIX; on Windows raise_chrome.ps1 finds it)
    ps axww -o pid= -o command= | awk -v p="--user-data-dir=$1" \
        'index($0, p) && !index($0, "--type=") && !index($0, "awk -v") {print $1; exit}'
}

# Stop the Chrome started with that profile, never the owner's own.
chrome_stop() {  # <profile dir>
    if [ "$PLATFORM" = windows ]; then
        local pat; pat="$(cygpath -w "$1")"
        # -like treats only * ? [ ] as wildcards, so the Windows path goes in as it is
        powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { \$_.CommandLine -like '*${pat}*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1
    else
        local pid; pid=$(chrome_main_pid "$1")
        [ -z "$pid" ] || kill -TERM "$pid" >/dev/null 2>&1   # the main process takes its helpers with it
    fi
}
