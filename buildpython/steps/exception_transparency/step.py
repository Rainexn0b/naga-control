"""Exception transparency debt scan.

Tracks broad exception patterns for review. Cleanup and fail-open boundaries
may legitimately catch BaseException; no blanket ban is imposed. Only reviewed
budgets in debt_baselines.json gate findings.
"""

from __future__ import annotations

from collections import Counter

from ...utils.paths import repo_root
from ...utils.subproc import RunResult
from .baseline import baseline_regressions, load_baseline
from .reporting import build_stdout, write_reports
from .scanner import (
    collect_annotation_inventory,
    collect_findings,
    count_broad_waivers,
)


def exception_transparency_runner() -> RunResult:
    root = repo_root()
    baseline = load_baseline(root)
    findings = collect_findings(root)
    waived_total = count_broad_waivers(root)
    annotation_inventory = collect_annotation_inventory(root)

    counts: Counter[str] = Counter()
    for finding in findings:
        counts[finding.category] += 1

    stdout_lines = build_stdout(findings, counts, waived_total, annotation_inventory)
    write_reports(root, findings, counts, waived_total, annotation_inventory)

    regressions = baseline_regressions(counts, baseline)
    should_fail = bool(regressions)
    return RunResult(
        command_str="(internal) exception transparency check",
        stdout="\n".join(stdout_lines) + "\n",
        stderr="",
        exit_code=1 if should_fail else 0,
    )
