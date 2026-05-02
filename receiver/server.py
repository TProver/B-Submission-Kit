"""BSK classroom submission server.

Single-process FastAPI app with:
  GET  /               dashboard HTML
  GET  /api/status     JSON snapshot for the dashboard (polled every 2s)
  POST /api/connect    register a student session (JSON body)
  POST /api/submit     accept a project zip (multipart/form-data)
  GET  /api/student/{sid}/log  view the latest verification log for a student

Verification runs in an in-process asyncio queue worker. One worker is
sufficient for cohorts up to ~50 students. The server keeps going if a
student's Atelier B disconnects mid-verification: the job is queued the
moment the upload finishes, so the client's session doesn't matter.

No database. State lives in-memory; each mutation writes submissions/_state.json.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

# Local modules (same directory).
sys.path.insert(0, str(Path(__file__).parent))
from state import State
from verify import verify, VerificationResult


HERE = Path(__file__).parent
ROOT = HERE.parent
SUBMISSIONS = ROOT / "submissions"
DASHBOARD_HTML = HERE / "dashboard.html"
LOGS_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports"

# Edge headless is the project's standard HTML->PDF tool (see CLAUDE.md).
# Override via env var if installed elsewhere.
import os
EDGE = Path(os.environ.get("BSK_EDGE",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if sys.platform == "win32" else "msedge"))


def _setup_logging() -> logging.Logger:
    """Configure a rotating log file at logs/server.log + console echo.

    Captures every worker step and exception with full traceback so we
    can diagnose race conditions and verification failures without
    digging through the ephemeral terminal output.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "server.log"
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=4, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger = logging.getLogger("bsk")
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers when uvicorn reloads or this module is reimported.
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    logger.propagate = False
    return logger


log = _setup_logging()
log.info("BSK server starting -- log file: %s", LOGS_DIR / "server.log")

app = FastAPI(title="BSK Submission Kit")
state = State(SUBMISSIONS)

# Background verification queue. Filled by /api/submit, drained by worker().
_queue: asyncio.Queue[tuple[str, str, str, Path]] = asyncio.Queue()


