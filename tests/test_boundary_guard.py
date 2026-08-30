"""Contract tests for scripts/check_boundary.py (INFRA-569)."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.business_policy]

from tests.script_guard_helpers import (
    guard_cli_json_output,
    guard_exit_codes,
    guard_live_repo_clean,
    guard_script_exists,
    guard_script_is_python,
)
from tests.script_module_helpers import load_script_module

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_boundary.py"


def test_script_exists():
    """check_boundary.py must exist in scripts/."""
    guard_script_exists(SCRIPT_PATH)


def test_script_is_python():
    """check_boundary.py must be valid Python syntax."""
    guard_script_is_python(SCRIPT_PATH)


def test_live_repo_clean():
    """Live infra-core repo must pass boundary check (exit 0)."""
    guard_live_repo_clean(SCRIPT_PATH, REPO_ROOT, "boundary check")


def test_detects_local_path_leak(tmp_path):
    """Detection of /Users/... path leaks in protected domains."""
    mod = load_script_module(SCRIPT_PATH, "check_boundary_leak")

    # Create a fake repo with a leak in src/infra_core/
    fake_src = tmp_path / "src" / "infra_core"
    fake_src.mkdir(parents=True)
    leak_file = fake_src / "leak.py"
    leak_file.write_text("path = '/Users/test/secret'\n")

    # Override REPO_ROOT and PROTECTED_DOMAINS
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PROTECTED_DOMAINS", ("src/infra_core/",))

    # Mock git to return the leak file as tracked
    original_get_git = mod._get_git_tracked_files
    mod._get_git_tracked_files = lambda root: {leak_file}

    findings = mod.scan_protected_domain_leaks()

    monkeypatch.undo()
    mod._get_git_tracked_files = original_get_git

    assert len(findings) > 0, "Should detect /Users/ path leak"
    assert any(f["kind"] == "protected-domain-leak" for f in findings)


def test_detects_business_prefix(tmp_path):
    """Detection of business-prefixed files in protected domains."""
    mod = load_script_module(SCRIPT_PATH, "check_boundary_business")

    # Create a fake repo with a business-prefixed file
    fake_src = tmp_path / "src" / "infra_core"
    fake_src.mkdir(parents=True)
    biz_file = fake_src / "workbot-config.toml"
    biz_file.write_text("config = true\n")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PROTECTED_DOMAINS", ("src/infra_core/",))

    findings = mod.scan_business_file_names()

    monkeypatch.undo()

    assert len(findings) > 0, "Should detect workbot- prefix"
    assert any(f["kind"] == "business-file-prefix" for f in findings)
    assert any("workbot-" in f["matched"] for f in findings)


def test_exempt_paths():
    """Certain paths must be exempt from scanning."""
    mod = load_script_module(SCRIPT_PATH, "check_boundary_exempt")

    # Test exempt fragments
    exempt_test_cases = [
        Path("/repo/.venv/lib/site-packages/bad.py"),
        Path("/repo/.git/hooks/bad.py"),
        Path("/repo/__pycache__/bad.py"),
        Path("/repo/tests/fixtures/leak.py"),
    ]

    for path in exempt_test_cases:
        assert mod._is_exempt(path), f"Should be exempt: {path}"


def test_cli_json_output():
    """CLI must support --json output mode."""
    guard_cli_json_output(SCRIPT_PATH, REPO_ROOT)


def test_exit_codes():
    """Exit code contract: 0=clean, 1=findings, 2=error."""
    guard_exit_codes(SCRIPT_PATH, REPO_ROOT)
