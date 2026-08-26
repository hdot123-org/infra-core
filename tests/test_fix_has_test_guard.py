"""Contract tests for scripts/check_fix_has_test.py (INFRA-569)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

from tests.script_module_helpers import init_test_git_repo, load_script_module

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_fix_has_test.py"


def test_script_exists():
    """check_fix_has_test.py must exist in scripts/."""
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"


def test_script_is_python():
    """check_fix_has_test.py must be valid Python syntax."""
    with open(SCRIPT_PATH) as f:
        compile(f.read(), SCRIPT_PATH, "exec")


def test_no_args_exits_clean():
    """Without --pr or --base, must exit 0 (non-PR context)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "Must exit 0 when no --pr/--base given"


def test_fix_pattern_detection():
    """Must detect fix:/hotfix:/bugfix: commit patterns."""
    mod = load_script_module(SCRIPT_PATH, "check_fix_has_test_pattern")

    test_cases = [
        ("fix: correct null pointer", True),
        ("fix!: breaking fix", True),
        ("fix(api): endpoint bug", True),
        ("hotfix: urgent repair", True),
        ("bugfix: data loss", True),
        ("feat: add feature", False),
        ("chore: cleanup", False),
    ]

    for commit_msg, should_match in test_cases:
        match = mod.FIX_PATTERN.match(commit_msg)
        if should_match:
            assert match is not None, f"Should match: {commit_msg}"
        else:
            assert match is None, f"Should not match: {commit_msg}"


def test_code_dirs_config():
    """CODE_DIRS must be configured for infra-core package."""
    mod = load_script_module(SCRIPT_PATH, "check_fix_has_test_dirs")

    assert hasattr(mod, "_CODE_DIRS"), "_CODE_DIRS must be defined"
    assert len(mod._CODE_DIRS) > 0, "_CODE_DIRS must not be empty"
    # Should include src/infra_core or similar
    assert any("src" in d or "infra_core" in d for d in mod._CODE_DIRS), (
        f"_CODE_DIRS should include infra-core source paths: {mod._CODE_DIRS}"
    )


def test_non_code_only_exempt():
    """Non-code-only changes must be exempt."""
    mod = load_script_module(SCRIPT_PATH, "check_fix_has_test_exempt")

    # All docs/config files -> should be exempt
    non_code_files = ["README.md", "docs/guide.md", "pyproject.toml", ".github/workflows/ci.yml"]
    assert mod.is_non_code_only(non_code_files), "Non-code files should be exempt"

    # Mixed files -> not exempt
    mixed_files = ["src/infra_core/engine.py", "README.md"]
    assert not mod.is_non_code_only(mixed_files), "Mixed files should not be exempt"


def test_has_test_files_detection():
    """Must detect test file changes."""
    mod = load_script_module(SCRIPT_PATH, "check_fix_has_test_detect")

    # Files in tests/ -> should detect
    test_files = ["tests/test_engine.py", "src/infra_core/engine.py"]
    assert mod.has_test_files(test_files), "Should detect tests/ files"

    # No test files -> should not detect
    non_test_files = ["src/infra_core/engine.py", "README.md"]
    assert not mod.has_test_files(non_test_files), "Should not detect non-test files"


def test_cli_json_output(tmp_path):
    """CLI must support --json output mode."""
    # Create a minimal test repo
    repo = tmp_path / "test_repo"
    repo.mkdir()
    init_test_git_repo(repo)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Should not crash with --json flag
    assert result.returncode in (0, 1), f"Unexpected exit code: {result.returncode}"