def _sanitize_id(sid: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", sid.strip())[:64]
    return s or "anon"


def _retry_rename(src: Path, dst: Path, attempts: int = 8, delay: float = 0.25) -> None:
    """Rename src -> dst, retrying on Windows PermissionError.

    Windows briefly locks files via AV scanners / search indexer / process
    handles that don't release immediately. A short backoff is the
    pragmatic fix; it's the same pattern git's filesystem code uses.
    """
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            src.rename(dst)
            if i > 0:
                log.info("worker: rename %s -> %s succeeded on retry %d", src, dst, i + 1)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(delay * (2 ** min(i, 4)))
    raise last_err if last_err else RuntimeError("rename failed without exception")


@app.on_event("startup")
async def _startup() -> None:
    SUBMISSIONS.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(_worker())


async def _worker() -> None:
    """Drain the verification queue one job at a time.

    All `latest/` mutation happens here, never in the submit handler.
    Worker is serial, so the submit handler can keep accepting new
    uploads while we're still verifying an earlier one without the two
    fighting over the same directory tree.
    """
    while True:
        student_id, submission_id, project_name, incoming_zip = await _queue.get()
        log.info("worker: pulled job sid=%s project=%s submission=%s zip=%s",
                 student_id, project_name, submission_id, incoming_zip)
        try:
            if not incoming_zip.exists():
                raise FileNotFoundError(
                    f"incoming zip vanished before worker pulled it: {incoming_zip}"
                )

            state.update_submission(student_id, project_name, status="verifying")

            staging = SUBMISSIONS / student_id / f"_work_{submission_id}"
            if staging.exists():
                log.warning("worker: pre-existing staging dir, removing: %s", staging)
                shutil.rmtree(staging)
            verif_dir = staging / "verification"
            verif_dir.mkdir(parents=True)

            staged_zip = staging / "submission.zip"
            shutil.move(str(incoming_zip), str(staged_zip))
            log.info("worker: staged zip -> %s (size=%d)", staged_zip, staged_zip.stat().st_size)

            loop = asyncio.get_running_loop()
            t0 = time.time()
            result: VerificationResult = await loop.run_in_executor(
                None, verify, staged_zip, student_id, project_name, verif_dir
            )
            log.info("worker: verify finished sid=%s project=%s overall=%s in %.1fs (%s)",
                     student_id, project_name, result.overall, time.time() - t0, result.summary)

            for s in result.stages:
                (verif_dir / f"{s.name}.log").write_text(s.log or "", encoding="utf-8")
                for sc in s.scenarios:
                    safe = re.sub(r"[^A-Za-z0-9_-]", "_", sc.name)[:64]
                    (verif_dir / f"{s.name}_{safe}.log").write_text(sc.log or "",
                                                                     encoding="utf-8")

            project_safe = _sanitize_id(project_name)
            latest_dir = SUBMISSIONS / student_id / f"latest_{project_safe}"
            swap_dir = SUBMISSIONS / student_id / f"_swap_{submission_id}"
            if swap_dir.exists():
                shutil.rmtree(swap_dir)
            if latest_dir.exists():
                _retry_rename(latest_dir, swap_dir)
            _retry_rename(staging, latest_dir)
            if swap_dir.exists():
                try:
                    shutil.rmtree(swap_dir)
                except OSError as e:
                    log.warning("worker: could not remove swap dir %s: %s", swap_dir, e)
            log.info("worker: swapped staging -> %s", latest_dir)

            scenarios_by_stage = {
                s.name: [
                    {"name": r.name, "verdict": r.verdict, "note": r.note}
                    for r in s.scenarios
                ]
                for s in result.stages if s.scenarios
            }
            state.update_submission(
                student_id, project_name,
                status=result.overall,
                summary=result.summary,
                stages={s.name: s.verdict for s in result.stages},
                scenarios=scenarios_by_stage,
            )
        except Exception as e:
            log.exception("worker: CRASH sid=%s project=%s submission=%s",
                          student_id, project_name, submission_id)
            state.update_submission(
                student_id, project_name, status="fail",
                summary=f"worker crash: {type(e).__name__}: {e}",
            )
        finally:
            _queue.task_done()


@app.get("/", response_class=FileResponse)
async def root() -> FileResponse:
    if not DASHBOARD_HTML.exists():
        raise HTTPException(500, "dashboard.html missing")
    return FileResponse(DASHBOARD_HTML, media_type="text/html")


def _expected_projects() -> list[str]:
    """Project names the teacher has configured scenarios for.

    A directory under receiver/scenarios/ counts as an "expected project"
    if it contains at least one .scenario file. Sorted alphabetically.
    """
    scenarios_dir = Path(__file__).parent / "scenarios"
    if not scenarios_dir.is_dir():
        return []
    out: list[str] = []
    for child in scenarios_dir.iterdir():
        if not child.is_dir():
            continue
        if any(p.suffix == ".scenario" for p in child.iterdir() if p.is_file()):
            out.append(child.name)
    return sorted(out)


@app.get("/api/status")
async def api_status(request: Request) -> JSONResponse:
    data = state.snapshot()
    data["dashboard_url"] = str(request.url_for("root"))
    data["expected_projects"] = _expected_projects()
    return JSONResponse(data)


@app.post("/api/connect")
async def api_connect(request: Request, payload: dict) -> JSONResponse:
    sid = _sanitize_id(str(payload.get("student_id", "")))
    hostname = str(payload.get("hostname", "")).strip() or "unknown"
    presented = str(payload.get("session_token", "")).strip() or None
    if not sid:
        raise HTTPException(400, "missing student_id")

    status_, token = state.claim_name(sid, hostname, presented)
    if status_ == "conflict":
        log.warning("connect: name conflict sid=%s hostname=%s (already claimed)",
                    sid, hostname)
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": (f"Name '{sid}' is already taken on this server. "
                          "Choose another name and Connect again."),
            },
        )
    log.info("connect: %s sid=%s hostname=%s", status_, sid, hostname)
    return JSONResponse({
        "ok": True,
        "student_id": sid,
        "session_token": token,
        "dashboard_url": str(request.url_for("root")),
    })


