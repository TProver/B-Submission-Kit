#!/bin/bash
# Start the BSK classroom submission server on Linux.
# Mirrors start_server.cmd's behaviour:
#   start_server.sh                  -- default port 8000
#   start_server.sh 9000             -- start on port 9000
#   start_server.sh --clean          -- archive submissions/+server_workspace/, then start
#   start_server.sh --clean 9000     -- combine
#   start_server.sh --purge          -- DELETE submissions/+server_workspace/ (DELETE-confirm)
set -e

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
VENV="$HERE/.venv"

CLEAN=0
PURGE=0
PORT=8000

while [ $# -gt 0 ]; do
    case "$1" in
        --clean) CLEAN=1; shift ;;
        --purge) PURGE=1; shift ;;
        *)       PORT="$1"; shift ;;
    esac
done

archive_submissions() {
    local TS ARCHIVE
    TS="$(date +%Y%m%d-%H%M%S)"
    ARCHIVE="$ROOT/archives/$TS"
    echo
    echo "About to ARCHIVE existing submission state."
    [ -d "$ROOT/submissions" ]      && echo "  - submissions/        -> archives/$TS/submissions/"
    [ -d "$ROOT/server_workspace" ] && echo "  - server_workspace/   -> archives/$TS/server_workspace/"
    echo
    read -r -p "Continue with archive? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y) ;;
        *)  echo "Aborted."; exit 0 ;;
    esac
    mkdir -p "$ARCHIVE"
    [ -d "$ROOT/submissions" ]      && mv "$ROOT/submissions"      "$ARCHIVE/submissions"
    [ -d "$ROOT/server_workspace" ] && mv "$ROOT/server_workspace" "$ARCHIVE/server_workspace"
    echo "Archived to $ARCHIVE"
}

purge_submissions() {
    echo
    echo "*** WARNING ***  --purge will DELETE the following without recovery:"
    [ -d "$ROOT/submissions" ]      && echo "  - $ROOT/submissions/"
    [ -d "$ROOT/server_workspace" ] && echo "  - $ROOT/server_workspace/"
    echo
    read -r -p "Type DELETE to confirm: " CONFIRM
    if [ "$CONFIRM" != "DELETE" ]; then
        echo "Aborted -- nothing deleted."
        exit 0
    fi
    rm -rf "$ROOT/submissions" "$ROOT/server_workspace"
    echo "Purged."
}

[ "$CLEAN" = "1" ] && archive_submissions
[ "$PURGE" = "1" ] && purge_submissions

if [ ! -x "$VENV/bin/python" ]; then
    echo
    echo "Virtual environment not found at $VENV"
    echo "Run install/linux/install_server.sh first."
    exit 1
fi

echo
echo "BSK classroom server starting on port $PORT."
echo "Dashboard: http://localhost:$PORT/"
echo "Press Ctrl+C to stop."
echo

exec "$VENV/bin/python" -m uvicorn server:app \
    --app-dir "$HERE" --host 0.0.0.0 --port "$PORT"
