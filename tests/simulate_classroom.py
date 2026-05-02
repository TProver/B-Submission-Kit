"""Simulate a classroom of 10 students submitting Airlock and Tunnel projects.

This script mimics what the BSK Submit plug-in would do for each student
(Connect + Submit) but talks directly to the receiver's HTTP API instead
of going through Atelier B. Used for:
  * functional testing of the server / dashboard / verification pipeline,
  * regression testing after changes to verify.py / state.py / server.py,
  * documentation screenshots.

Layout assumed:
  tests/
    projects/
      Airlock/
        perfect/src/<.mch + .imp + .mch>
        broken/src/<.mch + bad .imp + .mch>
      Tunnel/
        perfect/src/<.mch + .imp>
        broken/src/<.mch + bad .imp>

The script runs sequentially: connect each student, then for each project
build a zip mimicking bsk_client.py:zip_project, POST it, move on. Most
students send the perfect variant; a chosen one sends the broken variant
so the dashboard shows a mix of overall:ok and overall:fail rows.

The script does NOT wait for verification to finish. It just queues
submissions; the user watches the dashboard process them.

Usage:
    python tests/simulate_classroom.py
    python tests/simulate_classroom.py --server http://localhost:8000
    python tests/simulate_classroom.py --pace 0.3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib import error, request


HERE = Path(__file__).parent
PROJECTS_DIR = HERE / "projects"
TMP_DIR = HERE / "_tmp_zips"
TOKENS_FILE = HERE / ".tokens.json"  # cached session_tokens for repeat runs


def _load_tokens() -> dict[str, str]:
    if not TOKENS_FILE.exists():
        return {}
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tokens(tokens: dict[str, str]) -> None:
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


# 10 anonymised student names. Stable order so a re-run produces the same
# arrival sequence on the dashboard's "time" sort.
STUDENTS = [
    "alice_dupont",
    "bob_martin",
    "claire_lefevre",
    "david_rousseau",
    "emma_garnier",
    "francois_picard",
    "gabriel_morel",
    "helene_chevalier",
    "isabelle_renault",
    "jerome_bonnet",
]

PROJECTS = ["Airlock", "Tunnel"]

# Per-project, the index of the student that submits the broken variant.
# Choosing different students per project gives a more interesting matrix
# in the dashboard than picking the same one for both.
BROKEN_STUDENT_FOR = {
    "Airlock": 4,   # emma_garnier  -> broken Airlock
    "Tunnel":  7,   # helene_chevalier -> broken Tunnel
}


# ---------- HTTP helpers (stdlib only) ------------------------------------ #

def http_post_json(url: str, payload: dict, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_multipart(url: str, fields: dict[str, str],
                        file_path: Path, file_field: str = "file",
                        timeout: float = 60) -> dict:
    boundary = "----BSKSimBoundary" + uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f"--{boundary}".encode())
        parts.append(f'Content-Disposition: form-data; name="{k}"'.encode())
        parts.append(b"")
        parts.append(v.encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"'.encode())
    parts.append(b"Content-Type: application/zip")
    parts.append(b"")
    parts.append(file_path.read_bytes())
    parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(parts)
    req = request.Request(url, data=body, method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------- Zip building ---------------------------------------------------- #

def build_zip(project_name: str, src_dir: Path, out_zip: Path) -> int:
    """Mirror plugin/bsk_client.py:zip_project. Returns size in bytes."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src_dir.iterdir()):
            if not f.is_file():
                continue
            arc = Path(project_name) / "src" / f.name
            zf.write(f, arcname=str(arc))
    return out_zip.stat().st_size


# ---------- Driver ---------------------------------------------------------- #

def run(server: str, pace: float) -> int:
    if not PROJECTS_DIR.is_dir():
        print(f"ERROR: projects dir missing: {PROJECTS_DIR}", file=sys.stderr)
        return 2

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print(f"BSK simulation -> {server}")
    print(f"  students: {len(STUDENTS)}")
    print(f"  projects: {PROJECTS}")
    print(f"  broken assignments: {BROKEN_STUDENT_FOR}")
    print()

    submitted = 0
    errors = 0
    tokens = _load_tokens()  # reuse session_tokens across runs (so we don't get name-conflict on re-run)

    for i, sid in enumerate(STUDENTS):
        # 1. Connect: server issues a session_token we must reuse on submits.
        # If we already have a cached token for this student, send it as proof
        # so the server returns the same binding (idempotent re-Connect).
        token = None
        try:
            resp = http_post_json(f"{server}/api/connect", {
                "student_id": sid,
                "project_name": "init",
                "hostname": f"sim-host-{i:02d}",
                "session_token": tokens.get(sid, ""),
            })
            token = resp.get("session_token")
            tokens[sid] = token
            _save_tokens(tokens)
            print(f"[connect] {sid} -> ok (token={token[:10] if token else 'NONE'}...)")
        except error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[connect] {sid} -> FAILED HTTP {e.code}: {body}")
            errors += 1
            continue
        except (error.URLError, ConnectionError) as e:
            print(f"[connect] {sid} -> FAILED: {e}")
            errors += 1
            continue

        if not token:
            print(f"[connect] {sid} -> WARNING: server returned no session_token")
            errors += 1
            continue

        time.sleep(pace)

        # 2. Submit each project, carrying the session token.
        for project in PROJECTS:
            variant = "broken" if BROKEN_STUDENT_FOR.get(project) == i else "perfect"
            src_dir = PROJECTS_DIR / project / variant / "src"
            if not src_dir.is_dir():
                print(f"  [skip] {project}/{variant}: source dir missing -> {src_dir}")
                errors += 1
                continue

            zip_path = TMP_DIR / f"{sid}__{project}__{variant}.zip"
            size = build_zip(project, src_dir, zip_path)

            try:
                resp = http_post_multipart(
                    f"{server}/api/submit",
                    fields={
                        "student_id": sid,
                        "project_name": project,
                        "session_token": token,
                    },
                    file_path=zip_path,
                )
                print(f"  [submit] {sid} {project} ({variant}, {size:,} B) "
                      f"-> {resp.get('submission_id')}, queue={resp.get('queue_depth')}")
                submitted += 1
            except (error.URLError, error.HTTPError, ConnectionError) as e:
                print(f"  [submit] {sid} {project} -> FAILED: {e}")
                errors += 1

            time.sleep(pace)

    print()
    print(f"Done. {submitted} submission(s) queued, {errors} error(s).")
    print(f"Open {server}/ to watch the dashboard process them.")
    return 0 if errors == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default=os.environ.get("BSK_SERVER",
                                                            "http://localhost:8000"),
                        help="Base URL of the BSK server (default: http://localhost:8000)")
    parser.add_argument("--pace", type=float, default=0.5,
                        help="Seconds to wait between HTTP calls (default: 0.5)")
    args = parser.parse_args()
    return run(args.server, args.pace)


if __name__ == "__main__":
    sys.exit(main())
