#!/bin/bash
# Linux wrapper that Atelier B launches via the BSK .etool files.
# Finds a Python 3 interpreter and runs bsk_client.py with the passed args.
# Counterpart to bsk_run.cmd on Windows.
set -e

HERE="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)"

# 1) BSK_PYTHON env var wins if set.
if [ -n "$BSK_PYTHON" ] && [ -x "$BSK_PYTHON" ]; then
    exec "$BSK_PYTHON" "$HERE/bsk_client.py" "$@"
fi

# 2) python3 on PATH.
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$HERE/bsk_client.py" "$@"
fi

# 3) python on PATH.
if command -v python >/dev/null 2>&1; then
    exec python "$HERE/bsk_client.py" "$@"
fi

# 4) Fallback: common install locations.
for P in /usr/bin/python3 /usr/local/bin/python3 /opt/python3/bin/python3; do
    if [ -x "$P" ]; then
        exec "$P" "$HERE/bsk_client.py" "$@"
    fi
done

echo "ERROR: Python 3 not found. Install python3 (apt install python3 python3-tk) or set BSK_PYTHON." >&2
exit 127
