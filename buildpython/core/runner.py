from __future__ import annotations

import fcntl
import importlib.util
import shutil
import time
import traceback
from dataclasses import replace
from uuid import uuid4

from ..steps.coverage_step.constants import _CAPTURE_MARKER_NAME
from ..utils.log_format import iso_now
from ..utils.paths import buildlog_dir
from ..utils.subproc import RunResult
from . import summary as summary_module
from .debt_index import write_debt_index
from .model import Step, StepOutcome
from .runner_support import display as _ui
from .runner_support import health, reports
from .summary_support.common import read_json_if_exists

_REQUIRED_MODULES = {
    "Ruff": ("ruff",),
    "Ruff Format": ("ruff",),
    "Type Check": ("pyright",),
}
_OPTIONAL_MODULES = {
    "Coverage": ("coverage", "pytest"),
    "Dead Code": ("vulture",),
}


def _is_module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _abort_exit_code(exc: BaseException) -> int:
    if isinstance(exc, KeyboardInterrupt):
        return 130
    if isinstance(exc, SystemExit):
        return exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    return 1


def run_step(
    step: Step,
    *,
    index: int,
    total_steps: int,
    name_width: int,
    label_width: int,
    verbose: bool,
    compact_output: bool,
    skip_reason: str = "",
) -> StepOutcome:
    start = time.monotonic()
    _ui._print_step_header(
        step, index=index, total_steps=total_steps, name_width=name_width, label_width=label_width
    )
    required = step.name in _REQUIRED_MODULES
    modules = _REQUIRED_MODULES.get(step.name, _OPTIONAL_MODULES.get(step.name, ()))
    missing = [module for module in modules if not _is_module_available(module)]
    if step.name == "ShellCheck" and shutil.which("shellcheck") is None:
        missing.append("shellcheck")
    if missing or skip_reason:
        reason = skip_reason or f"{', '.join(missing)} not installed"
        status = "failure" if required else "skipped"
        exit_code = 1 if required else 0
        duration = time.monotonic() - start
        _ui._write_log(
            step, "(not executed)", reason + "\n", "", exit_code, duration, status=status
        )
        outcome = StepOutcome(
            status=status,
            exit_code=exit_code,
            duration_s=duration,
            message=reason,
            highlights=(reason,),
        )
        if not compact_output:
            _ui._print_step_footer(outcome, list(outcome.highlights))
        return outcome

    report_name = reports.STEP_REPORTS.get(step.name)
    before = reports.report_stamp(buildlog_dir() / report_name) if report_name else None
    # Replace an old successful log before invoking a runner that may abort.
    _ui._write_log(step, "(runner starting)", "", "", None, 0, status="running")
    message = ""
    try:
        result = step.runner()
    except (KeyboardInterrupt, SystemExit) as exc:
        _ui._write_log(
            step,
            "(runner aborted)",
            "",
            traceback.format_exc(),
            _abort_exit_code(exc),
            time.monotonic() - start,
            status="aborted",
        )
        raise
    except Exception as exc:
        message = f"Runner raised {type(exc).__name__}: {exc}"
        result = RunResult("(runner failed)", "", traceback.format_exc(), 1)
    if required and result.skip_reason:
        message = f"Required check was not executed: {result.skip_reason}"
        result = replace(
            result, exit_code=result.exit_code or 1, stderr=result.stderr + f"\n{message}\n"
        )
    duration = time.monotonic() - start
    status = "failure" if result.exit_code else "skipped" if result.skip_reason else "success"
    report_names = (
        () if status == "skipped" else reports.refreshed_reports(buildlog_dir(), step.name, before)
    )
    if (
        status == "success"
        and report_name
        and (not report_names or read_json_if_exists(buildlog_dir() / report_name) is None)
    ):
        result = replace(
            result,
            exit_code=1,
            stderr=result.stderr
            + f"\nExpected fresh JSON report was not produced: {report_name}\n",
        )
        status = "failure"
        report_names = ()
    _ui._write_log(
        step,
        result.command_str,
        result.stdout,
        result.stderr,
        result.exit_code,
        duration,
        status=status,
    )
    highlights = (
        [result.skip_reason]
        if status == "skipped"
        else _ui._step_highlights(
            step, stdout=result.stdout, stderr=result.stderr, report_names=report_names
        )
    )
    if result.stderr.strip() and not highlights:
        highlights.append(f"Diagnostics on stderr; see {step.log_file}")
    outcome = StepOutcome(
        status=status,
        exit_code=result.exit_code,
        duration_s=duration,
        message=message or result.skip_reason,
        highlights=tuple(highlights),
        report_names=report_names,
        health=None
        if status == "skipped"
        else health.build_step_health(
            step.name,
            stdout=result.stdout,
            stderr=result.stderr,
            report_dir=buildlog_dir(),
            report_names=report_names,
            failed=status == "failure",
        ),
    )
    if not compact_output:
        _ui._print_step_footer(outcome, highlights)
    if verbose:
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if result.stderr.strip():
            print(result.stderr.rstrip())
    return outcome


