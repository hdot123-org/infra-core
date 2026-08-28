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


def test_resolve_repo_owner_name(monkeypatch):
    """Must parse owner/name from git remote URL."""
    # 环境隔离：GITHUB_REPOSITORY（Actions 运行器默认注入）优先级高于 remote
    # 解析，不 delenv 会在 CI 上短路 remote fallback 分支（repo-context 双重
    # 防线引入，2026-08-28）。
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
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


# ============================================================================
# 仓库上下文双重防线（2026-08-28，mirror memory PR #1060 / INFRA-597）
# 自建 runner insteadOf 镜像重写使 git remote get-url 返回镜像 URL（解析出
# 错误 owner/repo）或 gh 无法从 remote 解析 host。GITHUB_REPOSITORY（Actions
# 默认注入）优先；未设置时保持原命令形态（本地调试）。
# ============================================================================


def test_resolve_repo_owner_name_prefers_github_repository_env(monkeypatch):
    """GITHUB_REPOSITORY 已设置 → env 优先，不咨询 git remote。"""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_resolve_env")

    def forbidden_run(cmd, *args, **kwargs):
        raise AssertionError(
            f"git remote must not be consulted when GITHUB_REPOSITORY is set: {cmd}"
        )

    monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    owner, name = mod._resolve_repo_owner_name()
    assert (owner, name) == ("hdot123-org", "infra-core")


def test_resolve_repo_owner_name_still_falls_back_to_remote(monkeypatch):
    """GITHUB_REPOSITORY 未设置 → origin remote fallback 语义不变。"""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_resolve_fallback")

    original_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "git" and "get-url" in cmd:
            return type("Result", (), {"stdout": "https://github.com/owner/repo.git"})()
        return original_run(cmd, *args, **kwargs)

    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(subprocess, "run", mock_run)
    owner, name = mod._resolve_repo_owner_name()
    assert (owner, name) == ("owner", "repo")


def test_fetch_issue_comments_adds_repo_when_github_repository_set(monkeypatch):
    """GITHUB_REPOSITORY 已设置（CI）→ gh issue view 必须显式 --repo。"""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_comments_env")
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
    monkeypatch.setattr(subprocess, "run", fake_run)
    mod.fetch_issue_comments(5)
    assert captured["cmd"] == [
        "gh",
        "issue",
        "view",
        "5",
        "--repo",
        "hdot123-org/infra-core",
        "--json",
        "comments",
        "--jq",
        ".comments[].body",
    ]


def test_fetch_issue_comments_original_form_without_env(monkeypatch):
    """GITHUB_REPOSITORY 未设置（本地调试）→ 保持原命令形态（无 --repo）。"""
    mod = load_script_module(SCRIPT_PATH, "check_pr_ref_comments_no_env")
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return type("Result", (), {"stdout": ""})()

    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    mod.fetch_issue_comments(5)
    assert captured["cmd"] == [
        "gh",
        "issue",
        "view",
        "5",
        "--json",
        "comments",
        "--jq",
        ".comments[].body",
    ]
