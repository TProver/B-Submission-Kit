"""Verification pipeline for BSK submissions.

FIRST-SHOT IMPLEMENTATION. Teachers are expected to edit this file per
classroom session, possibly with Claude's help, to match the specific
success criteria for the exercise being taught.

Current criteria (per user decision 2026-04-23):
  - typecheck succeeds for every component
  - POG succeeds for every component
  - prove with force 0 leaves no unproved obligations

The file is structured so a teacher can:
  - swap in different bbatch commands,
  - add a ProB animation stage,
  - add a C-code compilation-and-test stage,
  - or gate on component-name specific criteria,
without touching server.py or state.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# -------- Configuration --------------------------------------------------- #

BBATCH = Path(os.environ.get("BSK_BBATCH",
    r"C:\Program Files\Atelier B Community Edition 24.04.2 24.04.2\bin\bbatch.exe"
    if sys.platform == "win32" else "bbatch"))

PROBCLI = Path(os.environ.get("BSK_PROBCLI",
    r"C:\Tools\ProB\probcli.exe" if sys.platform == "win32" else "probcli"))

SERVER_WORKSPACE = Path(os.environ.get("BSK_WORKSPACE",
    str(Path(__file__).parent.parent / "server_workspace"))).resolve()

SCENARIOS_DIR = Path(os.environ.get("BSK_SCENARIOS",
    str(Path(__file__).parent / "scenarios"))).resolve()

COMPONENT_EXTS = (".mch", ".ref", ".imp")

# Timeout per bbatch invocation (seconds).
BBATCH_TIMEOUT = 300

# Timeout for a single ProB animation invocation (seconds).
# probcli's SICStus cold-start can eat ~20 s on its own; the actual
# trace-replay walltime is typically <1 s after that, so 30 s is a
# safety margin while still bounding worst-case animation time
# (5 scenarios x 30 s = 150 s per submission worst case).
PROBCLI_TIMEOUT = 30


# -------- Result types ---------------------------------------------------- #

@dataclass
class ScenarioResult:
    name: str
    verdict: str            # "ok" | "fail"
    note: str = ""          # short fail reason (e.g. "ko at line 3 (op_X)")
    log: str = ""           # full per-scenario log

@dataclass
class StageResult:
    name: str
    verdict: str            # "ok" | "fail" | "skipped"
    log: str = ""
    scenarios: list[ScenarioResult] = field(default_factory=list)  # used by animate

@dataclass
class VerificationResult:
    overall: str                          # "ok" | "fail"
    summary: str
    stages: list[StageResult] = field(default_factory=list)
    raw_log: str = ""


# -------- Pipeline -------------------------------------------------------- #

def verify(submission_zip: Path, student_id: str, project_name: str,
           workdir: Path) -> VerificationResult:
    """Entry point called by the server's background worker.

    Arguments:
        submission_zip: path to the zip uploaded by the student.
        student_id:     sanitized student identifier.
        project_name:   name of the Atelier B project (as the student has it).
        workdir:        writable directory for this verification run
                        (the server puts per-submission artefacts under
                        submissions/<sid>/latest/verification/).

    Returns a VerificationResult. Side-effects are confined to:
      - workdir   (per-submission logs),
      - SERVER_WORKSPACE (shared server-side Atelier B workspace).
    """
    stages: list[StageResult] = []
    workdir.mkdir(parents=True, exist_ok=True)
    extracted = workdir / "extracted"
    extracted.mkdir(exist_ok=True)

    # 1. Extract the submission.
    try:
        with zipfile.ZipFile(submission_zip) as zf:
            zf.extractall(extracted)
    except Exception as e:
        return VerificationResult("fail", f"zip extract failed: {e}",
                                  [StageResult("extract", "fail", str(e))])

    # 2. Locate B components in the extracted tree.
    components = _find_components(extracted)
    if not components:
        return VerificationResult("fail", "no B components (.mch/.ref/.imp) found in submission",
                                  [StageResult("extract", "fail", "no components")])

    # 3. Build the bbatch command script.
    # Project name is unique per submission so repeated submissions from the same
    # student don't collide with a stale registration pointing at a now-deleted path.
    import time
    ts_short = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    bsk_project = f"bsk_{student_id}_{ts_short}"
    project_root = SERVER_WORKSPACE / bsk_project
    project_bdp = project_root / "bdp"
    project_lang = project_root / "lang"
    project_bdp.mkdir(parents=True, exist_ok=True)
    project_lang.mkdir(parents=True, exist_ok=True)

    # bbatch command script. This is where a teacher customizes the pipeline.
    # NOTE: crp takes 4 path args: <name> <bdp_dir> <lang_dir> <type>.
    # The third arg is the translation-output directory, not a language code.
    # "m <action>" runs the action on every component in the project (make-all).
    # "po" and "pr" each require a force argument (0=auto). Without it bbatch
    # aborts with "missing argument number 3".
    commands = [
        f"crp {bsk_project} {project_bdp} {project_lang} SOFTWARE",
        f"op {bsk_project}",
    ] + [f"af {c}" for c in components] + [
        "m t",
        "m po 0",
        "m pr 0",
        "sg",
        "clp",
        "q",
    ]
    script = "\n".join(commands) + "\n"
    script_path = workdir / "bbatch_commands.txt"
    script_path.write_text(script, encoding="utf-8")

    # 4. Run bbatch. Capture stdout directly (do NOT use -f=, because
    # bbatch does not flush the -f file when it aborts on an earlier
    # command, which leaves us with a useless empty log).
    try:
        proc = subprocess.run(
            [str(BBATCH), f"-i={script_path}"],
            capture_output=True, text=True, timeout=BBATCH_TIMEOUT,
        )
        raw = (proc.stdout or "")
        if proc.stderr:
            raw += "\n--- stderr ---\n" + proc.stderr
    except subprocess.TimeoutExpired as e:
        return VerificationResult("fail", f"bbatch timed out after {BBATCH_TIMEOUT}s",
                                  [StageResult("bbatch", "fail", str(e))])
    except Exception as e:
        return VerificationResult("fail", f"bbatch failed to launch: {e}",
                                  [StageResult("bbatch", "fail", str(e))])

    # 5. Parse the bbatch output into per-stage verdicts.
    stages = _parse_output(raw)
    (workdir / "summary.log").write_text(raw, encoding="utf-8")

    # 6. ProB animation stage; only runs when prove actually succeeded.
    # If an earlier bbatch stage aborted (fail or skipped), the project
    # is in a bad state and ProB would just produce a less-informative error.
    prove_stage = next((s for s in stages if s.name == "prove"), None)
    if prove_stage and prove_stage.verdict == "ok":
        animate_stage = _animate(components, project_name, workdir)
        stages.append(animate_stage)
    else:
        stages.append(StageResult("animate", "skipped",
                                  "prove did not succeed; skipping animation"))

    overall = _overall_verdict(stages)
    summary = ", ".join(_summarise_stage(s) for s in stages)
    return VerificationResult(overall, summary, stages, raw_log=raw)


def _overall_verdict(stages: list[StageResult]) -> str:
    """Roll up stage verdicts into an overall classification.

    Rules (per user 2026-05-02):
      - "ok"      = every stage succeeded
      - "fail"    = no stage succeeded (all fail or skipped)
      - "partial" = at least one stage succeeded AND at least one did not
    """
    if not stages:
        return "fail"
    oks = sum(1 for s in stages if s.verdict == "ok")
    if oks == len(stages):
        return "ok"
    if oks == 0:
        return "fail"
    return "partial"


def _summarise_stage(s: StageResult) -> str:
    """One short token per stage for the overall summary line."""
    base = f"{s.name}:{s.verdict}"
    if s.scenarios:
        passed = sum(1 for r in s.scenarios if r.verdict == "ok")
        total = len(s.scenarios)
        token = f"{passed}/{total} passed"
        failed = [r.name for r in s.scenarios if r.verdict != "ok"]
        if failed:
            token += f"; failed: {', '.join(failed)}"
        return f"{base} ({token})"
    if s.verdict == "fail" and s.log:
        m = re.search(r"ko at (?:scenario line \d+ \([^)]+\)|step \d+ of \d+(?:; failing op: \S+)?)", s.log)
        if m:
            return f"{base} ({m.group(0)})"
    return base


# -------- Helpers (teacher-replaceable) ----------------------------------- #

def _find_components(root: Path) -> list[str]:
    """Return absolute paths to the authored .mch/.ref/.imp files under root.

    Atelier B projects carry several copies of each component:
      - <project>/src/Foo.mch            <- author-edited (we want this one)
      - <project>/bdp/src/Foo.mch        <- auto-managed copy under bdp/
      - <project>/bdp/expand_src/Foo.mch <- expanded / preprocessed form

    We skip everything under a bdp/ directory, then deduplicate by stem so
    that at most one copy of each component name survives.
    """
    candidates: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in COMPONENT_EXTS:
            continue
        if any(part.lower() == "bdp" for part in p.parts):
            continue
        candidates.append(p.resolve())
    # Dedup by stem, prefer the shortest path (closer to the project root).
    by_stem: dict[str, Path] = {}
    for p in sorted(candidates, key=lambda q: (len(q.parts), str(q))):
        by_stem.setdefault(p.stem, p)
    return [str(p) for p in sorted(by_stem.values())]


def _guess_main_component(component_paths: list[str]) -> str:
    """Kept for backward compat. With m-all commands we no longer pick one."""
    machines = [p for p in component_paths if p.lower().endswith(".mch")]
    pick = (machines or component_paths)[0]
    return Path(pick).stem


def _parse_output(raw: str) -> list[StageResult]:
    """Extract per-stage verdicts from bbatch output.

    Strategy: parse the `sg` (global status) table at the end of the run.
    That table summarizes TC / POG / prove stats per component, so we don't
    have to guess from keywords. Also detect "Interpretation aborted" which
    means an earlier command failed hard.

    Teachers who want different criteria can override this function -- for
    instance, require 100%% proof coverage, or gate on specific components.
    """
    stages: list[StageResult] = []

    # Detect mid-pipeline abort and diagnose per-stage from content markers.
    abort_match = re.search(r"Interpretation aborted at line (\d+)", raw)
    if abort_match:
        line_no = int(abort_match.group(1))
        abort_note = f"aborted at command line {line_no}"

        # typecheck: each "Type Checking machine|implementation|refinement X"
        # block ends with "End of Type checking" when successful.
        tc_starts = len(re.findall(r"^Type Checking (?:machine|implementation|refinement) ", raw, re.M))
        tc_ends = raw.count("End of Type checking")
        if "TYPECHECKING FAILED" in raw:
            tc_v = "fail"
        elif tc_starts == 0:
            tc_v = "skipped"
        elif tc_starts == tc_ends:
            tc_v = "ok"
        else:
            tc_v = "fail"

        # POG: "Pog generation..." starts a POG; "PO Generate error" fails it.
        pog_started = "Pog generation" in raw
        pog_error = "PO Generate error" in raw or "POG FAILED" in raw
        pog_v = "fail" if pog_error else ("ok" if pog_started else "skipped")

        # Prove: "Proving <name>" or "Proof pass" indicates prove ran at all.
        pr_started = bool(re.search(r"^Proving \S", raw, re.MULTILINE)) or "Proof pass" in raw
        pr_v = "ok" if pr_started else "skipped"

        stages.append(StageResult("bbatch",    "fail", abort_note))
        stages.append(StageResult("typecheck", tc_v, abort_note))
        stages.append(StageResult("pog",       pog_v, abort_note))
        stages.append(StageResult("prove",     pr_v, abort_note))
        return stages

    # Parse the final TOTAL row of the global status table.
    # Row looks like: | TOTAL | OK | OK  |   1 |   1 |   0 | ...
    row_re = re.compile(
        r"\|\s*TOTAL\s*\|\s*([A-Z\- ]+?)\s*\|\s*([A-Z\- ]+?)\s*\|"
        r"\s*(\d*)\s*\|\s*(\d*)\s*\|\s*(\d*)\s*\|"
    )
    m = row_re.search(raw)
    if not m:
        # bbatch ran but we couldn't find the status table -- probably a
        # partial success, surface the raw log.
        stages.append(StageResult("typecheck", "fail", "no status table in output"))
        stages.append(StageResult("pog",       "fail", ""))
        stages.append(StageResult("prove",     "fail", ""))
        return stages

    tc_total, pog_total, n_po, n_un, pct = m.groups()

    def verdict(flag: str) -> str:
        return "ok" if flag.strip().upper() == "OK" else "fail"

    tc_v  = verdict(tc_total)
    pog_v = verdict(pog_total)
    # Prove verdict: "prove actionable" = the command ran (no abort).
    # We count the unproved POs as context for the teacher.
    try:
        n_po_i = int(n_po) if n_po else 0
        n_un_i = int(n_un) if n_un else 0
    except ValueError:
        n_po_i, n_un_i = 0, 0
    prove_v = "ok"  # we already ruled out abort above
    prove_note = f"{n_po_i} POs generated, {n_un_i} unproved ({pct or '-'}% proved)"

    # Attach the full per-component table as the log payload so the
    # dashboard "Log" link shows everything useful.
    table = _extract_status_table(raw)
    stages.append(StageResult("typecheck", tc_v, table))
    stages.append(StageResult("pog",       pog_v, table))
    stages.append(StageResult("prove",     prove_v, prove_note + "\n\n" + table))
    return stages


def _extract_status_table(raw: str) -> str:
    """Return the ASCII status table printed by `sg`, or empty string."""
    m = re.search(r"(Project status\s*\n(?:\+.*\n|\|.*\n)+)", raw)
    return m.group(1) if m else ""


# -------- ProB animation stage -------------------------------------------- #

def _pick_animation_target(components: list[str]) -> Path | None:
    """Pick one component to animate: prefer an implementation, else a machine.

    Convention: if any .imp is present, animate it (the refined, executable form).
    Otherwise animate a .mch -- the abstract spec. Among multiple candidates,
    pick the shortest stem (heuristic for "main" machine like "Airlock" over
    "Airlock_pressure_bs").
    """
    imps = [Path(p) for p in components if p.lower().endswith(".imp")]
    if imps:
        return sorted(imps, key=lambda p: (len(p.stem), p.stem))[0]
    mchs = [Path(p) for p in components if p.lower().endswith(".mch")]
    if mchs:
        return sorted(mchs, key=lambda p: (len(p.stem), p.stem))[0]
    return None


MAX_SCENARIOS_PER_TARGET = 5


def _scenario_lines(path: Path) -> list[str]:
    """Read a scenario file and return its non-comment / non-blank lines."""
    ops: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        ops.append(s)
    return ops


def _load_scenarios(project_name: str, target_stem: str) -> list[tuple[str, list[str]]]:
    """Load up to MAX_SCENARIOS_PER_TARGET teacher-written scenarios.

    Configuration is keyed by **project name** (the canonical name students
    are required to use). The lookup falls back to the older target-stem
    layouts so existing setups keep working until migrated.

    Lookup order (first non-empty wins):
      1. scenarios/<project_name>/*.scenario       (preferred)
      2. scenarios/<project_name>.scenario         (single anonymous scenario)
      3. scenarios/<target_stem>/*.scenario        (legacy stem-keyed dir)
      4. scenarios/<target_stem>.scenario          (oldest legacy single file)

    Returns: list of (scenario_name, ops_list) in deterministic order.
    Empty list if no scenarios are configured.
    """
    for dir_key in (project_name, target_stem):
        d = SCENARIOS_DIR / dir_key
        if d.is_dir():
            files = sorted(p for p in d.iterdir() if p.suffix == ".scenario")
            collected: list[tuple[str, list[str]]] = []
            for p in files[:MAX_SCENARIOS_PER_TARGET]:
                ops = _scenario_lines(p)
                if ops:
                    collected.append((p.stem, ops))
            if collected:
                return collected
    for file_key in (project_name, target_stem):
        f = SCENARIOS_DIR / f"{file_key}.scenario"
        if f.exists():
            ops = _scenario_lines(f)
            if ops:
                return [("default", ops)]
    return []


_OP_WITH_ARGS_RE = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\s*"        # operation name
    r"(?:\(\s*(.*?)\s*\))?\s*"          # optional ( args )
    r"(?:->\s*(.+?))?\s*$"              # optional  -> returns
)


def _convert_scalar_arg(arg: str) -> str:
    """Wrap a teacher-written argument in the ProB Prolog term form.

    Supported:
      - integers (`42`, `-3`)                 -> `int(42)`, `int(-3)`
      - booleans (`TRUE`/`FALSE`/`true`/...)  -> `bool_true` / `bool_false`
      - quoted string (`'foo'`)               -> passed through verbatim
      - anything else                         -> passed through verbatim
        (lets a power-user teacher embed raw ProB terms like
        `avl_set(node(...))` or `fd(1,'Persons')` directly)
    """
    a = arg.strip()
    upper = a.upper()
    if upper in ("TRUE", "T"):
        return "bool_true"
    if upper in ("FALSE", "F"):
        return "bool_false"
    try:
        n = int(a)
        return f"int({n})"
    except ValueError:
        return a


def _scenario_to_trace(target_stem: str, ops: list[str]) -> str:
    """Convert a plain-text scenario to a Prolog-format ProB trace file.

    Line forms supported:
      - `setup_constants(100)`          -> `'$setup_constants'(int(100)).`
      - `setup_constants(100, TRUE)`    -> `'$setup_constants'(int(100), bool_true).`
      - `init`                          -> `'$initialise_machine'.`
      - `init(0)`                       -> `'$initialise_machine'(int(0)).`
      - `op_name`                       -> `'op_name'.`
      - `op_name()`                     -> `'op_name'.`
      - `op_name(3)`                    -> `'op_name'(int(3)).`
      - `op_name(3, TRUE)`              -> `'op_name'(int(3), bool_true).`
      - `op_name(avl_set(...))`         -> passed through as-is (power user)

    Use `setup_constants(...)` as the very first line for machines that
    have a CONCRETE_CONSTANTS clause; otherwise ProB's trace-replay
    refuses to initialise.

    Output (return) values, signalled by `->`:
      - `get_int -> 5`                  -> `'get_int'-->[int(5)].`
      - `op_pow(3) -> 8`                -> `'op_pow'(int(3))-->[int(8)].`
      - `get_all_values -> 7, 3`        -> `'get_all_values'-->[int(7),int(3)].`
      - `get_state -> TRUE, 0`          -> `'get_state'-->[bool_true,int(0)].`

    A line without `->` does not assert any return; ProB will fire the op
    but won't compare its outputs against an expected value.
    """
    lines = [f"machine('{target_stem}')."]
    for op in ops:
        m = _OP_WITH_ARGS_RE.match(op)
        if not m:
            # Unrecognized line: emit verbatim with a period so ProB sees it.
            lines.append(op.rstrip(".") + ".")
            continue
        name, argstr, retstr = m.group(1), m.group(2), m.group(3)
        if name.lower() in ("init", "initialise_machine", "$initialise_machine"):
            prolog_name = "$initialise_machine"
        elif name.lower() in ("setup_constants", "$setup_constants"):
            prolog_name = "$setup_constants"
        else:
            prolog_name = name
        # Build call form: name or name(args)
        if not argstr:
            call = f"'{prolog_name}'"
        else:
            args = [_convert_scalar_arg(a) for a in _split_top_level_commas(argstr)]
            call = f"'{prolog_name}'({', '.join(args)})"
        # Append return list when present.
        if retstr:
            rets = [_convert_scalar_arg(r) for r in _split_top_level_commas(retstr)]
            lines.append(f"{call}-->[{','.join(rets)}].")
        else:
            lines.append(f"{call}.")
    return "\n".join(lines) + "\n"


def _split_top_level_commas(s: str) -> list[str]:
    """Split by commas at nesting depth 0, so that nested terms like
    `avl_set(node(a,b))` stay intact as a single argument."""
    depth = 0
    out: list[str] = []
    buf: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _probcli_has_errors(output: str) -> tuple[bool, str]:
    """Apply the canonical probcli error detection from the interaction guide.

    When a trace-replay fails, try to extract:
      - `OPERATION:<name>` from the "ERROR CONTEXT" line, and
      - `replayed N/M operations` from the "Trace Checking was not successful" line,
    so the caller can tell the teacher exactly where the scenario diverged.
    """
    failing_op = None
    replayed: tuple[int, int] | None = None

    for line in output.splitlines():
        m = re.search(r"OPERATION:([A-Za-z_$][\w$]*)", line)
        if m:
            failing_op = m.group(1)
        m = re.search(r"replayed\s+(\d+)\s*/\s*(\d+)\s+operations", line)
        if m:
            replayed = (int(m.group(1)), int(m.group(2)))

    markers = [
        "Total Errors:",
        "Loading Specification Failed",
        "parse_error",
        "type_expression_error",
        "Replay Error",
        "replay failed",
        "Invariant violation",
        "ERROR: ",
        "Trace Checking was not successful",
    ]
    for m in markers:
        if m in output:
            if failing_op or replayed:
                parts = []
                if replayed:
                    parts.append(f"ko at step {replayed[0] + 1} of {replayed[1]}")
                if failing_op:
                    parts.append(f"failing op: {failing_op}")
                return True, "; ".join(parts)
            return True, f"found marker '{m}'"
    for line in output.splitlines():
        if line.startswith("!") and "enumeration_warning" not in line:
            return True, f"probcli '!' line: {line[:140]}"
    return False, ""