@app.post("/api/submit")
async def api_submit(request: Request,
                     student_id: str = Form(...),
                     project_name: str = Form(...),
                     session_token: str = Form(""),
                     file: UploadFile = File(...)) -> dict:
    sid = _sanitize_id(student_id)
    if not sid:
        raise HTTPException(400, "missing student_id")
    if not session_token or not state.check_token(sid, session_token):
        log.warning("submit: rejected sid=%s reason=bad_or_missing_token", sid)
        raise HTTPException(401, f"Invalid session for '{sid}'. "
                                  f"Run 'BSK Submission / Connect' first.")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "expected a .zip upload")

    # Include project + millisecond suffix so two rapid submissions from
    # the same student (e.g. Airlock + Tunnel within the same UTC second)
    # never collide on the staging directory name.
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    ms = int((time.time() % 1) * 1000)
    project_safe = _sanitize_id(project_name)
    submission_id = f"{sid}-{project_safe}-{ts}{ms:03d}Z"

    # Stage the incoming zip OUTSIDE of latest/ so we never race against
    # the worker reading/writing latest/ for an earlier submission.
    incoming_dir = SUBMISSIONS / sid / "_incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    incoming_zip = incoming_dir / f"{submission_id}.zip"
    with incoming_zip.open("wb") as dst:
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            dst.write(chunk)

    state.touch(sid)
    state.record_submission(sid, submission_id, project_name,
                            incoming_zip.stat().st_size)
    log.info("submit: queued sid=%s project=%s submission=%s zip=%s (size=%d)",
             sid, project_name, submission_id, incoming_zip, incoming_zip.stat().st_size)

    await _queue.put((sid, submission_id, project_name, incoming_zip))

    return {
        "ok": True,
        "submission_id": submission_id,
        "queue_depth": _queue.qsize(),
        "dashboard_url": str(request.url_for("root")),
    }


def _report_filename(project_names: list[str]) -> str:
    """Build a timestamped report filename from the set of project names.

    Example: ['Airlock', 'Tunnel'] -> 'Airlock_Tunnel_20260502T123000.pdf'
    Truncated to 20 chars for the project portion if longer.
    """
    joined = "_".join(sorted(set(p for p in project_names if p))) or "Empty"
    if len(joined) > 20:
        joined = joined[:20].rstrip("_") + "_"
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    return f"{joined}_{ts}.pdf"


def _read_log(path: Path) -> str:
    if not path.exists():
        return "(no log file)"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"(failed to read log: {e})"


