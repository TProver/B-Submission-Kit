"""BSK Submission client, invoked from Atelier B plug-ins.

Subcommands:
    connect <project_name> <project_bdp>
        First-run Tk dialog asks for student name + server URL.
        Saves to %APPDATA%\\BSKSubmissionKit\\config.json (or XDG on Linux).
        POSTs /api/connect and shows a confirmation popup.

    submit <project_name> <project_bdp>
        Reads config (fails with a popup if not configured).
        Zips the project tree (sources + bdp), POSTs /api/submit.
        Shows a popup with the dashboard URL on success.

The script is designed to work on Windows and Linux with no third-party
dependencies (stdlib only: tkinter, zipfile, urllib, json, pathlib).
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
import traceback
from pathlib import Path
from urllib import request, error


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "BSKSubmissionKit"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "bsksubmissionkit"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def popup(title: str, message: str, kind: str = "info") -> None:
    """Show a modal popup. kind = info | warn | error."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        {"info": messagebox.showinfo,
         "warn": messagebox.showwarning,
         "error": messagebox.showerror}[kind](title, message)
        root.destroy()
    except Exception:
        print(f"[{kind.upper()}] {title}: {message}", file=sys.stderr)


def ask_config(existing: dict) -> dict | None:
    """Modal form asking for student name + server URL. Returns dict or None if cancelled."""
    import tkinter as tk

    result: dict = {}
    cancelled = {"flag": False}

    root = tk.Tk()
    root.title("BSK Submission Kit - Configuration")
    root.attributes("-topmost", True)
    try:
        root.geometry("400x180")
    except Exception:
        pass

    tk.Label(root, text="Student name (letters / digits / _ / -):").pack(anchor="w", padx=12, pady=(12, 0))
    name_var = tk.StringVar(value=existing.get("student_id", ""))
    tk.Entry(root, textvariable=name_var, width=50).pack(padx=12, fill="x")

    tk.Label(root, text="Submission server URL (e.g. http://192.168.1.42:8080):").pack(anchor="w", padx=12, pady=(8, 0))
    url_var = tk.StringVar(value=existing.get("server_url", "http://localhost:8000"))
    tk.Entry(root, textvariable=url_var, width=50).pack(padx=12, fill="x")

    def ok():
        result["student_id"] = name_var.get().strip()
        result["server_url"] = url_var.get().strip().rstrip("/")
        root.destroy()

    def cancel():
        cancelled["flag"] = True
        root.destroy()

    bar = tk.Frame(root)
    bar.pack(pady=14)
    tk.Button(bar, text="OK", width=10, command=ok).pack(side="left", padx=6)
    tk.Button(bar, text="Cancel", width=10, command=cancel).pack(side="left", padx=6)

    root.bind("<Return>", lambda _e: ok())
    root.bind("<Escape>", lambda _e: cancel())

    root.mainloop()

    if cancelled["flag"]:
        return None
    if not result.get("student_id") or not result.get("server_url"):
        return None
    return result


def sanitize_student_id(sid: str) -> str:
    out = "".join(c if c.isalnum() or c in "_-" else "_" for c in sid.strip())
    return out[:64] or "anon"