def _run_one_scenario(target: Path, scenario_name: str, ops: list[str],
                      workdir: Path) -> ScenarioResult:
    """Run a single scenario via probcli -trace_replay. 8 s wall-clock cap."""
    trace_path = workdir / f"{target.stem}__{scenario_name}.trace"
    trace_path.write_text(_scenario_to_trace(target.stem, ops), encoding="utf-8")
    cmd = [str(PROBCLI), str(target), "-trace_replay", "prolog", str(trace_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=PROBCLI_TIMEOUT)
        output = (proc.stdout or "") + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else "")
    except subprocess.TimeoutExpired:
        return ScenarioResult(scenario_name, "fail",
                              f"timed out after {PROBCLI_TIMEOUT}s",
                              f"command: {' '.join(cmd)}\n\nTIMEOUT after {PROBCLI_TIMEOUT}s")
    except Exception as e:
        return ScenarioResult(scenario_name, "fail", f"probcli error: {e}",
                              f"command: {' '.join(cmd)}\n\n{e}")

    has_err, reason = _probcli_has_errors(output)
    note = ""
    if has_err:
        # Map the failing op name back to the teacher's 1-indexed scenario line.
        m = re.search(r"failing op:\s*(\S+)", reason)
        failing_op = m.group(1) if m else None
        if failing_op:
            for i, op_line in enumerate(ops, start=1):
                op_name = re.match(r"\s*([A-Za-z_$][\w$]*)", op_line)
                if op_name and (op_name.group(1) == failing_op
                                or (failing_op == "INITIALISATION"
                                    and op_name.group(1).lower() in ("init", "initialise_machine"))):
                    note = f"ko at line {i} ({failing_op})"
                    break
        if not note:
            note = reason
    full_log = (f"scenario: {scenario_name}\ncommand: {' '.join(cmd)}\n"
                f"steps: {len(ops)}\n\n{output}")
    if has_err:
        full_log += f"\n\n--- error detected: {note or reason} ---\n"
    return ScenarioResult(scenario_name,
                          "fail" if has_err else "ok",
                          note,
                          full_log)


