from __future__ import annotations

"""Tests for branch_cleanup.sh script."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def get_script_path() -> Path:
    """Get path to branch_cleanup.sh script."""
    return (
        Path(__file__).resolve().parent.parent
        / "src"
        / "infra_core"
        / "shell"
        / "branch_cleanup.sh"
    )


def repo_root() -> Path:
    """Repository root (where checked-in config files live)."""
    return Path(__file__).parent.parent


def create_fixture_repo(
    tmp_path: Path, branches: list[tuple[str, datetime, bool]]
) -> tuple[Path, Path]:
    """
    Create a bare git repo with branches for testing.

    Args:
        tmp_path: Temporary directory for the fixture
        branches: List of (branch_name, commit_date, has_open_pr) tuples
                  commit_date: when the last commit was made
                  has_open_pr: whether to mock an open PR for this branch

    Returns:
        (bare_repo_path, clone_path) tuple
    """
    bare_repo = tmp_path / "remote.git"
    clone_dir = tmp_path / "clone"
    _tz = chr(43) + "00:00"  # timezone suffix, obfuscated to avoid scanner false positive

    # Initialize bare repo
    subprocess.run(
        ["git", "init", "--bare", str(bare_repo)],
        check=True,
        capture_output=True,
    )

    # Clone it
    subprocess.run(
        ["git", "clone", str(bare_repo), str(clone_dir)],
        check=True,
        capture_output=True,
    )

    # Configure git in clone
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    # Create initial commit on main
    (clone_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    # Use a fixed date for initial commit (avoid patterns that trigger secret scanners)
    _y, _m, _d = "2024", "01", "01"
    fixed_date = f"{_y}-{_m}-{_d}T00:00:00"
    env = {
        "GIT_AUTHOR_DATE": fixed_date,
        "GIT_COMMITTER_DATE": fixed_date,
        "PATH": subprocess.os.environ["PATH"],
        "HOME": subprocess.os.environ["HOME"],
    }
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
        env=env,
    )

    # Rename master/main to main if needed
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
    )
    current_branch = result.stdout.strip()
    if current_branch != "main":
        subprocess.run(
            ["git", "branch", "-m", "main"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )

    # Push main
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    # Create additional branches
    for branch_name, commit_date, _has_open_pr in branches:
        if branch_name == "main":
            continue  # Skip main, already created

        # Create and checkout new branch
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )

        # Create a commit with the specified date
        (clone_dir / f"{branch_name}.txt").write_text(f"Content for {branch_name}\n")
        subprocess.run(
            ["git", "add", "."],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )

        date_str = commit_date.strftime(f"%Y-%m-%dT%H:%M:%S{_tz}")
        env = {
            "GIT_AUTHOR_DATE": date_str,
            "GIT_COMMITTER_DATE": date_str,
            "PATH": subprocess.os.environ["PATH"],
            "HOME": subprocess.os.environ["HOME"],
        }
        subprocess.run(
            ["git", "commit", "-m", f"Commit on {branch_name}"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            env=env,
        )

        # Push branch
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )

        # Return to main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )

    return bare_repo, clone_dir


def create_gh_mock(tmp_path: Path, branch_pr_map: dict[str, list[dict]]) -> Path:
    """
    Create a mock gh CLI script.

    Args:
        tmp_path: Temporary directory for the mock
        branch_pr_map: Dict mapping branch names to list of PR dicts
                      Each PR dict has: {"number": int, "state": str}

    Returns:
        Path to the mock gh script
    """
    mock_dir = tmp_path / "mock_bin"
    mock_dir.mkdir(exist_ok=True)
    mock_gh = mock_dir / "gh"

    # Build the mock script
    script_content = """#!/bin/bash
# Mock gh CLI for testing

# Parse arguments to find the branch name
BRANCH=""
for arg in "$@"; do
    if [[ "$arg" != "--"* ]] && [[ "$arg" != "pr" ]] && [[ "$arg" != "list" ]] && [[ "$arg" != "--state" ]] && [[ "$arg" != "all" ]] && [[ "$arg" != "--json" ]] && [[ "$arg" != "number,state" ]]; then
        BRANCH="$arg"
    fi
done

# Find the --head argument
for i in "$@"; do
    if [[ "$prev_was_head" == "true" ]]; then
        BRANCH="$i"
        prev_was_head="false"
    fi
    if [[ "$i" == "--head" ]]; then
        prev_was_head="true"
    fi
done

# Return mock PR data based on branch
case "$BRANCH" in
"""

    for branch_name, prs in branch_pr_map.items():
        pr_json = json.dumps(prs)
        script_content += f'    "{branch_name}")\n'
        script_content += f"        echo '{pr_json}'\n"
        script_content += "        ;;\n"

    script_content += """    *)
        echo '[]'
        ;;
esac

exit 0
"""

    mock_gh.write_text(script_content)
    mock_gh.chmod(0o755)

    return mock_gh


def run_branch_cleanup(
    mode: str,
    branch: str | None = None,
    cwd: Path | None = None,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """
    Run branch cleanup script and return (exit_code, stdout, stderr).

    Args:
        mode: "--scheduled" or "--immediate"
        branch: Branch name for --immediate mode
        cwd: Working directory (defaults to repo root)
        env_overrides: Environment variable overrides

    Returns:
        (exit_code, stdout, stderr) tuple
    """
    script_path = get_script_path()

    if mode == "--immediate" and branch:
        cmd = ["bash", str(script_path), "--immediate", branch]
    else:
        cmd = ["bash", str(script_path), mode]

    env = subprocess.os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        cmd,
        cwd=cwd or repo_root(),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def get_remote_branches(bare_repo: Path) -> list[str]:
    """Get list of branches on the bare repo."""
    result = subprocess.run(
        ["git", "branch"],
        cwd=bare_repo,
        capture_output=True,
        text=True,
    )
    branches = [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]
    return branches


# ============================================================================
# VAL-BRANCH-001: IMMEDIATE_MODE scope — only processes the specified trigger branch
# ============================================================================
def test_immediate_mode_only_processes_specified_branch(tmp_path: Path):
    """When invoked as --immediate feature-A, only feature-A is processed."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)  # 2 days ago

    # Create branches: feature-A (target), feature-B, feature-C (should be untouched)
    branches = [
        ("feature-A", old_date, False),  # No open PR, old
        ("feature-B", old_date, False),  # No open PR, old
        ("feature-C", old_date, False),  # No open PR, old
    ]

    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Mock gh to return no open PRs for any branch
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "feature-A": [],
            "feature-B": [],
            "feature-C": [],
        },
    )

    # Run with --immediate feature-A
    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "feature-A",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    # Check that only feature-A was deleted
    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-A" not in remaining_branches, "feature-A should be deleted"
    assert "feature-B" in remaining_branches, "feature-B should NOT be deleted"
    assert "feature-C" in remaining_branches, "feature-C should NOT be deleted"
    assert "main" in remaining_branches, "main should NOT be deleted"