def http_post_json(url: str, payload: dict, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_multipart(url: str, fields: dict[str, str], file_path: Path,
                        file_field: str = "file", timeout: float = 120) -> dict:
    """Minimal multipart/form-data uploader using stdlib only."""
    import uuid
    boundary = "----BSKKitBoundary" + uuid.uuid4().hex
    lines: list[bytes] = []
    for k, v in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{k}"'.encode())
        lines.append(b"")
        lines.append(v.encode("utf-8"))
    lines.append(f"--{boundary}".encode())
    lines.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"'.encode())
    lines.append(b"Content-Type: application/zip")
    lines.append(b"")
    lines.append(file_path.read_bytes())
    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines)
    req = request.Request(url, data=body, method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def zip_project(project_name: str, project_bdp: Path, out_zip: Path) -> None:
    """Zip the project tree: parent of bdp (contains both bdp/ and sources)."""
    project_root = project_bdp.parent.resolve()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(project_root):
            for f in files:
                full = Path(root) / f
                try:
                    arc = full.relative_to(project_root)
                except ValueError:
                    continue
                zf.write(full, arcname=str(Path(project_name) / arc))


def cmd_connect(project_name: str, project_bdp: str) -> int:
    cfg = load_config()
    # Always show the dialog on Connect so the student can adjust student_id
    # or server URL without hand-editing the config file. Pre-filled with
    # whatever was saved from the last run.
    new = ask_config(cfg)
    if new is None:
        popup("BSK Connect", "Cancelled.", "warn")
        return 1
    new["student_id"] = sanitize_student_id(new["student_id"])
    cfg.update(new)
    save_config(cfg)

    try:
        resp = http_post_json(f"{cfg['server_url']}/api/connect", {
            "student_id": cfg["student_id"],
            "project_name": project_name,
            "hostname": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
            "session_token": cfg.get("session_token", ""),
        })
    except error.HTTPError as e:
        # 409 -> name already claimed by someone else; 401 -> token expired.
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
            err = json.loads(body).get("error", body)
        except Exception:
            err = body or str(e)
        popup("BSK Connect - rejected", err, "error")
        return 3
    except Exception as e:
        popup("BSK Connect - error", f"Failed to reach {cfg['server_url']}\n\n{e}", "error")
        return 2

    # Persist the server-issued session token so subsequent Submits authenticate.
    if resp.get("session_token"):
        cfg["session_token"] = resp["session_token"]
        save_config(cfg)

    popup("BSK Connect", (
        f"Connected as: {cfg['student_id']}\n"
        f"Server: {cfg['server_url']}\n"
        f"Dashboard: {resp.get('dashboard_url', cfg['server_url'] + '/')}\n"
        f"Project: {project_name}"
    ), "info")
    return 0


def cmd_submit(project_name: str, project_bdp: str) -> int:
    cfg = load_config()
    if not cfg.get("student_id") or not cfg.get("server_url"):
        popup("BSK Submit", "Run 'BSK Submission / Connect' first.", "warn")
        return 1

    bdp = Path(project_bdp)
    if not bdp.exists():
        popup("BSK Submit - error", f"Project bdp not found:\n{bdp}", "error")
        return 2

    tmpdir = Path(os.environ.get("TEMP") or "/tmp") / "bsksubmissionkit"
    tmpdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    zip_path = tmpdir / f"{cfg['student_id']}_{project_name}_{ts}.zip"

    try:
        zip_project(project_name, bdp, zip_path)
    except Exception as e:
        popup("BSK Submit - error", f"Failed to zip project:\n{e}\n\n{traceback.format_exc()}", "error")
        return 3

    if not cfg.get("session_token"):
        popup("BSK Submit", "No session token in config. Run 'BSK Submission / Connect' first.", "warn")
        return 6

    try:
        resp = http_post_multipart(
            f"{cfg['server_url']}/api/submit",
            fields={
                "student_id": cfg["student_id"],
                "project_name": project_name,
                "session_token": cfg["session_token"],
            },
            file_path=zip_path,
            file_field="file",
        )
    except error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        popup("BSK Submit - rejected", body or str(e), "error")
        return 7
    except error.URLError as e:
        popup("BSK Submit - error", f"Failed to upload to {cfg['server_url']}\n\n{e}", "error")
        return 4
    except Exception as e:
        popup("BSK Submit - error", f"Upload failed:\n{e}", "error")
        return 5

    popup("BSK Submit", (
        f"Submitted. Server will verify in the background.\n\n"
        f"Submission ID: {resp.get('submission_id', '?')}\n"
        f"Size: {zip_path.stat().st_size:,} bytes\n"
        f"Dashboard: {resp.get('dashboard_url', cfg['server_url'] + '/')}"
    ), "info")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: bsk_client.py (connect|submit) <project_name> <project_bdp>", file=sys.stderr)
        return 64
    sub = argv[1]
    args = argv[2:]
    if sub == "connect":
        if len(args) < 2:
            popup("BSK Connect", "Missing project_name or project_bdp argument.", "error")
            return 64
        return cmd_connect(args[0], args[1])
    if sub == "submit":
        if len(args) < 2:
            popup("BSK Submit", "Missing project_name or project_bdp argument.", "error")
            return 64
        return cmd_submit(args[0], args[1])
    popup("BSK Client", f"Unknown subcommand: {sub}", "error")
    return 64


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except Exception as e:
        popup("BSK Client - crash", f"{e}\n\n{traceback.format_exc()}", "error")
        sys.exit(99)