def _animate(components: list[str], project_name: str, workdir: Path) -> StageResult:
    """Run a ProB animation stage with up to MAX_SCENARIOS_PER_TARGET scenarios.

    Behaviour:
      - Pick a target (implementation preferred, then machine).
      - Load all configured scenarios for that target's stem.
      - Run each scenario in turn via probcli -trace_replay; per-scenario cap.
      - Verdict: ok if every scenario passed; fail if any failed; skipped if none.
    """
    if not PROBCLI.exists():
        return StageResult("animate", "skipped",
                           f"probcli not found at {PROBCLI}; set BSK_PROBCLI to override")

    target = _pick_animation_target(components)
    if target is None:
        return StageResult("animate", "skipped", "no .imp or .mch to animate")

    scenarios = _load_scenarios(project_name, target.stem)
    if not scenarios:
        return StageResult("animate", "skipped",
                           f"no scenarios configured for project '{project_name}' "
                           f"(target {target.name}); drop .scenario files into "
                           f"scenarios/{project_name}/")

    results: list[ScenarioResult] = []
    for name, ops in scenarios:
        results.append(_run_one_scenario(target, name, ops, workdir))

    passed = sum(1 for r in results if r.verdict == "ok")
    total = len(results)
    if passed == total:
        overall = "ok"
    elif passed == 0:
        overall = "fail"
    else:
        overall = "partial"
    failed_names = [r.name for r in results if r.verdict != "ok"]
    summary = f"target: {target.name}\nscenarios: {passed}/{total} passed"
    if failed_names:
        summary += f"\nfailed: {', '.join(failed_names)}"
    full_log = summary + "\n\n" + "\n\n".join(
        f"=== {r.name}: {r.verdict} ===\n{r.note}\n{r.log}" for r in results
    )
    return StageResult("animate", overall, full_log, scenarios=results)
