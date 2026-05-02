#!/bin/bash
# ============================================================
# BSK classroom server installer (Linux)
#
# Run once on the teacher machine to set up the Python venv and
# install dependencies. After install, use start_server.sh (in
# receiver/) to launch the server on demand.
#
# Prerequisites:
#   - python3 3.9+ and python3-venv
#       sudo apt install python3 python3-venv python3-tk
#   - Atelier B Linux installed (for bbatch; default
#       /opt/atelierb-*/bbin/<arch>/bbatch or override via
#       BSK_BBATCH).
#   - ProB installed (default 'probcli' on PATH or set
#       BSK_PROBCLI).
#   - Microsoft Edge or Chromium installed (for PDF report
#       rendering); set BSK_EDGE if neither is on PATH.
# ============================================================
set -e

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RECEIVER="$ROOT/receiver"
VENV="$RECEIVER/.venv"

echo
echo "===== BSK classroom server -- Linux installer ====="
echo

# 1. locate python3
PY="${BSK_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: $PY not found. Install python3 first:"
    echo "  sudo apt install python3 python3-venv python3-tk"
    exit 1
fi
echo "[1/3] Python: $($PY --version)"

# 2. create venv
if [ -x "$VENV/bin/python" ]; then
    echo "[2/3] Virtual environment already exists at $VENV, reusing."
else
    echo "[2/3] Creating virtual environment at $VENV"
    "$PY" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
fi

# 3. install dependencies
echo "[3/3] Installing dependencies from receiver/requirements.txt"
"$VENV/bin/python" -m pip install -r "$RECEIVER/requirements.txt"

cat <<EOF

============================================================
 Server installed successfully.

 To start the server, run:
   $RECEIVER/start_server.sh

 Useful flags:
   start_server.sh                 (default port 8000)
   start_server.sh 9000            (use port 9000)
   start_server.sh --clean         (archive previous submissions)

 Optional: open port 8000 in your firewall:
   sudo ufw allow 8000/tcp
============================================================
EOF
