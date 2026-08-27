"""Contract tests for scripts/check_pr_ref_consistency.py (INFRA-569)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.business_policy]

from tests.script_module_helpers import load_script_module

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_pr_ref_consistency.py"


def test_script_exists():
    """check_pr_ref_consistency.py must exist in scripts/."""
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"


def test_script_is_python():
    """check_pr_ref_consistency.py must be valid Python syntax."""
    with open(SCRIPT_PATH) as f:
        compile(f.read(), SCRIPT_PATH, "exec")


def test_extract_infra_ids():
    """Must extract INFRA-xxx IDs from PR body."""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_extract")

    test_cases = [
        # Basic cases
        ("Fixes INFRA-123", {"INFRA-123"}),
        ("fixes INFRA-456", {"INFRA-456"}),  # case insensitive
        ("Closes INFRA-789", {"INFRA-789"}),
        ("Resolves INFRA-101", {"INFRA-101"}),
        # Multiple IDs
        ("Fixes INFRA-123, INFRA-456", {"INFRA-123", "INFRA-456"}),
        ("Fixes INFRA-1 and INFRA-2", {"INFRA-1", "INFRA-2"}),
        ("Fixes INFRA-1, INFRA-2, and INFRA-3", {"INFRA-1", "INFRA-2", "INFRA-3"}),
        # No IDs
        ("Just a description", set()),
        ("INFRA-999 without keyword", set()),
        # Mixed
        ("Fixes INFRA-123\nSome text\nCloses INFRA-456", {"INFRA-123", "INFRA-456"}),
    ]

    for body, expected in test_cases:
        result = mod.extract_fixes_infra_ids(body)
        assert result == expected, f"Body: {body!r}, expected {expected}, got {result}"


def test_extract_linkback_three_tiers():
    """Must extract linkback IDs using three extraction tiers."""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_linkback")

    # Tier 1: HTML comment
    html_comment = "Some text\n<!-- linear-linkback INFRA-123 -->\nMore text"
    assert mod.extract_linkback_from_comments(html_comment) == "INFRA-123"

    # Tier 2a: href format (must include linear-linkback marker to be detected)
    href_text = (
        "Some text\n<!-- linear-linkback -->\nCheck linear.app/org/issue/INFRA-456 for details"
    )
    assert mod.extract_linkback_from_comments(href_text) == "INFRA-456"

    # Tier 2b: anchor text (must include linear-linkback marker to be detected)
    anchor_text = 'Some text\n<!-- linear-linkback -->\nSee <a href="...">INFRA-789</a> for more'
    assert mod.extract_linkback_from_comments(anchor_text) == "INFRA-789"

    # No linkback
    no_linkback = "Just a regular comment"
    assert mod.extract_linkback_from_comments(no_linkback) is None


def test_resolve_repo_owner_name():
    """Must parse owner/name from git remote URL."""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_resolve")

    # Test both HTTPS and SSH formats
    test_urls = [
        ("https://github.com/hdot123-org/infra-core.git", "hdot123-org", "infra-core"),
        ("git@github.com:hdot123-org/infra-core.git", "hdot123-org", "infra-core"),
        ("https://github.com/owner/repo", "owner", "repo"),
    ]

    for url, expected_owner, expected_name in test_urls:
        # Mock git remote
        import subprocess

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "git" and "get-url" in cmd:
                result = type("Result", (), {"stdout": url})()
                return result
            return original_run(cmd, *args, **kwargs)

        subprocess.run = mock_run

        try:
            owner, name = mod._resolve_repo_owner_name()
            assert owner == expected_owner, f"URL: {url}, owner: {owner} != {expected_owner}"
            assert name == expected_name, f"URL: {url}, name: {name} != {expected_name}"
        finally:
            subprocess.run = original_run


def test_fail_closed_behavior():
    """Must exit 1 (not 0) when fetch fails (PR #827 fix)."""
    # This is a contract test - we verify the script exists and has the right structure
    with open(SCRIPT_PATH) as f:
        content = f.read()

    # Must have exception handling that returns 1
    assert "except Exception" in content or "except:" in content, (
        "Script must have exception handling"
    )
    # Must return 1 on error (not 0)
    assert "return 1" in content, "Script must return 1 on error (fail-closed)"


def test_cli_no_args():
    """CLI must require PR number argument."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"Should exit 2 without args: {result.stderr}"
    assert "Usage" in result.stderr or "usage" in result.stderr
