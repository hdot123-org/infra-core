#!/usr/bin/env python3
"""
Real Shell Adversarial Matrix Test for B4 — VAL-MSC-001
Source-extracted tests that anchor to reconcile-evolution.sh at runtime.

This test extracts the actual pipeline and guard from reconcile-evolution.sh
instead of using parallel mock implementations. If the source script is modified
(pipeline order changed, guard removed, fallback value altered), extraction
fails and these tests turn red — no transcription drift.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "webhook-scripts" / "reconcile-evolution.sh"

# B4 four adversarial categories: multi-line numeric, number followed by
# warning text, empty string, pure garbage. Expected values per the guards.
ADVERSARIAL_CASES = [
    ("multiline_numeric", "12\n34", "12"),
    ("number_with_warning", "42\nwarning: some issue", "42"),
    ("empty_string", "", "9999"),
    ("pure_garbage", "warning:somethingbad", "9999"),
]

GUARDED_VARS = ["pr_age_minutes", "commit_age_minutes"]


def _extract_pipeline(script: str) -> str:
    """Extract the actual pipeline tail (head first, then trim) from the script.

    The regex only matches the fixed order `head -n 1 | tr -d '[:space:]'`;
    if the order is ever flipped back to trim-first, extraction fails.
    """
    m = re.search(r"head -n 1 \| tr -d '\[:space:\]'", script)
    assert m, (
        "pipeline 'head -n 1 | tr -d '[:space:]' not found in "
        f"{SCRIPT_PATH} — pipeline order must be head first, then trim"
    )
    return m.group(0)


def _extract_case_guard(script: str, var: str) -> str:
    """Extract the actual non-numeric→9999 case guard block for `var`.

    Raises AssertionError if the guard is absent — deleting the guard from the
    script must turn every matrix test red (anchoring requirement).
    """
    guard_re = (
        r'case "\$\{' + re.escape(var) + r'\}" in\s*'
        r"''\|\*\[!0-9\]\*\) " + re.escape(var) + r"=9999;;\s*esac"
    )
    m = re.search(guard_re, script)
    assert m, (
        f"case guard for {var} not found in {SCRIPT_PATH} — guard has been removed from the script!"
    )
    return m.group(0)


def _run_extracted_guard(var_name: str, input_value: str) -> tuple[int, str, str]:
    """Build a harness from source-extracted pieces and run it against input."""
    script = SCRIPT_PATH.read_text()
    pipeline = _extract_pipeline(script)
    guard = _extract_case_guard(script, var_name)

    harness = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'input_value="$1"\n'
        f"{var_name}=$(printf '%s' \"$input_value\" | {pipeline})\n"
        f"{guard}\n"
        f'echo "${var_name}"\n'
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, encoding="utf-8") as f:
        f.write(harness)
        temp_script_path = f.name
    try:
        os.chmod(temp_script_path, 0o755)
        result = subprocess.run(
            ["bash", temp_script_path, input_value], capture_output=True, text=True
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        os.unlink(temp_script_path)


# ============================================================================
# B4: 对抗性验证 (Adversarial Input Matrix, source-extracted) — VAL-MSC-001
# 4 categories × 2 guarded variables = 8 checks
# ============================================================================


class TestRealShellIntegration:
    """B4: drive the source-extracted guard logic with adversarial inputs."""

    @pytest.mark.parametrize("var_name", GUARDED_VARS)
    @pytest.mark.parametrize(
        "case_name,input_value,expected",
        ADVERSARIAL_CASES,
        ids=[c[0] for c in ADVERSARIAL_CASES],
    )
    def test_extracted_guard_adversarial_matrix(self, var_name, case_name, input_value, expected):
        """Run the real guard (extracted from reconcile-evolution.sh) on adversarial input."""
        returncode, stdout, stderr = _run_extracted_guard(var_name, input_value)
        assert returncode == 0, (
            f"[{var_name}/{case_name}] should not error on input {input_value!r}: {stderr}"
        )
        assert "integer expression expected" not in stderr, (
            f"[{var_name}/{case_name}] guard failed: integer expression error resurfaced"
        )
        assert stdout.strip() == expected, (
            f"[{var_name}/{case_name}] expected {expected!r}, got {stdout.strip()!r}"
        )


def test_original_script_syntax():
    """Verify the actual reconcile-evolution.sh script has correct syntax."""
    result = subprocess.run(["bash", "-n", str(SCRIPT_PATH)], capture_output=True, text=True)

    assert result.returncode == 0, f"Script syntax error: {result.stderr}"
    print("✓ Original script syntax is valid")


if __name__ == "__main__":
    print("Running real shell adversarial matrix tests...")
    pytest.main([__file__, "-v"])
