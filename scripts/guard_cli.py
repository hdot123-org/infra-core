#!/usr/bin/env python3
"""Guard CLI 共享骨架 (INFRA-559)。

从 memory-core scripts/guard_cli.py 移植，提供守卫脚本的公共 CLI 结构。
避免 check_boundary.py 和 check_doc_classification.py 等脚本重复 argparse/输出逻辑。

Exit codes (contract shared by all guards using this runner):
    0 — clean
    1 — findings detected
    2 — script error (raised by the caller's __main__ block)
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable

Finding = dict[str, str]


def run_cli(
    *,
    label: str,
    description: str,
    collect_findings: Callable[[], list[Finding]],
    format_finding: Callable[[Finding], str],
) -> int:
    """Run a guard CLI: parse --json, collect findings, print a summary.

    Args:
        label: Human-readable guard name used in the non-JSON summary lines
            (e.g., "BOUNDARY guard").
        description: argparse program description.
        collect_findings: Zero-arg callable returning the findings list
            (6-field dicts with at least `kind` plus formatter keys).
        format_finding: Renders one finding as the full (possibly
            multi-line) indented block for the non-JSON summary.

    Returns:
        Process exit code: 1 when findings exist, 0 when clean.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--json", action="store_true", help="Output findings as JSON")
    args = parser.parse_args()

    findings = collect_findings()

    if args.json:
        print(json.dumps({"findings": findings, "count": len(findings)}, ensure_ascii=False, indent=2))
    elif not findings:
        print(f"{label}: clean (0 findings)")
    else:
        print(f"{label}: {len(findings)} finding(s)")
        for f in findings:
            print(format_finding(f))

    return 1 if findings else 0