def _build_report_html(snapshot: dict) -> str:
    """Render the report's HTML.

    Mirrors what each clickable link on the dashboard reveals: the per-stage
    log, the per-scenario log, and the full bbatch summary, embedded as
    <pre> blocks so the resulting PDF is a self-contained verification archive.
    """
    rows = snapshot.get("students") or []
    expected = snapshot.get("expected_projects") or []
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;")
                       .replace("<", "&lt;").replace(">", "&gt;"))

    def stage_pill(name: str, verdict: str, scenarios: list[dict] | None = None) -> str:
        cls = {"ok": "ok", "partial": "partial", "fail": "fail",
               "skipped": "skipped"}.get(verdict, "pending")
        if scenarios:
            ok_count = sum(1 for s in scenarios if s.get("verdict") == "ok")
            label = f"{esc(name)}: {ok_count}/{len(scenarios)}"
        else:
            label = f"{esc(name)}: {esc(verdict)}"
        return f'<span class="pill {cls}">{label}</span>'

    def stage_chips_with_scenarios(stages: dict, scenarios: dict) -> str:
        """Render stage pills with X/Y counts AND per-scenario sub-chips."""
        out = []
        for k, v in stages.items():
            scs = scenarios.get(k) if scenarios else None
            out.append(stage_pill(k, v, scs))
        # Sub-chips per scenario, named with their verdict
        for stage_name, scs in (scenarios or {}).items():
            for s in scs:
                cls = "ok" if s.get("verdict") == "ok" else "fail"
                note = f" {s.get('note')}" if s.get("note") else ""
                out.append(f'<span class="pill {cls}" title="{esc(stage_name)}/{esc(s.get("name",""))}{esc(note)}">'
                           f'&nbsp;&nbsp;{esc(s.get("name",""))}: {esc(s.get("verdict",""))}</span>')
        return " ".join(out)

    # Top-level summary table
    summary_rows = []
    for r in rows:
        sub = r.get("last_submission") or {}
        stages = sub.get("stages") or {}
        scenarios = sub.get("scenarios") or {}
        stage_html = stage_chips_with_scenarios(stages, scenarios)
        summary_rows.append(
            f"<tr><td>{esc(r['id'])}</td>"
            f"<td>{esc(r.get('project_name','-'))}</td>"
            f"<td><span class='badge {esc(sub.get('status','-'))}'>{esc(sub.get('status','-'))}</span></td>"
            f"<td>{esc(sub.get('timestamp','-'))}</td>"
            f"<td class='stages'>{stage_html}</td></tr>"
        )

    # Per-submission detail sections
    detail_html = []
    for r in rows:
        sub = r.get("last_submission") or {}
        if not sub:
            continue
        sid = r["id"]
        project = r.get("project_name", "")
        project_safe = re.sub(r"[^A-Za-z0-9_-]", "_", project)[:64]
        verif_dir = SUBMISSIONS / sid / f"latest_{project_safe}" / "verification"

        sec = [f"<section class='detail'>"]
        sec.append(f"<h3>{esc(sid)} &mdash; {esc(project)}</h3>")
        sec.append(f"<p><b>Status:</b> <span class='badge {esc(sub.get('status','-'))}'>{esc(sub.get('status','-'))}</span> &middot; "
                   f"<b>Submitted:</b> {esc(sub.get('timestamp','-'))} &middot; "
                   f"<b>Submission ID:</b> <code>{esc(sub.get('submission_id','-'))}</code></p>")

        stages = sub.get("stages") or {}
        scenarios = sub.get("scenarios") or {}
        sec.append("<p>" + " ".join(stage_pill(k, v, scenarios.get(k)) for k, v in stages.items()) + "</p>")
        if sub.get("summary"):
            sec.append(f"<p class='mono'>{esc(sub['summary'])}</p>")

        # Embed the bbatch summary log
        sec.append("<details open><summary><b>summary.log</b> (full bbatch transcript)</summary>")
        sec.append(f"<pre>{esc(_read_log(verif_dir / 'summary.log'))}</pre></details>")

        # Per-stage logs
        for stage in ("typecheck", "pog", "prove", "animate", "bbatch"):
            log_path = verif_dir / f"{stage}.log"
            if log_path.exists():
                sec.append(f"<details><summary><b>{stage}.log</b></summary>")
                sec.append(f"<pre>{esc(_read_log(log_path))}</pre></details>")

        # Per-scenario logs (animate detail)
        scenarios = (sub.get("scenarios") or {}).get("animate") or []
        for s in scenarios:
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", s["name"])[:64]
            log_path = verif_dir / f"animate_{safe}.log"
            verdict = s.get("verdict", "?")
            note = s.get("note") or ""
            sec.append(f"<details><summary><b>animate / {esc(s['name'])}</b> &mdash; {esc(verdict)} {esc(note and ('('+note+')'))}</summary>")
            sec.append(f"<pre>{esc(_read_log(log_path))}</pre></details>")

        sec.append("</section>")
        detail_html.append("\n".join(sec))

    css = """
      body { font-family: system-ui, sans-serif; margin: 24px; color: #222; }
      h1 { font-size: 22px; margin: 0 0 4px; }
      h2 { font-size: 18px; margin-top: 28px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
      h3 { font-size: 15px; margin-top: 22px; }
      .meta { color: #666; font-size: 12px; }
      table.summary { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 12px; }
      table.summary th, table.summary td { border: 1px solid #e0e0e0; padding: 6px 8px; text-align: left; vertical-align: top; }
      table.summary th { background: #f3f5fa; }
      .pill { display: inline-block; font-size: 10px; margin: 1px 3px 1px 0; padding: 1px 6px; border-radius: 8px; background: #eee; color: #444; }
      .pill.ok { background: #dff0dd; color: #1a5a2a; }
      .pill.partial { background: #fdecc8; color: #7a4a10; }
      .pill.fail { background: #fadede; color: #8a1e1e; }
      .pill.skipped { background: #eceff4; color: #556; font-style: italic; }
      .badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; color: #fff; background: #888; }
      .badge.ok { background: #2e9e4a; }
      .badge.partial { background: #e0a030; }
      .badge.fail { background: #c44040; }
      .badge.verifying { background: #3a76d6; }
      .badge.queued { background: #888; }
      pre { background: #f6f8fa; padding: 10px; border-radius: 6px; font-family: ui-monospace, Consolas, monospace; font-size: 11px; white-space: pre-wrap; word-break: break-word; max-height: 600px; overflow: auto; border: 1px solid #e0e0e0; }
      details { margin: 6px 0; }
      details > summary { cursor: pointer; font-size: 12px; color: #444; padding: 3px 0; }
      .mono { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #666; }
      section.detail { page-break-inside: avoid; margin-bottom: 18px; }
      @media print {
        details { open: true; }
        details > summary { display: none; }
        pre { max-height: none; }
      }
    """

    proj_list = ", ".join(expected) or "(none)"
    n_subs = sum(1 for r in rows if r.get("last_submission"))
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>BSK Verification Report &mdash; {ts}</title>
<style>{css}</style></head><body>
<h1>BSK Verification Report</h1>
<div class="meta">
  Generated {ts} &middot; expected projects: {esc(proj_list)} &middot; submissions: {n_subs}