def _completed_run_exit_code(summaries: list[summary_module.StepSummary]) -> int:
    for step in summaries:
        if step.status == "failure":
            return step.exit_code or 1
    return 0


def run(steps: list[Step], *, verbose: bool, continue_on_error: bool) -> int:
    report_dir = buildlog_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / ".buildpython.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"Build not started: another buildpython run owns {report_dir}.")
            return 2
        return _run_locked(steps, verbose=verbose, continue_on_error=continue_on_error)


def _run_locked(steps: list[Step], *, verbose: bool, continue_on_error: bool) -> int:
    total_steps = len(steps)
    name_width = max((len(step.name) for step in steps), default=7)
    label_width = len(f"[{total_steps}/{total_steps}]")
    report_dir = buildlog_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    # Coverage must come from a successful pytest invocation in this build.
    (report_dir / _CAPTURE_MARKER_NAME).unlink(missing_ok=True)
    print(f"Naga Control Build | {total_steps} selected steps | Logs in {report_dir}")
    started = time.monotonic()
    run_id = str(uuid4())
    started_at = iso_now()
    summaries: list[summary_module.StepSummary] = []
    report_names: list[str] = []

    def snapshot(
        *, completed: bool, running_step: Step | None = None
    ) -> summary_module.BuildSummary:
        pending = [
            summary_module.StepSummary(
                number=step.number,
                name=step.name,
                status="not_run",
                exit_code=None,
                duration_s=0,
                message="Not executed in this run",
            )
            for step in steps[len(summaries) :]
        ]
        if running_step is not None:
            pending[0] = summary_module.StepSummary(
                number=running_step.number,
                name=running_step.name,
                status="running",
                exit_code=None,
                duration_s=0,
                message="Started; no final outcome recorded",
                log_file=str(running_step.log_file),
            )
        return summary_module.BuildSummary(
            total_duration_s=time.monotonic() - started,
            steps=[*summaries, *pending],
            completed=completed,
            run_id=run_id,
            started_at=started_at,
            report_names=tuple(report_names),
        )

    # An interrupted run must never leave the previous build's PASS summary current.
    write_debt_index(report_dir, report_names=())
    summary_module.write_summary(report_dir, snapshot(completed=False))
    for index, step in enumerate(steps, start=1):
        summary_module.write_summary(report_dir, snapshot(completed=False, running_step=step))
        skip_reason = ""
        if step.name == "AppImage Smoke" and any(
            s.name == "AppImage" and s.status != "success" for s in summaries
        ):
            skip_reason = "AppImage build did not complete in this run; refusing to smoke-test an older artifact"
        outcome = run_step(
            step,
            index=index,
            total_steps=total_steps,
            name_width=name_width,
            label_width=label_width,
            verbose=verbose,
            compact_output=not verbose,
            skip_reason=skip_reason,
        )
        summaries.append(
            summary_module.StepSummary(
                number=step.number,
                name=step.name,
                status=outcome.status,
                exit_code=outcome.exit_code,
                duration_s=outcome.duration_s,
                message=outcome.message,
                log_file=str(step.log_file),
                health=outcome.health,
            )
        )
        report_names.extend(outcome.report_names)
        if not verbose:
            _ui._print_compact_step_footer(outcome)
        summary_module.write_summary(report_dir, snapshot(completed=False))
        if outcome.status == "failure":
            if not continue_on_error:
                _ui._print_failure_guidance(step, index=index, total_steps=total_steps)
                break
            print(f"→ Failure details: {step.log_file}; continuing with remaining selected steps")

    final_summary = snapshot(completed=True)
    write_debt_index(report_dir, report_names=final_summary.report_names)
    summary_module.write_summary(report_dir, final_summary)
    for line in summary_module.build_terminal_build_overview(report_dir, final_summary):
        print(line)
    return _completed_run_exit_code(summaries)