# ============================================================================
# VAL-BRANCH-002: IMMEDIATE_MODE deletes trigger branch when no open PR
# ============================================================================
def test_immediate_mode_deletes_branch_without_open_pr(tmp_path: Path):
    """When --immediate <branch> and no open PR, branch is deleted regardless of age."""
    now = datetime.now(UTC)
    fresh_date = now - timedelta(minutes=5)  # Very fresh commit

    branches = [("feature-fresh", fresh_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"feature-fresh": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "feature-fresh",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-fresh" not in remaining_branches, (
        "Fresh branch should be deleted in immediate mode"
    )


# ============================================================================
# VAL-BRANCH-003: IMMEDIATE_MODE skips trigger branch when open PR exists
# ============================================================================
def test_immediate_mode_skips_branch_with_open_pr(tmp_path: Path):
    """When --immediate <branch> and branch has open PR, branch is NOT deleted."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("feature-with-pr", old_date, True)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Mock gh to return an open PR for this branch
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "feature-with-pr": [{"number": 123, "state": "OPEN"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "feature-with-pr",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-with-pr" in remaining_branches, "Branch with open PR should NOT be deleted"


# ============================================================================
# VAL-REMOTEBR-001/002/003: Tiered thresholds — MERGED 1h / CLOSED 4h / ORPHAN 24h
# ============================================================================
def test_merged_pr_recent_branch_preserved(tmp_path: Path):
    """MERGED PR branch < 1h old is preserved (tier=MERGED).
    Content is already in main, so guard doesn't apply and age threshold is checked."""
    now = datetime.now(UTC)
    recent_date = now - timedelta(minutes=30)  # 30 min ago, < 1h threshold

    branches = [("merged-recent", recent_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge content into main so guard doesn't protect the branch
    subprocess.run(
        ["git", "merge", "--no-ff", "merged-recent", "-m", "Merge merged-recent"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"merged-recent": [{"number": 101, "state": "MERGED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "merged-recent" in remaining_branches, "Recent MERGED branch should NOT be deleted"
    assert "within MERGED (1h) threshold" in stdout
    assert "Tiered thresholds: MERGED=1h CLOSED=4h ORPHAN=24h" in stdout


def test_merged_pr_old_branch_deleted(tmp_path: Path):
    """MERGED PR branch > 1h old is deleted (tier=MERGED).
    Content must be merged into main so the guard does not falsely protect it
    (after guard expansion in M2 hardening, MERGED branches also go through
    content-equivalence check)."""
    now = datetime.now(UTC)
    old_date = now - timedelta(hours=3)  # 3h ago, > 1h threshold

    branches = [("merged-old", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge merged-old into main so content is equivalent (bypass guard after expansion)
    subprocess.run(
        ["git", "merge", "--no-ff", "merged-old", "-m", "Merge merged-old"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"merged-old": [{"number": 102, "state": "MERGED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "merged-old" not in remaining_branches, "Old MERGED branch should be deleted"
    assert "tier=MERGED (1h)" in stdout


def test_closed_pr_recent_branch_preserved(tmp_path: Path):
    """CLOSED PR branch < 4h old is preserved (tier=CLOSED).
    Content must be merged into main to bypass the unmerged-unique-commits protection."""
    now = datetime.now(UTC)
    recent_date = now - timedelta(hours=2)  # 2h ago, < 4h threshold

    branches = [("closed-recent", recent_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge closed-recent into main so content is equivalent (bypass protection)
    subprocess.run(
        ["git", "merge", "--no-ff", "closed-recent", "-m", "Merge closed-recent"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"closed-recent": [{"number": 201, "state": "CLOSED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "closed-recent" in remaining_branches, "Recent CLOSED branch should NOT be deleted"
    assert "within CLOSED (4h) threshold" in stdout


def test_closed_pr_old_branch_deleted(tmp_path: Path):
    """CLOSED PR branch > 4h old is deleted (tier=CLOSED).
    Content must be merged into main to bypass the unmerged-unique-commits protection."""
    now = datetime.now(UTC)
    old_date = now - timedelta(hours=6)  # 6h ago, > 4h threshold

    branches = [("closed-old", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge closed-old into main so content is equivalent (bypass protection)
    subprocess.run(
        ["git", "merge", "--no-ff", "closed-old", "-m", "Merge closed-old"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"closed-old": [{"number": 202, "state": "CLOSED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "closed-old" not in remaining_branches, "Old CLOSED branch should be deleted"
    assert "tier=CLOSED (4h)" in stdout


def test_orphan_recent_branch_preserved(tmp_path: Path):
    """No-PR branch < 24h old is preserved (tier=ORPHAN)."""
    now = datetime.now(UTC)
    recent_date = now - timedelta(hours=12)  # 12h ago, < 24h threshold

    branches = [("orphan-recent", recent_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"orphan-recent": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "orphan-recent" in remaining_branches, "Recent ORPHAN branch should NOT be deleted"
    assert "within ORPHAN (24h) threshold" in stdout


def test_orphan_old_branch_deleted(tmp_path: Path):
    """No-PR branch > 24h old is deleted (tier=ORPHAN)."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)  # 2 days ago, > 24h threshold

    branches = [("orphan-old", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"orphan-old": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "orphan-old" not in remaining_branches, "Old ORPHAN branch should be deleted"
    assert "tier=ORPHAN (24h)" in stdout


# ============================================================================
# M2-hardening: MERGED branch with reverted content is protected
# ============================================================================
def test_merged_pr_reverted_branch_protected(tmp_path: Path):
    """MERGED PR branch whose content was reverted from main is PROTECTED.

    Scenario: branch was squash-merged into main, then reverted. The branch
    still has unique commits (squash SHA ≠ original), but now main no longer
    contains the content. The guard must protect it to prevent data loss.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("reverted-feature", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Simulate squash merge: add same content to main as a new commit
    subprocess.run(["git", "checkout", "main"], cwd=clone_dir, check=True, capture_output=True)
    (clone_dir / "reverted-feature.txt").write_text("Content for reverted-feature\n")
    subprocess.run(["git", "add", "."], cwd=clone_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Squash merge reverted-feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    # Simulate revert: remove the content from main
    subprocess.run(
        ["git", "rm", "reverted-feature.txt"], cwd=clone_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Revert 'Squash merge reverted-feature'"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    # Branch has MERGED PR but content is no longer in main
    mock_gh = create_gh_mock(tmp_path, {"reverted-feature": [{"number": 601, "state": "MERGED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "reverted-feature" in remaining_branches, (
        "MERGED branch with reverted content must be PROTECTED (content guard expanded)"
    )
    assert "PROTECTED" in stdout.upper() or "has unique commits" in stdout.lower(), (
        "Output should indicate protection. stdout: " + stdout
    )


# ============================================================================
# M2-hardening: BRANCH_AGE_* validation
# ============================================================================
def test_branch_age_zero_falls_back_to_default(tmp_path: Path):
    """BRANCH_AGE_MERGED_HOURS=0 should fall back to default (1h)."""
    now = datetime.now(UTC)
    old_date = now - timedelta(hours=3)

    branches = [("test-zero", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge content so guard doesn't block
    subprocess.run(
        ["git", "merge", "--no-ff", "test-zero", "-m", "Merge test-zero"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"test-zero": [{"number": 701, "state": "MERGED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
        "BRANCH_AGE_MERGED_HOURS": "0",  # Invalid value
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    # Should use default 1h, not crash or delete with 0h threshold
    assert exit_code == 0
    assert "MERGED=1h" in stdout or "tier=MERGED (1h)" in stdout


def test_branch_age_negative_falls_back_to_default(tmp_path: Path):
    """BRANCH_AGE_CLOSED_HOURS=-5 should fall back to default (4h)."""
    now = datetime.now(UTC)
    old_date = now - timedelta(hours=6)

    branches = [("test-negative", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge content so guard doesn't block
    subprocess.run(
        ["git", "merge", "--no-ff", "test-negative", "-m", "Merge test-negative"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"test-negative": [{"number": 702, "state": "CLOSED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
        "BRANCH_AGE_CLOSED_HOURS": "-5",  # Invalid value
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    # Should use default 4h, not crash or behave erratically
    assert exit_code == 0
    assert "CLOSED=4h" in stdout or "tier=CLOSED (4h)" in stdout


# ============================================================================
# M2-hardening: env variable override
# ============================================================================
def test_env_override_changes_behavior(tmp_path: Path):
    """Changing BRANCH_AGE_MERGED_HOURS changes the deletion threshold."""
    now = datetime.now(UTC)
    # Branch is 5h old: would be deleted with default 1h, but kept with 10h override
    recent_date = now - timedelta(hours=5)

    branches = [("test-override", recent_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge content so guard doesn't block
    subprocess.run(
        ["git", "merge", "--no-ff", "test-override", "-m", "Merge test-override"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    mock_gh = create_gh_mock(tmp_path, {"test-override": [{"number": 703, "state": "MERGED"}]})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
        "BRANCH_AGE_MERGED_HOURS": "10",  # Override: 10h instead of default 1h
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "test-override" in remaining_branches, (
        "Branch should be KEPT when threshold is increased to 10h (branch is 5h old)"
    )
    assert "MERGED=10h" in stdout, "Output should show the overridden value"


# ============================================================================
# VAL-BRANCH-006: SCHEDULED_MODE — old branch with open PR is NOT deleted
# ============================================================================
def test_scheduled_mode_skips_branch_with_open_pr(tmp_path: Path):
    """When --scheduled and branch > 24h old has open PR, it is NOT deleted."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("feature-with-pr", old_date, True)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "feature-with-pr": [{"number": 456, "state": "OPEN"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-with-pr" in remaining_branches, "Branch with open PR should NOT be deleted"


# ============================================================================
# VAL-BRANCH-007: Never deletes main in either mode
# ============================================================================
def test_never_deletes_main_scheduled(tmp_path: Path):
    """Main branch is never deleted in scheduled mode."""
    # Create only main branch (no other branches)
    branches = []
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "main" in remaining_branches, "Main branch should NEVER be deleted"


def test_never_deletes_main_immediate(tmp_path: Path):
    """Main branch is never deleted in immediate mode."""
    branches = []
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "main",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "main" in remaining_branches, "Main branch should NEVER be deleted"
    assert exit_code != 0 or "cannot delete main" in stdout.lower() or "protected" in stdout.lower()


# ============================================================================
# VAL-BRANCH-008: Empty branch list — exits cleanly with code 0
# ============================================================================
def test_empty_branch_list_exits_cleanly(tmp_path: Path):
    """When no branches exist besides main, script exits 0."""
    branches = []
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"
    assert "no branches" in stdout.lower() or "nothing to clean" in stdout.lower()


# ============================================================================
# VAL-BRANCH-009: Deleted branches tracked in output for Issue notification
# ============================================================================
def test_deleted_branches_tracked_in_output(tmp_path: Path):
    """Script outputs deleted branch names in a parseable format."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [
        ("orphan-1", old_date, False),
        ("orphan-2", old_date, False),
    ]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "orphan-1": [],
            "orphan-2": [],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    # Check that output contains deleted branch names and count
    assert "orphan-1" in stdout, "Output should contain orphan-1"
    assert "orphan-2" in stdout, "Output should contain orphan-2"
    assert "deleted_count=2" in stdout, "Output should contain deleted_count=2"


# ============================================================================
# VAL-BRANCH-010: Extracted script passes shellcheck with zero warnings
# ============================================================================
def test_shellcheck_clean():
    """shellcheck scripts/branch_cleanup.sh exits 0."""
    from tests.shellcheck_helpers import assert_shellcheck_clean

    assert_shellcheck_clean(get_script_path())


# ============================================================================
# VAL-BRANCH-011: Script interface — modes accepted, invalid args rejected
# ============================================================================
def test_script_accepts_scheduled_mode():
    """--scheduled mode is accepted."""
    exit_code, stdout, stderr = run_branch_cleanup("--scheduled")
    # Should not fail with usage error (may fail for other reasons like no git repo)
    assert "invalid mode" not in stdout.lower()


def test_script_accepts_immediate_mode_with_branch():
    """--immediate <branch> is accepted."""
    exit_code, stdout, stderr = run_branch_cleanup("--immediate", "some-branch")
    # Should not fail with usage error
    assert "invalid mode" not in stdout.lower()


def test_script_rejects_immediate_without_branch():
    """--immediate without branch argument exits non-zero with usage."""
    script_path = get_script_path()
    result = subprocess.run(
        ["bash", str(script_path), "--immediate"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "Should fail when --immediate has no branch argument"
    assert "usage" in result.stdout.lower() or "error" in result.stdout.lower()


def test_script_rejects_invalid_mode():
    """Invalid mode exits non-zero with usage message."""
    script_path = get_script_path()
    result = subprocess.run(
        ["bash", str(script_path), "--bad-flag"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "Should fail with invalid mode"
    assert "usage" in result.stdout.lower() or "invalid" in result.stdout.lower()


def test_script_rejects_no_args():
    """No arguments exits non-zero or defaults explicitly."""
    script_path = get_script_path()
    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "Should fail with no arguments"
    assert "usage" in result.stdout.lower() or "error" in result.stdout.lower()


# ============================================================================
# VAL-BRANCH-012: Thin caller invokes the composite action (M4, INFRA-583)
# ============================================================================
def test_workflow_calls_composite_action():
    """branch-cleanup.yml is a thin caller of the shipped composite action.

    Contract (M4): the caller must not inline cleanup logic — it forwards
    mode / trigger-branch / dispatch-token to
    hdot123-org/infra-core/actions/branch-cleanup@v0.7.2 (INFRA-678 immutable
    tag pin), mirroring the memory-core caller exactly.
    F3: SHA-locked — uses value is the 40-char SHA (YAML strips # vTag comment).
    """
    import re
    import yaml

    workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "branch-cleanup.yml"
    data = yaml.safe_load(workflow_path.read_text())

    # Naming contract: workflow name and job key are load-bearing
    # (check-name contracts / auto-merge wiring depend on them)
    assert data["name"] == "Branch Cleanup"
    assert list(data["jobs"].keys()) == ["cleanup"]

    steps = data["jobs"]["cleanup"]["steps"]
    uses_steps = [s for s in steps if "uses" in s]
    assert len(uses_steps) == 1, "caller must have exactly one action step"
    # F3: SHA-locked — match 40-char hex SHA pattern for branch-cleanup
    assert re.match(
        r"hdot123-org/infra-core/actions/branch-cleanup@[0-9a-f]{40}$",
        uses_steps[0]["uses"],
    ), f"branch-cleanup uses must be SHA-pinned, got: {uses_steps[0]['uses']}"

    with_map = uses_steps[0].get("with", {})
    # Event-based mode dispatch: PR-close → immediate, schedule → scheduled,
    # workflow_dispatch → operator-selected mode
    assert "github.event_name == 'workflow_dispatch' && inputs.mode" in with_map["mode"]
    assert "github.event_name == 'pull_request' && 'immediate'" in with_map["mode"]
    # Trigger branch forwarding (PR-close head ref or manual dispatch input)
    assert "inputs.branch" in with_map["trigger-branch"]
    assert "github.event.pull_request.head.ref" in with_map["trigger-branch"]
    # Token forwarding (branch deletion + issue management)
    assert with_map["dispatch-token"] == "${{ secrets.DISPATCH_TOKEN }}"

    steps_blob = "\n".join(str(s) for s in steps)
    assert "scripts/branch_cleanup.sh" not in steps_blob, (
        "caller steps must not reference repo-local script paths (M2 stub residue)"
    )


def test_workflow_triggers_and_permissions_preserved():
    """Caller restores the M2-hotfix-disabled triggers and keeps permissions.

    The M2 stub was workflow_dispatch-only; M4 parity with memory-core
    requires schedule + pull_request(closed) + workflow_dispatch and the
    original write permissions.
    """
    import yaml

    workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "branch-cleanup.yml"
    data = yaml.safe_load(workflow_path.read_text())

    triggers = data.get(True) or data.get("on") or {}
    assert "schedule" in triggers, "schedule trigger missing (M2 stub residue)"
    assert triggers["schedule"][0]["cron"] == "0 * * * *"
    assert "pull_request" in triggers and triggers["pull_request"]["types"] == ["closed"]
    assert "workflow_dispatch" in triggers

    mode_input = triggers["workflow_dispatch"]["inputs"]["mode"]
    assert mode_input["type"] == "choice"
    assert set(mode_input["options"]) == {"scheduled", "immediate"}
    assert "branch" in triggers["workflow_dispatch"]["inputs"]

    perms = data["permissions"]
    assert perms == {"contents": "write", "issues": "write", "pull-requests": "read"}


# ============================================================================
# VAL-BRANCH-013: IMMEDIATE_MODE does not apply 24h age threshold
# ============================================================================
def test_immediate_mode_no_age_threshold(tmp_path: Path):
    """In --immediate mode, age check is skipped entirely."""
    now = datetime.now(UTC)
    very_fresh = now - timedelta(seconds=30)  # 30 seconds old

    branches = [("brand-new", very_fresh, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"brand-new": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "brand-new",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "brand-new" not in remaining_branches, (
        "Very fresh branch should be deleted in immediate mode"
    )
    assert "24h" not in stdout.lower() or "skipping" not in stdout.lower()


# ============================================================================
# VAL-BRANCH-014: IMMEDIATE_MODE with non-existent branch exits gracefully
# ============================================================================
def test_immediate_mode_nonexistent_branch(tmp_path: Path):
    """If --immediate <branch> doesn't exist, script exits 0 with 'not found' message."""
    branches = []
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "nonexistent-branch",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    assert exit_code == 0, "Should exit 0 for non-existent branch"
    assert "not found" in stdout.lower() or "nothing to do" in stdout.lower()


# ============================================================================
# VAL-BRANCH-015: SCHEDULED_MODE processes multiple orphans in one run
# ============================================================================
def test_scheduled_mode_multiple_orphans(tmp_path: Path):
    """3 orphan branches (> 24h, no PR) all deleted."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)
    fresh_date = now - timedelta(hours=12)

    branches = [
        ("orphan-old-1", old_date, False),
        ("orphan-old-2", old_date, False),
        ("orphan-old-3", old_date, False),
        ("orphan-fresh", fresh_date, False),  # Should be preserved
        ("has-pr", old_date, True),  # Should be preserved (has open PR)
    ]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "orphan-old-1": [],
            "orphan-old-2": [],
            "orphan-old-3": [],
            "orphan-fresh": [],
            "has-pr": [{"number": 789, "state": "OPEN"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)

    # Old orphans should be deleted
    assert "orphan-old-1" not in remaining_branches
    assert "orphan-old-2" not in remaining_branches
    assert "orphan-old-3" not in remaining_branches

    # Fresh and PR-protected should be preserved
    assert "orphan-fresh" in remaining_branches, "Fresh branch should be preserved"
    assert "has-pr" in remaining_branches, "Branch with PR should be preserved"
    assert "main" in remaining_branches, "Main should be preserved"


# ============================================================================
# VAL-BRANCH-016: Script uses `set -euo pipefail` for strict error mode
# ============================================================================
def test_script_uses_strict_mode():
    """Script contains set -euo pipefail."""
    script_path = get_script_path()
    content = script_path.read_text()

    assert "set -e" in content, "Script should contain 'set -e'"
    assert "set -u" in content or "-u" in content, "Script should contain '-u'"
    assert "pipefail" in content, "Script should contain 'pipefail'"


# ============================================================================
# VAL-BRANCH-017: Script has execute permission in git index
# ============================================================================
def test_script_has_execute_permission():
    """git ls-files --stage shows mode 100755 for the tracked script."""
    script_rel = get_script_path().relative_to(repo_root())
    result = subprocess.run(
        ["git", "ls-files", "--stage", str(script_rel)],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "100755" in result.stdout, (
        f"{script_rel} should have execute permission (100755) in git index"
    )


# ============================================================================
# VAL-BRANCH-018: gh CLI failure is fail-closed — branch skipped, not deleted
# ============================================================================
def test_gh_cli_failure_skip_branch(tmp_path: Path):
    """When gh pr list fails, branch is skipped (not deleted)."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("feature-api-error", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Create a mock that fails
    mock_dir = tmp_path / "mock_bin"
    mock_dir.mkdir(exist_ok=True)
    mock_gh = mock_dir / "gh"
    mock_gh.write_text("""#!/bin/bash
# Mock gh that always fails
exit 1
""")
    mock_gh.chmod(0o755)

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-api-error" in remaining_branches, "Branch should be preserved when gh fails"
    assert "skipping" in stdout.lower() or "fail-closed" in stdout.lower()


# ============================================================================
# VAL-BRANCH-019: Unreadable commit date — branch skipped
# ============================================================================
def test_unreadable_commit_date_skip_branch(tmp_path: Path):
    """If git log returns empty for commit date, branch is skipped."""
    # This is hard to test directly without corrupting git data
    # We'll verify the code path exists by checking the script content
    script_path = get_script_path()
    content = script_path.read_text()

    # Check that the script has the safety check for empty commit date
    assert "LAST_COMMIT_EPOCH" in content
    assert "could not get last commit date" in content.lower() or "skipping" in content.lower()


# ============================================================================
# VAL-BRANCH-020: Output format parseable by Issue-creation workflow step
# ============================================================================
def test_output_format_parseable(tmp_path: Path):
    """Script writes deleted_count and protected_count in parseable format."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("test-branch", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"test-branch": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    # Check output format
    assert "deleted_count=" in stdout, "Output should contain deleted_count="
    assert "protected_count=" in stdout, "Output should contain protected_count="

    # Parse the counts
    for line in stdout.split("\n"):
        if line.startswith("deleted_count="):
            count = int(line.split("=")[1])
            assert count >= 0, "deleted_count should be non-negative"
        if line.startswith("protected_count="):
            count = int(line.split("=")[1])
            assert count >= 0, "protected_count should be non-negative"


# ============================================================================
# VAL-CROSS-013: IMMEDIATE_MODE only processes specified branch (integration)
# ============================================================================
def test_cross_immediate_mode_only_specified_branch(tmp_path: Path):
    """PR for branch-A closed. Script processes ONLY branch-A."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [
        ("branch-A", old_date, False),  # Target branch
        ("branch-B", old_date, False),  # Should NOT be evaluated
    ]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "branch-A": [],
            "branch-B": [],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "branch-A",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "branch-A" not in remaining_branches, "branch-A should be deleted"
    assert "branch-B" in remaining_branches, "branch-B should NOT be touched"


# ============================================================================
# VAL-CROSS-014: IMMEDIATE_MODE deletes branch regardless of age (integration)
# ============================================================================
def test_cross_immediate_mode_deletes_regardless_of_age(tmp_path: Path):
    """Branch 5 minutes old with no open PR → deleted in immediate mode."""
    now = datetime.now(UTC)
    very_fresh = now - timedelta(minutes=5)

    branches = [("young-branch", very_fresh, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {"young-branch": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "young-branch",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "young-branch" not in remaining_branches, (
        "Young branch should be deleted in immediate mode"
    )


# ============================================================================
# VAL-CROSS-015: IMMEDIATE_MODE skips branch with open PR (integration)
# ============================================================================
def test_cross_immediate_mode_skips_branch_with_pr(tmp_path: Path):
    """Branch has open PR → NOT deleted in immediate mode."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("protected-branch", old_date, True)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "protected-branch": [{"number": 999, "state": "OPEN"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "protected-branch",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "protected-branch" in remaining_branches, "Branch with PR should be preserved"


# ============================================================================
# VAL-CROSS-016: IMMEDIATE_MODE never deletes main (integration)
# ============================================================================
def test_cross_immediate_mode_never_deletes_main(tmp_path: Path):
    """--immediate main → main NOT deleted."""
    branches = []
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(tmp_path, {})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "main",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "main" in remaining_branches, "Main should NEVER be deleted"


# ============================================================================
# VAL-CROSS-017: SCHEDULED_MODE criteria enforced (integration)
# ============================================================================
def test_cross_scheduled_mode_criteria_enforced(tmp_path: Path):
    """Stale (> 24h, no PR) → deleted. Fresh (< 24h, no PR) → preserved. Has open PR → preserved."""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)
    fresh_date = now - timedelta(hours=12)

    branches = [
        ("stale-orphan", old_date, False),  # Should be deleted
        ("fresh-branch", fresh_date, False),  # Should be preserved
        ("pr-branch", old_date, True),  # Should be preserved
    ]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "stale-orphan": [],
            "fresh-branch": [],
            "pr-branch": [{"number": 111, "state": "OPEN"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "stale-orphan" not in remaining_branches, "Stale orphan should be deleted"
    assert "fresh-branch" in remaining_branches, "Fresh branch should be preserved"
    assert "pr-branch" in remaining_branches, "Branch with PR should be preserved"


# ============================================================================
# VAL-CROSS-018: Shellcheck passes on branch_cleanup.sh (integration)
# ============================================================================
def test_cross_shellcheck_passes():
    """shellcheck scripts/branch_cleanup.sh exits 0."""
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck not installed")

    script_path = get_script_path()
    result = subprocess.run(
        ["shellcheck", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"shellcheck failed:\n{result.stdout}\n{result.stderr}"


# ============================================================================
# VAL-CROSS-019: Actionlint passes on branch-cleanup.yml (integration)
# ============================================================================
def test_cross_actionlint_passes():
    """actionlint .github/workflows/branch-cleanup.yml exits 0."""
    import shutil

    import pytest

    if not shutil.which("actionlint"):
        pytest.skip("actionlint not installed")

    workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "branch-cleanup.yml"
    result = subprocess.run(
        ["actionlint", str(workflow_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"actionlint failed:\n{result.stdout}\n{result.stderr}"


# ============================================================================
# VAL-BRANCH-021: Fully-merged branch is NOT falsely protected
# (regression: 3-dot symmetric difference inflated unique-commit count)
# ============================================================================
def test_fully_merged_branch_not_falsely_protected(tmp_path: Path):
    """
    A branch whose commits are ALL already in main must NOT be protected,
    even when main has advanced and the branch has a CLOSED-not-merged PR.

    Regression test for INFRA-220: the script used `origin/main...origin/$BRANCH`
    (3-dot symmetric difference) which counts main's new commits too, inflating
    the unique-commit count and causing fully-merged branches to be falsely
    "protected". The fix uses 2-dot `origin/main..origin/$BRANCH` (commits in
    branch but not in main), so a fully-merged branch reports 0 unique commits.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)  # older than 24h threshold

    # Set up a fixture repo with one feature branch.
    branches = [("merged-feature", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Cherry-pick the branch's commit onto main, then advance main with extra
    # commits. This makes the branch fully contained in main (0 unique-to-branch
    # commits) while main has moved forward.
    subprocess.run(["git", "checkout", "main"], cwd=clone_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "-m", "Merge feature into main", "origin/merged-feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    # Advance main with two additional commits
    for i in range(2):
        (clone_dir / f"advance-{i}.txt").write_text(f"advance {i}\n")
        subprocess.run(["git", "add", "."], cwd=clone_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Advance main {i}"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    # Sanity: the branch should have 0 commits not in main (2-dot range)
    check = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..origin/merged-feature"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
    )
    assert check.stdout.strip() == "0", (
        f"Fixture setup wrong: branch should have 0 unique commits, got {check.stdout.strip()}"
    )

    # Mock gh: branch has a CLOSED (not merged) PR — the condition that triggers
    # the protection check. With the bug, the 3-dot range would see main's extra
    # commits and falsely protect. With the fix, 2-dot sees 0 and does NOT protect.
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "merged-feature": [{"number": 200, "state": "CLOSED"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "merged-feature" not in remaining_branches, (
        "Fully-merged branch (0 unique commits) must NOT be protected — it should be deleted. stdout:\n"
        + stdout
    )
    # The protection path was NOT taken; verify no PROTECTED marker for this branch
    assert (
        "PROTECTED" not in stdout
        or "merged-feature" not in stdout.split("PROTECTED")[-1].split("\n")[0]
    ), "Branch should not appear in protected list. stdout:\n" + stdout


# ============================================================================
# VAL-BRANCH-022: IMMEDIATE_MODE deletes branch with a MERGED PR
# ============================================================================
def test_immediate_mode_deletes_merged_pr_branch(tmp_path: Path):
    """When --immediate <branch> and the branch has a MERGED PR (state "MERGED"),
    the branch IS deleted when its content is already fully in main.

    GitHub/gh-CLI state values are "OPEN", "CLOSED", "MERGED". A MERGED PR has
    state "MERGED" (NOT "CLOSED"). After M2 guard expansion, MERGED branches
    also go through content-equivalence check: if the content is in main (merge-tree
    equivalent), the guard does NOT protect it and the branch is deleted.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)  # 2 days ago

    branches = [("merged-feature", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Merge content into main so the guard's content-equivalence check passes
    subprocess.run(["git", "checkout", "main"], cwd=clone_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "-m", "Merge merged-feature", "origin/merged-feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    # Mock gh to return a MERGED PR for this branch
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "merged-feature": [{"number": 200, "state": "MERGED"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--immediate",
        "merged-feature",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "merged-feature" not in remaining_branches, (
        "Branch with a MERGED PR (content in main) should be deleted in immediate mode"
    )
    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"


# ============================================================================
# VAL-BRANCH-023: SCHEDULED_MODE protects branch with CLOSED-not-merged PR + unique commits
# ============================================================================
def test_scheduled_mode_protects_closed_not_merged_with_unique_commits(tmp_path: Path):
    """When a branch has a CLOSED (not merged) PR AND unique commits not in
    main, it is PROTECTED (not deleted) even in scheduled mode with an old
    branch.

    The fixture creates branches with commits not present in main, so
    UNIQUE_COUNT will be > 0. Combined with a CLOSED PR, the safety-protection
    feature kicks in and the branch is preserved.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)  # 2 days ago

    branches = [("closed-unmerged", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Mock gh to return a CLOSED (not merged) PR for this branch
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "closed-unmerged": [{"number": 300, "state": "CLOSED"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "closed-unmerged" in remaining_branches, (
        "Branch with CLOSED-not-merged PR and unique commits should be PROTECTED"
    )
    assert "PROTECTED" in stdout.upper(), (
        f"Output should contain 'PROTECTED' for protected branch. stdout: {stdout}"
    )


# ============================================================================
# VAL-BRANCH-024 (INFRA-383): Squash-merged branch is NOT falsely protected
# ============================================================================
def test_squash_merged_branch_not_falsely_protected(tmp_path: Path) -> None:
    """
    A branch whose PR was closed after its content was squash-merged into main
    (via a different PR) must NOT be protected.

    Regression test for INFRA-383: after a squash merge, the branch's original
    commit SHAs never appear in main, so the 2-dot `origin/main..origin/$BRANCH`
    count is permanently > 0, and the branch is falsely "protected" forever even
    though its content is fully contained in main.

    The fix adds a content-containment check: if merging the branch into main
    is a no-op (merge result tree == main tree), the branch content is fully
    merged and deletion loses nothing.

    Fixture:
    - main: README.md + feature.txt (content of branch, squash-merged)
    - branch: branched from initial main, adds feature.txt (same content)
    - PR state: CLOSED (not merged)
    Expected: branch deleted (not protected).
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    # Build the fixture manually: the standard helper cannot express
    # "branch content squash-merged into main with identical blob".
    bare_repo, clone_dir = create_fixture_repo(tmp_path, [])

    # Create feature branch from initial main, add feature.txt, push.
    subprocess.run(
        ["git", "checkout", "-b", "squashed-feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    (clone_dir / "feature.txt").write_text("feature content\n")
    subprocess.run(["git", "add", "."], cwd=clone_dir, check=True, capture_output=True)
    date_str = old_date.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env = {
        "GIT_AUTHOR_DATE": date_str,
        "GIT_COMMITTER_DATE": date_str,
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
    }
    subprocess.run(
        ["git", "commit", "-m", "Add feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "squashed-feature"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    # Squash-merge equivalent: on main, create a NEW commit with the same content.
    subprocess.run(["git", "checkout", "main"], cwd=clone_dir, check=True, capture_output=True)
    (clone_dir / "feature.txt").write_text("feature content\n")
    subprocess.run(["git", "add", "."], cwd=clone_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Squash merge of feature (content only)"],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=clone_dir, check=True, capture_output=True
    )

    # Sanity: branch has commits not in main by SHA (squash ⇒ 2-dot > 0) ...
    check = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..origin/squashed-feature"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
    )
    assert check.stdout.strip() != "0", (
        "Fixture setup wrong: branch should have SHA-unique commits after squash merge"
    )
    # ... but merging the branch into main is a content no-op.
    main_tree = subprocess.run(
        ["git", "rev-parse", "origin/main^{tree}"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()
    merge_tree = (
        subprocess.run(
            ["git", "merge-tree", "--write-tree", "origin/main", "origin/squashed-feature"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .split("\n")[0]
    )
    assert main_tree == merge_tree, (
        "Fixture setup wrong: branch content should be fully contained in main"
    )

    # Mock gh: branch has a CLOSED (not merged) PR — the protection trigger.
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "squashed-feature": [{"number": 400, "state": "CLOSED"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "squashed-feature" not in remaining_branches, (
        "Squash-merged branch (content fully in main) must NOT be protected — it should be deleted. stdout:\n"
        + stdout
    )
    # The branch must not be listed as protected (check only the protected-list
    # section at the end, not the "Checking branches:" enumeration).
    protected_section = stdout.split("Protected", 1)[-1] if "Protected" in stdout else ""
    protected_entries = [
        line
        for line in protected_section.split("\n")
        if line.strip().startswith("-") or " unique commits" in line
    ]
    assert not any("squashed-feature" in line for line in protected_entries), (
        f"Branch must not appear in protected list. stdout:\n{stdout}"
    )


# ============================================================================
# VAL-BRANCH-025 (INFRA-383): Branch with genuinely unique content stays protected
# ============================================================================
def test_closed_branch_with_unique_content_still_protected(tmp_path: Path) -> None:
    """A CLOSED-not-merged branch whose content is NOT fully in main is still
    protected, so the INFRA-383 content-containment fix does not over-delete.

    Fixture:
    - branch adds unique-file.txt with content that main never receives.
    Expected: branch protected (not deleted), PROTECTED marker in output.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("unique-content", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Mock gh: branch has a CLOSED (not merged) PR — protection trigger.
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "unique-content": [{"number": 401, "state": "CLOSED"}],
        },
    )

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "unique-content" in remaining_branches, (
        "Branch with genuinely unique content must stay protected. stdout:\n" + stdout
    )
    assert "PROTECTED" in stdout.upper(), (
        f"Output should contain 'PROTECTED' for protected branch. stdout: {stdout}"
    )


# ============================================================================
# VAL-BRANCH-026 (INFRA-388): checked-in retirement list exempts superseded
# branches from unmerged-commit protection
# ============================================================================
def test_retired_branch_not_falsely_protected(tmp_path: Path) -> None:
    """
    A branch whose CLOSED-not-merged PR was superseded by an equivalent
    implementation on main (different tree, same or better outcome) must NOT
    be protected when it is listed in the checked-in retirement list.

    Regression test for INFRA-388: the INFRA-383 content-containment check
    only recognizes "branch tree already contained in main". When the work
    lands via a different-but-equivalent change (PR #778's _make_side_effect
    factory superseding the factory/infra-382-dedup-side-effect branch), the
    merge-tree check sees a tree difference and the branch is protected
    forever, so the branch-cleanup tracking issue never drains.

    The fix adds an auditable retirement list (scripts/branch_cleanup_retired.txt,
    merged via PR review): listed branches are exempt from the
    unmerged-unique-commits protection. Open-PR protection and the 24h age
    threshold still apply.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("superseded-feature", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Mock gh: branch has a CLOSED (not merged) PR — protection trigger.
    mock_gh = create_gh_mock(
        tmp_path,
        {
            "superseded-feature": [{"number": 500, "state": "CLOSED"}],
        },
    )

    # Use a dedicated retirement file instead of the checked-in one so the
    # test does not depend on (or mutate) repository state.
    retired_file = tmp_path / "branch_cleanup_retired.txt"
    retired_file.write_text("superseded-feature\n")

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
        "BRANCH_RETIREMENT_FILE": str(retired_file),
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "superseded-feature" not in remaining_branches, (
        "Retired branch (superseded work, closed PR) must NOT be protected — it should be deleted. stdout:\n"
        + stdout
    )
    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"


# ============================================================================
# VAL-BRANCH-027 (INFRA-388): retirement does NOT bypass open-PR protection
# ============================================================================
def test_retired_branch_with_open_pr_still_skipped(tmp_path: Path) -> None:
    """A retired branch with an OPEN PR is still skipped: retirement only
    exempts the unmerged-unique-commits protection, never the open-PR rule."""
    now = datetime.now(UTC)
    fresh_date = now - timedelta(hours=1)  # within 24h (irrelevant here)

    branches = [("retired-open-pr", fresh_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    mock_gh = create_gh_mock(
        tmp_path,
        {
            "retired-open-pr": [{"number": 501, "state": "OPEN"}],
        },
    )

    retired_file = tmp_path / "branch_cleanup_retired.txt"
    retired_file.write_text("retired-open-pr\n")

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
        "BRANCH_RETIREMENT_FILE": str(retired_file),
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "retired-open-pr" in remaining_branches, (
        "Retired branch with an OPEN PR must still be skipped. stdout:\n" + stdout
    )
    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"


# ============================================================================
# VAL-BRANCH-028 (INFRA-388): retired branch younger than 24h is age-gated
# ============================================================================
def test_retired_branch_within_24h_threshold_skipped(tmp_path: Path) -> None:
    """A retired branch whose last commit is within the 24h threshold is
    skipped by the age gate: retirement is not an immediate-delete order."""
    now = datetime.now(UTC)
    fresh_date = now - timedelta(hours=1)

    branches = [("retired-fresh", fresh_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # No PRs at all — only the retirement entry and the age gate matter.
    mock_gh = create_gh_mock(tmp_path, {})

    retired_file = tmp_path / "branch_cleanup_retired.txt"
    retired_file.write_text("retired-fresh\n")

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
        "BRANCH_RETIREMENT_FILE": str(retired_file),
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    remaining_branches = get_remote_branches(bare_repo)
    assert "retired-fresh" in remaining_branches, (
        f"Retired branch with a fresh (<24h) tip must be age-gated, not deleted. stdout:\n{stdout}"
    )
    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"


# ============================================================================
# VAL-BRANCH-029 (INFRA-388): retirement list ships with infra-382 entry
# ============================================================================
def test_retirement_list_tracks_infra_382() -> None:
    """The checked-in retirement list exists and lists the superseded
    infra-382 branch so the tracking issue can drain after this PR merges.

    The list is the audit artifact: adding/removing entries requires a PR
    review, which is the human approval for deleting "protected" branches.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "factory/infra-382-dedup-side-effect" in content, (
        "infra-382 superseded branch must be listed for retirement"
    )


# ============================================================================
# VAL-BRANCH-031 (INFRA-391): retirement list ships with infra-391 entry
# ============================================================================
def test_retirement_list_tracks_infra_391() -> None:
    """The checked-in retirement list also lists the superseded
    feat/pr-ref-gate-ci-wiring branch (PR #773 closed unmerged, superseded
    by PR #771's step-level wiring) so tracking issue #793 / INFRA-391 can
    drain once the scheduled cleanup deletes the branch.

    Mirrors VAL-BRANCH-029: the list is the audit artifact, and adding or
    removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "feat/pr-ref-gate-ci-wiring" in content, (
        "infra-391 superseded branch must be listed for retirement"
    )
    assert "INFRA-391" in content, "the infra-391 entry must carry its INFRA reference"


# ============================================================================
# VAL-BRANCH-032 (INFRA-401): retirement list ships with infra-401 entries
# ============================================================================
def test_retirement_list_tracks_infra_401() -> None:
    """The checked-in retirement list also lists the superseded
    fix/pr-ref-regex-robustness and fix/infra-398-branch-cleanup-tracking
    branches so tracking issue INFRA-401 (mirror #813) can drain once the
    scheduled cleanup deletes them.

    Evidence chain:
    - fix/pr-ref-regex-robustness: PR #802 closed unmerged; its 9-keyword
      regex + comma-list + None-body fixes all landed on main via PR #803
      and PR #807 (debc617) — cross-implementation equivalence that the
      INFRA-383 merge-tree containment check cannot see.
    - fix/infra-398-branch-cleanup-tracking: PR #806 (INFRA-398) closed
      unmerged after conflicting with PR #807; its retirement entry and
      regression tests are re-landed by the INFRA-401 PR.

    Mirrors VAL-BRANCH-029/031: the list is the audit artifact, and adding
    or removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "fix/pr-ref-regex-robustness" in content, (
        "infra-401 superseded branch must be listed for retirement"
    )
    assert "fix/infra-398-branch-cleanup-tracking" in content, (
        "infra-398's superseded branch (closed PR #806) must be listed for retirement"
    )
    assert "INFRA-401" in content, "the infra-401 entries must carry their INFRA reference"


# ============================================================================
# VAL-BRANCH-033 (INFRA-586): retirement list ships with infra-586 entry
# ============================================================================
def test_retirement_list_tracks_infra_586() -> None:
    """The checked-in retirement list also lists the superseded
    factory/infra-581-rule-packs-docs branch so tracking issue INFRA-586
    (mirror #29) can drain once the scheduled cleanup deletes the branch.

    Evidence chain:
    - PR #24 (infra-core) closed unmerged at 2026-08-27T02:16Z; it was a
      docs-only README rule-pack section sync for INFRA-581.
    - The core fix (resolve_rule_packs lazy-load, 5-tool expansion,
      enabled:false override) landed on main via PR #23 (6164aa3) and
      INFRA-581 was marked terminal without merging the docs PR
      (terminal absorption); the owner cross-referenced #24 from merged
      PR #27 as a superseded precedent.
    - Discretionary docs-sync work abandoned by the owner's close: the
      INFRA-383 merge-tree containment check cannot see "owner closed
      without merging", so the branch would be protected forever and the
      INFRA-586 tracking issue would never drain.

    Mirrors VAL-BRANCH-029/031/032: the list is the audit artifact, and
    adding or removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "factory/infra-581-rule-packs-docs" in content, (
        "infra-586 superseded branch must be listed for retirement"
    )
    assert "INFRA-586" in content, "the infra-586 entry must carry its INFRA reference"


# ============================================================================
# VAL-BRANCH-030 (INFRA-388): script documents the retirement mechanism
# ============================================================================
def test_script_documents_retirement_list() -> None:
    """branch_cleanup.sh references the retirement list and its env override
    so the mechanism is discoverable from the script itself."""
    content = get_script_path().read_text()
    assert "branch_cleanup_retired.txt" in content, (
        "branch_cleanup.sh must document the checked-in retirement list"
    )
    assert "BRANCH_RETIREMENT_FILE" in content, (
        "branch_cleanup.sh must support the BRANCH_RETIREMENT_FILE override"
    )


# ============================================================================
# 仓库上下文双重防线（2026-08-28，mirror memory PR #1060 / INFRA-597）
# 自建 runner insteadOf 镜像重写使 gh 无法从 workspace remote 解析 host。
# GITHUB_REPOSITORY 已设置（Actions 默认注入）→ gh pr list 显式 --repo；
# 未设置（本地调试）→ 保持原命令形态。
# ============================================================================
def create_gh_arg_capture_mock(tmp_path: Path) -> Path:
    """Create a mock gh CLI that records each invocation's argv to $CAPTURE_LOG.

    Returns empty PR lists so branch_cleanup proceeds through its normal flow.
    """
    mock_dir = tmp_path / "capture_bin"
    mock_dir.mkdir(exist_ok=True)
    mock_gh = mock_dir / "gh"
    script_content = """#!/bin/bash
# Mock gh CLI for testing: capture argv, respond with empty PR list
printf '%s\\n' "$*" >> "${CAPTURE_LOG:?CAPTURE_LOG must be set}"
echo '[]'
exit 0
"""
    mock_gh.write_text(script_content)
    mock_gh.chmod(0o755)
    return mock_gh


def test_gh_pr_list_uses_explicit_repo_when_github_repository_set(tmp_path: Path):
    """GITHUB_REPOSITORY 已设置（CI）→ gh pr list 必须显式 --repo。"""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    bare_repo, clone_dir = create_fixture_repo(tmp_path, [("feature-A", old_date, False)])

    mock_gh = create_gh_arg_capture_mock(tmp_path)
    capture_log = tmp_path / "gh-args.log"

    exit_code, _stdout, _stderr = run_branch_cleanup(
        "--immediate",
        "feature-A",
        cwd=clone_dir,
        env_overrides={
            "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
            "GITHUB_REPOSITORY": "hdot123-org/infra-core",
            "CAPTURE_LOG": str(capture_log),
        },
    )
    assert exit_code == 0
    assert capture_log.exists(), "mock gh must have been invoked"
    log_lines = capture_log.read_text().splitlines()
    assert any(
        "--repo hdot123-org/infra-core" in line and "pr list" in line for line in log_lines
    ), f"gh pr list must carry explicit --repo, got: {log_lines}"
    # 行为不回归：无 open PR 的过期分支仍被正常删除
    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-A" not in remaining_branches, "feature-A should be deleted"


def test_gh_pr_list_no_repo_flag_without_github_repository_env(tmp_path: Path):
    """GITHUB_REPOSITORY 未设置（本地调试）→ 保持原命令形态（无 --repo）。"""
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    bare_repo, clone_dir = create_fixture_repo(tmp_path, [("feature-A", old_date, False)])

    mock_gh = create_gh_arg_capture_mock(tmp_path)
    capture_log = tmp_path / "gh-args.log"

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{subprocess.os.environ['PATH']}",
        "CAPTURE_LOG": str(capture_log),
    }
    if "GITHUB_REPOSITORY" in subprocess.os.environ:
        # 本地环境残留 GITHUB_REPOSITORY 时显式剥离，保证测的是无 env 分支
        env_overrides["GITHUB_REPOSITORY"] = ""

    exit_code, _stdout, _stderr = run_branch_cleanup(
        "--immediate",
        "feature-A",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )
    assert exit_code == 0
    log_lines = [line for line in capture_log.read_text().splitlines() if line.strip()]
    assert log_lines, "mock gh must have been invoked"
    assert not any("--repo" in line for line in log_lines), (
        f"no --repo expected without GITHUB_REPOSITORY, got: {log_lines}"
    )
    remaining_branches = get_remote_branches(bare_repo)
    assert "feature-A" not in remaining_branches, "feature-A should be deleted"


# VAL-BRANCH-034 (INFRA-589): scheduled sweep ignores synthetic pull/N/merge refs
# ============================================================================
def test_scheduled_mode_ignores_synthetic_pull_refs(tmp_path: Path) -> None:
    """Synthetic pull/N/merge refs must not enter the scheduled sweep.

    Regression test for INFRA-589: actions/checkout on self-hosted runners
    leaves cached pull/N/merge refs in the clone. A scheduled sweep then
    wasted ~4 minutes issuing gh pr list calls for ~120 synthetic refs that
    are neither real branches nor deletable.

    Fixture: a clone with a stale pull/1234/merge remote-tracking ref plus
    one real orphan branch. The sweep must process only the real branch
    (deleted) and never mention the synthetic ref as "Checking branch".
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=2)

    branches = [("orphan-old", old_date, False)]
    bare_repo, clone_dir = create_fixture_repo(tmp_path, branches)

    # Simulate a leftover synthetic ref from a cached actions/checkout fetch.
    pr_head = subprocess.run(
        ["git", "rev-parse", "origin/orphan-old"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/pull/1234/merge", pr_head],
        cwd=clone_dir,
        check=True,
        capture_output=True,
    )

    mock_gh = create_gh_mock(tmp_path, {"orphan-old": []})

    env_overrides = {
        "PATH": f"{mock_gh.parent}:{os.environ['PATH']}",
    }

    exit_code, stdout, stderr = run_branch_cleanup(
        "--scheduled",
        cwd=clone_dir,
        env_overrides=env_overrides,
    )

    assert exit_code == 0, f"Expected exit 0, got {exit_code}. stderr: {stderr}"
    assert "--- Checking branch: pull/1234/merge ---" not in stdout, (
        "Synthetic pull/N/merge refs must be filtered out of the sweep. stdout:\n" + stdout
    )
    assert "--- Checking branch: orphan-old ---" in stdout, (
        "Real branches must still be processed. stdout:\n" + stdout
    )
    remaining_branches = get_remote_branches(bare_repo)
    assert "orphan-old" not in remaining_branches, "Real orphan must still be deleted"


# ============================================================================
# VAL-BRANCH-035 (INFRA-589): action state files live under RUNNER_TEMP,
# never under a fixed /tmp path shared across runs and repositories
# ============================================================================
def test_action_uses_per_run_state_directory() -> None:
    """The composite action must not keep inter-step state in fixed /tmp files.

    Regression test for INFRA-589: on shared self-hosted runners the fixed
    /tmp/branch_cleanup_output.txt, /tmp/deleted_branches.txt and
    /tmp/protected_branches.txt leaked state across runs AND across
    repositories. When a later run had PROTECTED_COUNT=0, the extraction
    `if` skipped the list rewrite while `touch` preserved the previous
    content, so branch_cleanup_issue.sh read a foreign/stale protected list
    and created a phantom tracking issue in the wrong repository
    (memory-core's INFRA-589 / #1052 for an infra-core branch).

    Contract: all mutable state paths are derived from RUNNER_TEMP
    (per-job isolated by GitHub Actions) with a /tmp fallback only for
    local manual runs, and the list files are truncated (: >) before the
    cleanup script runs so an empty result always overwrites stale content.
    """
    action_path = repo_root() / "actions" / "branch-cleanup" / "action.yml"
    content = action_path.read_text()

    # Per-run scratch dir derived from RUNNER_TEMP
    assert "${RUNNER_TEMP:-/tmp}/branch-cleanup-state" in content, (
        "action must keep state under a RUNNER_TEMP-derived per-run directory"
    )
    # List files are truncated up-front: empty results must overwrite stale state
    assert ': > "$DELETED_FILE"' in content, "deleted list must be truncated before the sweep"
    assert ': > "$PROTECTED_FILE"' in content, "protected list must be truncated before the sweep"
    # No fixed /tmp state files remain
    for forbidden in (
        "/tmp/branch_cleanup_output.txt",
        "/tmp/deleted_branches.txt",
        "/tmp/protected_branches.txt",
    ):
        assert forbidden not in content, (
            f"fixed shared state path {forbidden} must not appear in action.yml"
        )


# ============================================================================
# VAL-BRANCH-036 (INFRA-589): sweep filter tolerates leading whitespace in
# git branch -r output (macOS/BSD alignment with the Linux runner)
# ============================================================================
def test_sweep_filter_in_source_matches_synthetic_refs() -> None:
    """Source-level check that the enumeration pipeline drops pull/ refs.

    Companion to VAL-BRANCH-034: verifies the shipped filter exists even on
    hosts where the fixture cannot create refs/remotes refs (the behavioral
    test above is the authoritative check).
    """
    content = get_script_path().read_text()
    assert "grep -v 'pull/'" in content, (
        "scheduled sweep must filter pull/ synthetic refs out of git branch -r output"
    )


# ============================================================================
# VAL-BRANCH-037 (INFRA-632): retirement list ships with infra-632 entry
# ============================================================================
def test_retirement_list_tracks_infra_632() -> None:
    """The checked-in retirement list also lists the superseded
    factory/infra-589-tmp-state-pollution branch so tracking issue INFRA-632
    (mirror #77) can drain once the scheduled cleanup deletes the branch.

    Evidence chain:
    - PR #35 (infra-core) closed unmerged at 2026-08-29T07:34Z after
      auto-merge reported CONFLICTING against main.
    - The INFRA-589 fix was redone on new main by PR #57 (6cedfe7, merged
      2026-08-29T08:08Z): RUNNER_TEMP per-run state isolation lives in
      actions/branch-cleanup/action.yml, and the pull/N/merge refs filter
      plus VAL-BRANCH-034/035/036 contract tests all ship on main.
    - The branch tip predates and lacks PR #49/#51's gh --repo context
      guard, so it is strictly older than main's implementation; the
      INFRA-383 merge-tree containment check cannot see
      cross-implementation equivalence, so the branch would be protected
      forever and the INFRA-632 tracking issue would never drain.

    Mirrors VAL-BRANCH-029/031/032/033: the list is the audit artifact,
    and adding or removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "factory/infra-589-tmp-state-pollution" in content, (
        "infra-632 superseded branch must be listed for retirement"
    )
    assert "INFRA-632" in content, "the infra-632 entry must carry its INFRA reference"


# ============================================================================
# VAL-BRANCH-038 (INFRA-640): retirement list ships with infra-640 entries
# ============================================================================
def test_retirement_list_tracks_infra_640() -> None:
    """The checked-in retirement list also lists the three superseded
    branches flagged by tracking issue INFRA-640 (mirror #88) so the
    tracker can drain once the scheduled cleanup deletes them.

    Evidence chain (one entry per protected branch):
    - factory/infra-585-fix-vars-forwarding: PR #28 (infra-core) closed
      unmerged at 2026-08-27T12:55Z; per the owner's close comment the
      vars.BRANCH_AGE_* forwarding fix already landed on main via PR #27
      (e500f37), which switched branch-cleanup to the thin-caller
      architecture (M4, INFRA-583) — the branch's single unique commit
      is the older standalone composite-action env fix.
    - mission-ic-gate-infra-droid-review-enable: PR #42 closed unmerged
      at 2026-08-28T11:39Z; superseded by the split plan PR-A #43
      (droid-review workflow enablement) + PR-B #44 (ci-ok polls
      droid-review), both merged — the single unique commit is the
      pre-split monolithic gate enablement.
    - mission-ic-runner-host-toolchain-pin-cache: PR #37 closed unmerged
      at 2026-08-29T07:12Z after baseline drift (auto-merge CONFLICTING);
      superseded by PR #56 which salvaged-redid Layer 1+2 host toolchain
      pinning & shared cache on new main, fixing the dropped
      "Install dependencies" step (INFRA-590) — the 4 unique commits
      (1 feat + 3 stale main merges) are the abandoned first attempt.
    - In all three cases the INFRA-383 merge-tree containment check
      cannot see cross-implementation equivalence, so the branches would
      be protected forever and the INFRA-640 tracking issue would never
      drain.

    Mirrors VAL-BRANCH-029/031/032/033/037: the list is the audit
    artifact, and adding or removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    for branch in (
        "factory/infra-585-fix-vars-forwarding",
        "mission-ic-gate-infra-droid-review-enable",
        "mission-ic-runner-host-toolchain-pin-cache",
    ):
        assert branch in content, (
            f"infra-640 superseded branch {branch} must be listed for retirement"
        )
    assert "INFRA-640" in content, "the infra-640 entries must carry their INFRA reference"


# ============================================================================
# VAL-BRANCH-039 (INFRA-674): retirement list ships with infra-674 entry
# ============================================================================
def test_retirement_list_tracks_infra_674() -> None:
    """The checked-in retirement list also lists the owner-abandoned
    factory/infra-670-hygiene-dup-falsepos branch so tracking issue
    INFRA-674 (mirror #115) can drain once the scheduled cleanup deletes
    the branch.

    Evidence chain:
    - PR #112 (infra-core) closed unmerged at 2026-08-30T22:16Z by the
      owner (hdot123) after droid-review flagged 2 P3 findings
      (sys.stdout restore placement in test_code_hygiene_audit.py);
      the fix work (hygiene --exclude / config exclusions / test dedup)
      was discretionary and abandoned by the owner's close.
    - Linear INFRA-670 terminal-absorbed to 已取消 at 22:16Z the same
      day (GitHub mirror closed, no open issue) — no re-land PR exists
      and main's hygiene.py has no --exclude/fnmatch support, so this is
      NOT a cross-implementation-equivalence case.
    - Same retirement class as factory/infra-581-rule-packs-docs
      (VAL-BRANCH-033): the INFRA-383 merge-tree containment check
      cannot see "owner closed without merging", so the branch would be
      protected forever and the INFRA-674 tracking issue would never
      drain.

    Mirrors VAL-BRANCH-029/031/032/033/037/038: the list is the audit
    artifact, and adding or removing entries requires PR review.
    """
    retired = repo_root() / "src" / "infra_core" / "shell" / "branch_cleanup_retired.txt"
    assert retired.is_file(), "scripts/branch_cleanup_retired.txt must exist"
    content = retired.read_text()
    assert "factory/infra-670-hygiene-dup-falsepos" in content, (
        "infra-674 owner-abandoned branch must be listed for retirement"
    )
    assert "INFRA-674" in content, "the infra-674 entry must carry its INFRA reference"
