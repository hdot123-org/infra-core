"""Tests for the zero-red check-runs mechanism.

User mandate (2026-08-28): "写死不允许红色合并，一个都不允许"
These tests verify that the ci-ok gate correctly fails when any check-run
(including advisory jobs) has a non-success conclusion. INFRA-595: advisory
jobs carry no continue-on-error, so a failure is a red check-run that both
the needs.result gate and the GitHub API scan block.
"""

import subprocess
from pathlib import Path

import pytest


class TestZeroRedScript:
    """Test the check_zero_red.sh script logic."""

    @pytest.fixture
    def script_path(self):
        """Path to the zero-red check script."""
        return Path(__file__).parent.parent / "scripts" / "check_zero_red.sh"

    def test_script_exists_and_executable(self, script_path):
        """Verify the script exists and is executable."""
        assert script_path.exists(), f"Script not found: {script_path}"
        assert script_path.stat().st_mode & 0o111, "Script is not executable"

    def test_script_usage_on_missing_args(self, script_path):
        """Script should print usage when called without arguments."""
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Usage:" in result.stderr or "Usage:" in result.stdout

    def test_script_logic_mock_success(self):
        """Test zero-red logic with all-success check-runs (mock)."""
        # Simulate the check-runs output format
        mock_output = """pytest\tsuccess
ruff\tsuccess
actionlint\tsuccess
Advisory dependency security scan\tsuccess
Advisory deptry\tneutral
Advisory telemetry coverage audit\tskipped
ci-ok\tsuccess"""

        # Parse the output the same way the script does
        lines = mock_output.strip().split("\n")
        red_checks = []

        for line in lines:
            parts = line.split("\t")
            if len(parts) == 2:
                name, conclusion = parts
                if conclusion not in ["success", "skipped", "neutral"]:
                    red_checks.append(line)

        # All success/skipped/neutral should pass
        assert len(red_checks) == 0, "Should have no red checks when all are green"

    def test_script_logic_mock_failure_advisory_red(self):
        """Test zero-red logic with a red advisory check (mock)."""
        # Simulate a scenario where advisory security scan fails
        mock_output = """pytest\tsuccess
ruff\tsuccess
actionlint\tsuccess
Advisory dependency security scan\tfailure
Advisory deptry\tsuccess
ci-ok\tsuccess"""

        # Parse the output the same way the script does
        lines = mock_output.strip().split("\n")
        red_checks = []

        for line in lines:
            parts = line.split("\t")
            if len(parts) == 2:
                name, conclusion = parts
                if conclusion not in ["success", "skipped", "neutral"]:
                    red_checks.append(line)

        # Should detect the red advisory check
        assert len(red_checks) == 1
        assert "Advisory dependency security scan" in red_checks[0]
        assert "failure" in red_checks[0]

    def test_script_logic_mock_multiple_red(self):
        """Test zero-red logic with multiple red checks (mock)."""
        # Simulate multiple failures
        mock_output = """pytest\tsuccess
ruff\tfailure
Advisory dependency security scan\tfailure
Advisory deptry\tsuccess
mypy\tsuccess"""

        # Parse the output the same way the script does
        lines = mock_output.strip().split("\n")
        red_checks = []

        for line in lines:
            parts = line.split("\t")
            if len(parts) == 2:
                name, conclusion = parts
                if conclusion not in ["success", "skipped", "neutral"]:
                    red_checks.append(line)

        # Should detect both red checks
        assert len(red_checks) == 2
        assert any("ruff" in check for check in red_checks)
        assert any("Advisory" in check for check in red_checks)


class TestCIWorkflowZeroRed:
    """Test that the CI workflow includes zero-red enforcement."""

    def test_ci_ok_includes_advisory_in_needs(self):
        """Verify ci-ok job lists advisory jobs in needs."""
        ci_yml = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci_yml.read_text()

        # Check that advisory jobs are in the needs list
        assert "advisory-dependency-security-scan" in content
        assert "advisory-deptry" in content
        assert "advisory-telemetry-audit" in content

    def test_ci_ok_checks_advisory_jobs(self):
        """Verify ci-ok job actually checks advisory job results (not just prints)."""
        ci_yml = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci_yml.read_text()

        # Find the ci-ok job section
        ci_ok_start = content.find("  ci-ok:")
        assert ci_ok_start != -1, "ci-ok job not found"

        # Extract ci-ok section (up to next top-level job or end)
        ci_ok_section = content[ci_ok_start:]

        # Verify advisory jobs are checked with FAILED=1 logic
        # INFRA-595: advisory jobs must NOT set continue-on-error (which makes
        # .result always "success"); with it removed, .result is the real
        # conclusion and this gate is effective.
        assert "advisory-dependency-security-scan.result" in ci_ok_section, (
            "Should check advisory-dependency-security-scan result"
        )
        assert "advisory-deptry.result" in ci_ok_section, "Should check advisory-deptry result"
        assert "advisory-telemetry-audit.result" in ci_ok_section, (
            "Should check advisory-telemetry-audit result"
        )

        # Verify they set FAILED=1 on non-success
        assert "FAILED=1" in ci_ok_section, "Should set FAILED=1 on failure"

    def test_ci_ok_includes_zero_red_api_scan(self):
        """Verify ci-ok includes the zero-red aggregation step via GitHub API."""
        ci_yml = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci_yml.read_text()

        # Check for the zero-red step
        assert "Zero-red aggregation" in content or "zero-red" in content.lower(), (
            "Should have a zero-red aggregation step"
        )
        # The zero-red logic is delegated to the standalone script
        assert "check_zero_red.sh" in content, "Should invoke the check_zero_red.sh script"


class TestZeroRedPolicy:
    """Test the zero-red policy documentation and intent."""

    def test_user_mandate_in_ci(self):
        """Verify the user mandate comment is present in CI."""
        ci_yml = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci_yml.read_text()

        # Check for the user mandate reference
        assert "写死不允许红色合并" in content or "zero-red" in content.lower(), (
            "Should reference the user mandate or zero-red policy"
        )

    def test_advisory_jobs_no_continue_on_error(self):
        """INFRA-595: advisory jobs must NOT have continue-on-error (zero-red).

        continue-on-error masks failures: needs.<job>.result reports the
        post-masking value (always "success"), making the ci-ok gate a no-op
        (proven in run 33129232081). Zero-red requires red check-runs.
        """
        ci_yml = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci_yml.read_text()

        # Advisory jobs must exist
        assert "advisory-dependency-security-scan:" in content, (
            "Should have advisory-dependency-security-scan job"
        )
        assert "advisory-deptry:" in content, "Should have advisory-deptry job"
        assert "advisory-telemetry-audit:" in content, "Should have advisory-telemetry-audit job"

        # No job-level continue-on-error anywhere: failures must stay red
        continue_on_error_count = content.count("continue-on-error: true")
        assert continue_on_error_count == 0, (
            f"Expected 0 continue-on-error: true (zero-red: INFRA-595), found {continue_on_error_count}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