</div>

<h2>Summary</h2>
<table class="summary">
<thead><tr><th>Student</th><th>Project</th><th>Overall</th><th>Submitted (UTC)</th><th>Stages</th></tr></thead>
<tbody>{''.join(summary_rows) or '<tr><td colspan=5>(no submissions)</td></tr>'}</tbody>
</table>

<h2>Detailed verifications</h2>
{''.join(detail_html) or '<p>(no submission details)</p>'}

</body></html>
"""


def _html_to_pdf(html_path: Path, pdf_path: Path, timeout: float = 60) -> None:
    """Render html_path -> pdf_path via Edge headless."""
    if not EDGE.exists():
        raise FileNotFoundError(f"Edge browser not found at {EDGE}; "
                                 "set BSK_EDGE to msedge.exe path")
    cmd = [
        str(EDGE),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        f"file:///{html_path.as_posix()}",
    ]
    log.info("report: rendering pdf via Edge: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if not pdf_path.exists():
        raise RuntimeError(f"Edge did not produce PDF; stderr: {proc.stderr[:500]}")


@app.post("/api/report")
async def api_report(request: Request) -> dict:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = state.snapshot()
    project_names = []
    for r in snapshot["students"]:
        p = r.get("project_name")
        if p and p != "(none)":
            project_names.append(p)
    fname = _report_filename(project_names)
    pdf_path = REPORTS_DIR / fname
    html_path = REPORTS_DIR / (fname.replace(".pdf", ".html"))

    html = _build_report_html({**snapshot, "expected_projects": _expected_projects()})
    html_path.write_text(html, encoding="utf-8")
    log.info("report: wrote html -> %s (%d bytes)", html_path, html_path.stat().st_size)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _html_to_pdf, html_path, pdf_path)
    except Exception as e:
        log.exception("report: pdf rendering failed")
        return {
            "ok": False,
            "error": str(e),
            "html_url": f"/reports/{html_path.name}",
        }

    log.info("report: wrote pdf -> %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
    return {
        "ok": True,
        "filename": fname,
        "pdf_url": f"/reports/{fname}",
        "html_url": f"/reports/{html_path.name}",
    }


@app.get("/reports/{filename}")
async def api_report_file(filename: str):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:200]
    path = REPORTS_DIR / safe
    if not path.exists():
        raise HTTPException(404, f"no such report: {safe}")
    media_type = "application/pdf" if safe.endswith(".pdf") else "text/html"
    return FileResponse(path, media_type=media_type, filename=safe)


@app.get("/api/student/{sid}/log")
async def api_student_log(sid: str, stage: str = "summary",
                           project: str = "") -> PlainTextResponse:
    sid = _sanitize_id(sid)
    stage_safe = re.sub(r"[^A-Za-z0-9_-]", "", stage)[:64] or "summary"
    project_safe = _sanitize_id(project) if project else ""
    candidate_dirs = []
    if project_safe:
        candidate_dirs.append(SUBMISSIONS / sid / f"latest_{project_safe}" / "verification")
    # Legacy fallback for state from before the per-project refactor.
    candidate_dirs.append(SUBMISSIONS / sid / "latest" / "verification")
    for d in candidate_dirs:
        log_path = d / f"{stage_safe}.log"
        if log_path.exists():
            return PlainTextResponse(log_path.read_text(encoding="utf-8", errors="replace"))
    raise HTTPException(404, f"no {stage_safe} log for {sid}"
                             + (f" / {project_safe}" if project_safe else ""))
