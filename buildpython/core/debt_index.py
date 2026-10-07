from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .debt_index_markdown import render_debt_index
from .summary_support.common import read_json_if_exists


def build_debt_index(
    buildlog_dir: Path, *, report_names: tuple[str, ...] | None = None
) -> dict[str, Any]:
    hygiene = read_json_if_exists(buildlog_dir / "code-hygiene.json", report_names=report_names)
    exception_transparency = read_json_if_exists(
        buildlog_dir / "exception-transparency.json", report_names=report_names
    )
    markers = read_json_if_exists(buildlog_dir / "code-markers.json", report_names=report_names)
    file_size = read_json_if_exists(
        buildlog_dir / "file-size-analysis.json", report_names=report_names
    )
    loc_check = read_json_if_exists(buildlog_dir / "loc-check.json", report_names=report_names)
    architecture = read_json_if_exists(
        buildlog_dir / "architecture-validation.json", report_names=report_names
    )
    coverage = read_json_if_exists(
        buildlog_dir / "coverage-summary.json", report_names=report_names
    )
    dead_code = read_json_if_exists(
        buildlog_dir / "dead-code-vulture.json", report_names=report_names
    )

    sections: dict[str, Any] = {}
    report_paths: dict[str, str] = {}

    if dead_code is not None:
        sections["dead_code"] = {
            "candidates": dead_code.get("count"),
            "actionable": dead_code.get("actionable_count"),
        }
        report_paths["dead_code"] = str(buildlog_dir / "dead-code-vulture.md")

    if hygiene is not None:
        sections["code_hygiene"] = {
            "active_counts": hygiene.get("active_counts", {}),
            "suppressed_counts": hygiene.get("suppressed_counts", {}),
            "top_files_by_category": hygiene.get("top_files_by_category", {}),
        }
        report_paths["code_hygiene"] = str(buildlog_dir / "code-hygiene.md")

    if exception_transparency is not None:
        sections["exception_transparency"] = {
            "counts": exception_transparency.get("counts", {}),
            "waived_total": exception_transparency.get("waived_total", 0),
            "annotation_inventory": exception_transparency.get("annotation_inventory", {}),
            "top_files_by_category": exception_transparency.get("top_files_by_category", {}),
        }
        report_paths["exception_transparency"] = str(buildlog_dir / "exception-transparency.md")

    if markers is not None:
        sections["code_markers"] = {
            "marker_counts": markers.get("marker_counts", {}),
            "regressions": markers.get("baseline", {}).get("regressions", []),
            "top_marker_files": markers.get("top_marker_files", {}),
        }
        report_paths["code_markers"] = str(buildlog_dir / "code-markers.md")

    if file_size is not None:
        sections["file_size"] = {
            "counts": file_size.get("counts", {}),
            "files": file_size.get("files", []),
            "import_blocks": file_size.get("import_blocks", []),
            "flat_directories": file_size.get("flat_directories", []),
            "delegation_candidates": file_size.get("delegation_candidates", []),
            "middleman_modules": file_size.get("middleman_modules", []),
            "unreferenced_files": file_size.get("unreferenced_files", []),
        }
        report_paths["file_size"] = str(buildlog_dir / "file-size-analysis.md")

    if loc_check is not None:
        sections["loc_check"] = {
            "threshold": loc_check.get("threshold"),
            "thresholds": loc_check.get("thresholds"),
            "count": loc_check.get("count"),
            "counts": loc_check.get("counts", {}),
            "counts_by_scope": loc_check.get("counts_by_scope", {}),
            "files": loc_check.get("files", []),
        }
        report_paths["loc_check"] = str(buildlog_dir / "loc-check.md")

    if architecture is not None:
        sections["architecture_validation"] = architecture.get("summary", {})
        report_paths["architecture_validation"] = str(buildlog_dir / "architecture-validation.md")

    if coverage is not None:
        sections["coverage"] = {
            "summary": coverage.get("summary", {}),
            "regressions": coverage.get("baseline", {}).get("regressions", []),
            "tracked_prefixes": coverage.get("tracked_prefixes", []),
            "watch_files": coverage.get("watch_files", []),
        }
        report_paths["coverage"] = str(buildlog_dir / "coverage-summary.md")

    return {
        "summary": {
            "scope": "current_run" if report_names is not None else "latest_available",
            "available_sections": sorted(sections.keys()),
            "report_count": len(report_paths),
        },
        "reports": report_paths,
        "sections": sections,
    }


def write_debt_index(buildlog_dir: Path, *, report_names: tuple[str, ...] | None = None) -> None:
    buildlog_dir.mkdir(parents=True, exist_ok=True)
    payload = build_debt_index(buildlog_dir, report_names=report_names)

    json_path = buildlog_dir / "debt-index.json"
    md_path = buildlog_dir / "debt-index.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_debt_index(payload), encoding="utf-8")
