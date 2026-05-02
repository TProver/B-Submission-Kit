"""Session state for the BSK classroom server.

No database. A single JSON snapshot under `submissions/_state.json` mirrors
the in-memory dict and is rewritten atomically after each mutation.

The state tracks:
  students[sid] = {
    id, connected_at, last_activity, hostname,
    submissions: {
      <project_name>: {
        submission_id, timestamp, size_bytes,
        status, stages, scenarios, summary,
      },
      ...
    }
  }

Only the LATEST submission per (student, project) pair is retained.
On-disk artefacts live in submissions/<student_id>/latest_<project_name>/.

The dashboard view treats each (student, project) pair as one row.
"""

from __future__ import annotations

import calendar
import json
import os
import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Any


class State:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshot_path = root / "_state.json"
        self._lock = threading.RLock()
        self.students: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            self.students = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            self.students = {}

    def _save_unlocked(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.snapshot_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.students, indent=2), encoding="utf-8")
        os.replace(tmp, self.snapshot_path)

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _student(self, student_id: str) -> dict[str, Any]:
        s = self.students.setdefault(student_id, {"id": student_id, "submissions": {}})
        s.setdefault("submissions", {})  # legacy entries
        return s

    def touch(self, student_id: str) -> None:
        with self._lock:
            s = self._student(student_id)
            s["last_activity"] = self._now()
            self._save_unlocked()

    def connect(self, student_id: str, project_name: str, hostname: str) -> None:
        # Kept for compat; the new claim_name() is the auth-aware path.
        with self._lock:
            s = self._student(student_id)
            now = self._now()
            s["connected_at"] = s.get("connected_at") or now
            s["last_activity"] = now
            s["hostname"] = hostname
            self._save_unlocked()

    def claim_name(self, student_id: str, hostname: str,
                   presented_token: str | None = None
                   ) -> tuple[str, str]:
        """First-come-first-serve name binding.

        Returns (status, token):
          - status == "claimed"  -> name was free, generated a fresh token
          - status == "rebound"  -> name was bound to the same presented_token
                                    (idempotent re-Connect from the same plug-in)
          - status == "conflict" -> name is bound to a different token; token == "" (caller responsible for HTTP 409)

        The token is a 32-char URL-safe random string and is the only proof
        of ownership. It is never exposed via snapshot().
        """
        with self._lock:
            s = self._student(student_id)
            existing = s.get("secret")
            now = self._now()
            if existing is None:
                token = _secrets.token_urlsafe(24)
                s["secret"] = token
                s["connected_at"] = now
                s["last_activity"] = now
                s["hostname"] = hostname
                self._save_unlocked()
                return ("claimed", token)
            if presented_token and presented_token == existing:
                s["last_activity"] = now
                s["hostname"] = hostname
                self._save_unlocked()
                return ("rebound", existing)
            return ("conflict", "")

    def check_token(self, student_id: str, presented_token: str) -> bool:
        """Validate a session token before accepting any state-changing action."""
        with self._lock:
            s = self.students.get(student_id)
            if not s:
                return False
            return bool(presented_token) and presented_token == s.get("secret")

    def release_name(self, student_id: str) -> bool:
        """Teacher escape hatch: clear a binding so the student can re-Connect."""
        with self._lock:
            if student_id not in self.students:
                return False
            self.students[student_id].pop("secret", None)
            self._save_unlocked()
            return True

    def record_submission(self, student_id: str, submission_id: str,
                          project_name: str, size_bytes: int) -> None:
        with self._lock:
            s = self._student(student_id)
            now = self._now()
            s["last_activity"] = now
            s["submissions"][project_name] = {
                "submission_id": submission_id,
                "timestamp": now,
                "size_bytes": size_bytes,
                "status": "queued",
                "stages": {"typecheck": "pending", "pog": "pending", "prove": "pending"},
                "summary": "",
            }
            self._save_unlocked()

    def update_submission(self, student_id: str, project_name: str,
                          **kwargs: Any) -> None:
        with self._lock:
            s = self.students.get(student_id)
            if not s or project_name not in s.get("submissions", {}):
                return
            s["submissions"][project_name].update(kwargs)
            s["last_activity"] = self._now()
            self._save_unlocked()

    def snapshot(self) -> dict[str, Any]:
        """Flatten state into one entry per (student, project) submission.

        Secrets (per-student session tokens) are NEVER included in the snapshot;
        the dashboard is public and must not leak credentials.
        """
        with self._lock:
            now_epoch = time.time()
            rows: list[dict[str, Any]] = []
            for sid, s in self.students.items():
                last = s.get("last_activity")
                liveness = self._liveness(last, now_epoch)
                base = {
                    "id": sid,
                    "hostname": s.get("hostname", ""),
                    "connected_at": s.get("connected_at"),
                    "last_activity": last,
                    "liveness": liveness,
                    "claimed": bool(s.get("secret")),
                }
                subs = s.get("submissions", {})
                if not subs:
                    rows.append({**base, "project_name": "(none)", "last_submission": None})
                    continue
                for project_name, sub in subs.items():
                    rows.append({**base, "project_name": project_name,
                                 "last_submission": sub})
            return {
                "generated_at": self._now(),
                "students": sorted(rows, key=lambda r: (r["id"], r["project_name"])),
            }

    @staticmethod
    def _liveness(last: str | None, now_epoch: float) -> str:
        if not last:
            return "red"
        try:
            # `last` is a UTC timestamp like "2026-05-01T08:55:44Z".
            last_epoch = calendar.timegm(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ"))
            age = now_epoch - last_epoch
            if age < 60:
                return "green"
            if age < 300:
                return "amber"
        except Exception:
            pass
        return "red"
