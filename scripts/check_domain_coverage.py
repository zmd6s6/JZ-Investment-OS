"""Enforce the Master Spec's separate domain line and branch coverage floors."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def domain_totals(report: dict[str, Any]) -> tuple[int, int, int, int]:
    covered_lines = statements = covered_branches = branches = 0
    for filename, data in report["files"].items():
        normalized = filename.replace("\\", "/")
        if "/investment_os/domain/" not in normalized:
            continue
        summary = data["summary"]
        covered_lines += summary["covered_lines"]
        statements += summary["num_statements"]
        covered_branches += summary["covered_branches"]
        branches += summary["num_branches"]
    if statements == 0:
        raise SystemExit("domain coverage data is missing")
    return covered_lines, statements, covered_branches, branches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", nargs="?", type=Path)
    parser.add_argument("--line-min", type=float, default=90.0)
    parser.add_argument("--branch-min", type=float, default=85.0)
    args = parser.parse_args()

    report_path = args.report
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if report_path is None:
        temporary_directory = tempfile.TemporaryDirectory()
        report_path = Path(temporary_directory.name) / "coverage.json"
        subprocess.run(
            [sys.executable, "-m", "coverage", "json", "-o", str(report_path)],
            check=True,
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    covered_lines, statements, covered_branches, branches = domain_totals(report)
    line_rate = covered_lines / statements * 100
    branch_rate = covered_branches / branches * 100 if branches else 100.0
    print(f"domain line coverage: {line_rate:.2f}% ({covered_lines}/{statements})")
    print(f"domain branch coverage: {branch_rate:.2f}% ({covered_branches}/{branches})")
    if line_rate < args.line_min or branch_rate < args.branch_min:
        raise SystemExit("domain coverage is below the Master Spec threshold")
    if temporary_directory is not None:
        temporary_directory.cleanup()


if __name__ == "__main__":
    main()
