"""Contract tests for repo_health_check.sh"""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.business_policy
def test_repo_health_check_script_exists():
    """repo_health_check.sh must exist in scripts/"""
    script_path = Path(__file__).parent.parent / "scripts" / "repo_health_check.sh"
    assert script_path.exists(), "scripts/repo_health_check.sh must exist"


@pytest.mark.business_policy
def test_repo_health_check_passes_on_clean_repo():
    """repo_health_check.sh must pass on a clean repo"""
    script_path = Path(__file__).parent.parent / "scripts" / "repo_health_check.sh"
    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, f"Repo health check failed: {result.stderr.decode()}"
