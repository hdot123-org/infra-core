"""Contract tests for scripts/check_doc_classification.py (INFRA-569)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.business_policy]

from tests.script_module_helpers import (
    load_script_module,
    run_cli_json_contract,
    run_live_repo_clean_contract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_doc_classification.py"


def test_script_exists():
    """check_doc_classification.py must exist in scripts/."""
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"


def test_script_is_python():
    """check_doc_classification.py must be valid Python syntax."""
    with open(SCRIPT_PATH) as f:
        compile(f.read(), SCRIPT_PATH, "exec")


def test_scan_roots_config():
    """SCAN_ROOTS must be configured for infra-core docs structure."""
    mod = load_script_module(SCRIPT_PATH, "check_doc_scan_roots")

    assert hasattr(mod, "SCAN_ROOTS"), "SCAN_ROOTS must be defined"
    assert len(mod.SCAN_ROOTS) > 0, "SCAN_ROOTS must not be empty"
    # Should include docs/
    assert any("docs" in str(root) for root in mod.SCAN_ROOTS), (
        f"SCAN_ROOTS should include docs/ paths: {mod.SCAN_ROOTS}"
    )


def test_exempt_paths():
    """Certain paths must be exempt from scanning."""
    mod = load_script_module(SCRIPT_PATH, "check_doc_exempt")

    # Test exempt paths (matching the script's EXCEPTION_DIRS and SKIP_FILES)
    exempt_test_cases = [
        Path("/repo/docs/__pycache__/module.py"),
        Path("/repo/docs/.DS_Store"),
    ]

    for path in exempt_test_cases:
        # Check if path matches exception logic
        path_str = str(path)
        is_exempt = path.name in mod.SKIP_FILES or any(
            exc in path_str for exc in mod.EXCEPTION_DIRS
        )
        assert is_exempt, f"Should be exempt: {path}"


def test_live_repo_clean():
    """Live infra-core repo must pass doc classification check (shared contract, INFRA-697)."""
    run_live_repo_clean_contract(SCRIPT_PATH, REPO_ROOT, "doc classification")


def test_cli_json_output():
    """CLI must support --json output mode (shared contract, INFRA-696)."""
    run_cli_json_contract(SCRIPT_PATH, REPO_ROOT)


def test_detects_unregistered_dir(tmp_path):
    """Must detect files in unregistered directories."""
    mod = load_script_module(SCRIPT_PATH, "check_doc_unregistered")

    # Create fake docs structure with unregistered directory
    fake_docs = tmp_path / "docs" / "unknown-category"
    fake_docs.mkdir(parents=True)
    unregistered_file = fake_docs / "orphan.md"
    unregistered_file.write_text("# Orphan document")

    # Use parameterized scan_root and repo_root
    findings = mod.scan_doc_classification(
        scan_root=tmp_path / "docs",
        repo_root=tmp_path,
    )

    assert len(findings) > 0, "Should detect unregistered directory"
    assert any(f["kind"] == "unregistered-doc-dir" for f in findings)


def test_registered_categories_accepted(tmp_path):
    """Files in registered categories must pass."""
    mod = load_script_module(SCRIPT_PATH, "check_doc_registered")

    # Create fake docs structure with registered directories
    fake_arch = tmp_path / "docs" / "architecture"
    fake_arch.mkdir(parents=True)
    arch_file = fake_arch / "design.md"
    arch_file.write_text("# Architecture design")

    fake_guide = tmp_path / "docs" / "guides"
    fake_guide.mkdir(parents=True)
    guide_file = fake_guide / "tutorial.md"
    guide_file.write_text("# Tutorial guide")

    fake_roadmap = tmp_path / "docs" / "roadmap"
    fake_roadmap.mkdir(parents=True)
    roadmap_file = fake_roadmap / "central-scheduling.md"
    roadmap_file.write_text("# Central scheduling roadmap")

    # Use parameterized scan_root and repo_root
    findings = mod.scan_doc_classification(
        scan_root=tmp_path / "docs",
        repo_root=tmp_path,
    )

    assert len(findings) == 0, f"Registered categories should pass, got: {findings}"


def test_exit_codes():
    """Exit code contract: 0=clean, 1=findings, 2=error."""
    # Test clean case (live repo)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode in (0, 1), "Exit code must be 0 or 1 for valid run"
