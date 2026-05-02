#!/bin/bash
# ============================================================
# BSK Atelier B plug-in installer (Linux)
#
# Copies the BSK Submission plug-in into the Atelier B
# share/plugins/ folder so it appears as a "BSK Submission"
# submenu under the Project menu.
#
# Likely needs root (system-wide Atelier B install). Run with:
#   sudo bash install_plugin.sh
#
# If your Atelier B is in a non-default location, set ATB_ROOT
# before running:
#   sudo ATB_ROOT=/path/to/atelierb bash install_plugin.sh
# ============================================================
set -e

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PLUGIN="$ROOT/plugin"

# Try common Atelier B install paths if ATB_ROOT not set.
if [ -z "$ATB_ROOT" ]; then
    for CANDIDATE in \
        /opt/atelierb-cssp-24.04 \
        /opt/atelierb-free-24.04 \
        /opt/atelierb-free-24.04.2 \
        /opt/atelierb-25.02 \
        /opt/atelierb \
        /usr/share/atelierb \
        /usr/local/atelierb; do
        if [ -d "$CANDIDATE/share/plugins" ] || [ -d "$CANDIDATE/share" ]; then
            ATB_ROOT="$CANDIDATE"
            break
        fi
    done
fi

if [ -z "$ATB_ROOT" ] || [ ! -d "$ATB_ROOT" ]; then
    echo "ERROR: Atelier B install not found."
    echo "Tried: /opt/atelierb-cssp-24.04, /opt/atelierb-*, /usr/share/atelierb, /usr/local/atelierb"
    echo "Set ATB_ROOT to the right path, then re-run."
    exit 1
fi

DST="$ATB_ROOT/share/plugins"

echo
echo "===== BSK Atelier B plug-in -- Linux installer ====="
echo "Source : $PLUGIN"
echo "Target : $DST"
echo

mkdir -p "$DST"

# Linux .etool variants point at bsk_run.sh, not bsk_run.cmd.
install -m 0644 "$PLUGIN/BSKConnect.linux.etool"  "$DST/BSKConnect.etool"
install -m 0644 "$PLUGIN/BSKSubmit.linux.etool"   "$DST/BSKSubmit.etool"
install -m 0755 "$PLUGIN/bsk_run.sh"              "$DST/bsk_run.sh"
install -m 0644 "$PLUGIN/bsk_client.py"           "$DST/bsk_client.py"
install -m 0644 "$PLUGIN/bsk_connect.png"         "$DST/bsk_connect.png"
install -m 0644 "$PLUGIN/bsk_submit.png"          "$DST/bsk_submit.png"

cat <<EOF

============================================================
 Plug-in installed successfully.

 Next steps:
   1. Fully close Atelier B if it is currently running.
   2. Reopen Atelier B and open any B project.
   3. The Project menu now has a "BSK Submission" submenu
      with "Connect" and "Submit and verify" entries.
   4. Click "Connect" and enter your name + the classroom
      server URL given by the teacher.

 If the menu does not appear after restart, check that:
   - python3 and python3-tk are installed:
       sudo apt install python3 python3-tk
   - $DST/ is the path Atelier B reads (binary string check:
       strings $ATB_ROOT/bin/AtelierB | grep -iE 'plugins|etool')
============================================================
EOF
