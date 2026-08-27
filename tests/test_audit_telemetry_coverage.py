"""Contract tests for audit_telemetry_coverage.sh"""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.business_policy
def test_audit_telemetry_coverage_script_exists():
    """audit_telemetry_coverage.sh must exist in scripts/"""
    script_path = Path(__file__).parent.parent / "scripts" / "audit_telemetry_coverage.sh"
    assert script_path.exists(), "scripts/audit_telemetry_coverage.sh must exist"


@pytest.mark.business_policy
def test_audit_telemetry_coverage_always_exits_zero():
    """audit_telemetry_coverage.sh must always exit 0 (advisory only)"""
    script_path = Path(__file__).parent.parent / "scripts" / "audit_telemetry_coverage.sh"
    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, "Telemetry audit must always exit 0 (advisory)"
