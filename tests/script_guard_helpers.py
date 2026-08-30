"""Shared script guard test helpers (INFRA-670 dedup).

INFRA-670: the generic guard test functions (``test_script_exists`` /
``test_script_is_python`` / ``test_cli_json_output`` / ``test_exit_codes``)
had 100% AST similarity across test_boundary_guard.py and
test_doc_classification_guard.py (CODE_HYGIENE_DUPLICATE_BLOCK, 27 lines /
199 tokens and 14 lines / 97 tokens) — both files test scripts/ CLI tools
that share the same guard contract.

All four guards are folded into parametrized factories here. Test modules
bind them via module-level ``test_*`` aliases so existing test IDs stay
unchanged (``test_boundary_guard.py::test_cli_json_output`` etc.).

Pattern follows tests/drift_watch_helpers.py (INFRA-415).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def guard_script_exists(script_path: Path) -> None:
    """Guard: the target script must exist (test_script_exists body)."""
    assert script_path.exists(), f"Script not found: {script_path}"


def guard_script_is_python(script_path: Path) -> None:
    """Guard: the target script must be valid Python syntax (test_script_is_python body)."""
    with open(script_path) as f:
        compile(f.read(), script_path, "exec")


def guard_cli_json_output(script_path: Path, repo_root: Path) -> None:
    """Guard: CLI must support --json with findings/count keys (test_cli_json_output body)."""
    result = subprocess.run(
        [sys.executable, str(script_path), "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "findings" in result.stdout, "JSON output must contain 'findings'"
    assert "count" in result.stdout, "JSON output must contain 'count'"


def guard_exit_codes(script_path: Path, repo_root: Path) -> None:
    """Guard: exit code contract 0=clean / 1=findings (test_exit_codes body)."""
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=repo_root,
        capture_output=True,
    )
    assert result.returncode in (0, 1), "Exit code must be 0 or 1 for valid run"


def guard_live_repo_clean(script_path: Path, repo_root: Path, check_name: str) -> None:
    """Guard: live repo must pass the script with exit 0 (test_live_repo_clean body).

    Args:
        check_name: Human-readable check name for the failure message
            (e.g. "boundary check", "doc classification check").
    """
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Live repo failed {check_name}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
