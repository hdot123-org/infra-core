"""Tests for webhook-scripts/drift-gate.sh — three-state drift gate.

Architecture §2.1 defines the three states:
  GATE_INVALID  baseline untrustworthy (exit 2)
  IN_SYNC       baseline trustworthy, --check exit 0 (exit 0)
  DRIFT         baseline trustworthy, --check exit 1 (exit 1)

Tests create fixture git repos with:
- A repo webhook-scripts/ + src/infra_core/engine/ + sync-webhook-scripts.sh
- A production directory mirroring managed files
- Various dirty/clean/fetch-lag conditions to trigger each state

VAL-GATE-001: Three-state gate implemented with unit tests passing
VAL-GATE-002: Gate never triggers sync (no sync-webhook-scripts.sh call without --check)
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DRIFT_GATE_PATH = REPO_ROOT / "webhook-scripts" / "drift-gate.sh"
SYNC_SCRIPT_PATH = REPO_ROOT / "webhook-scripts" / "sync-webhook-scripts.sh"


def _run_drift_gate(*args, cwd=None, env_override=None):
    """Run drift-gate.sh with given args, return (exit_code, stdout, stderr)."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        ["bash", str(DRIFT_GATE_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env=env,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def fixture_repo(tmp_path):
    """Create a minimal fixture git repo with repo-side + production-side layout.

    Layout:
      fixture_repo/             — a git repo (the "clone")
        .git/
        webhook-scripts/
          MANIFEST.sh           — declares 2 managed files
          trigger-droid.sh      — managed file
          trigger-ci-droid.sh   — managed file
          sync-webhook-scripts.sh — copied from real repo (for --check)
        src/infra_core/engine/
          extract_anchor.py     — cross-dir source
      fixture_prod/             — the "production" directory
        trigger-droid.sh
        trigger-ci-droid.sh
        extract_anchor.py

    The fixture repo are set up so HEAD == origin/main (using a bare remote).
    """
    # --- bare "remote" to make fetch work ---
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    # --- working clone ---
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", "main"], check=True, capture_output=True
    )

    # webhook-scripts/
    ws = repo / "webhook-scripts"
    ws.mkdir()

    # MANIFEST declares 2 managed files + 1 cross-dir mapping
    (ws / "MANIFEST.sh").write_text(
        textwrap.dedent("""\
        MANAGED_FILES=(
            "trigger-droid.sh"
            "trigger-ci-droid.sh"
        )
        MANAGED_LIB_FILES=()
        CROSS_DIR_MAPPINGS=(
            "src/infra_core/engine/extract_anchor.py:extract_anchor.py"
        )
        ENV_DIFF_LINES=()
    """)
    )

    # Managed scripts (content A)
    (ws / "trigger-droid.sh").write_text("#!/bin/bash\necho 'version-A'\n")
    (ws / "trigger-ci-droid.sh").write_text("#!/bin/bash\necho 'version-A'\n")

    # sync-webhook-scripts.sh: copy real one so --check works in fixture
    # But we need it to work with fixture paths, so use --repo-root / --prod-root
    # Actually the drift-gate.sh will call it with explicit paths.
    import shutil

    shutil.copy2(str(SYNC_SCRIPT_PATH), str(ws / "sync-webhook-scripts.sh"))

    # src/infra_core/engine/
    eng = repo / "src" / "infra_core" / "engine"
    eng.mkdir(parents=True)
    (eng / "extract_anchor.py").write_text("# engine source A\n")

    # Initial commit (set user config — CI runners may lack global defaults)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True
    )

    # Push to bare and set tracking
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True
    )

    # --- production directory (in-sync baseline) ---
    prod = tmp_path / "prod"
    prod.mkdir()
    (prod / "trigger-droid.sh").write_text("#!/bin/bash\necho 'version-A'\n")
    (prod / "trigger-ci-droid.sh").write_text("#!/bin/bash\necho 'version-A'\n")
    (prod / "extract_anchor.py").write_text("# engine source A\n")

    return {
        "repo": repo,
        "prod": prod,
        "bare": bare,
        "tmp_path": tmp_path,
    }


class TestDriftGateExists:
    """Drift gate script must exist and be executable."""

    def test_script_exists(self):
        assert DRIFT_GATE_PATH.is_file(), "webhook-scripts/drift-gate.sh must exist"

    def test_script_is_executable(self):
        assert os.access(DRIFT_GATE_PATH, os.X_OK), "drift-gate.sh must be executable"

    def test_syntax_check(self):
        """bash -n must pass."""
        result = subprocess.run(
            ["bash", "-n", str(DRIFT_GATE_PATH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed: {result.stderr}"


class TestGateInvalid:
    """GATE_INVALID (exit 2): baseline untrustworthy, do not judge drift."""

    def test_not_in_git_repo(self, tmp_path):
        """Running outside a git repo without --repo-root → GATE_INVALID."""
        non_git = tmp_path / "non_git"
        non_git.mkdir()
        rc, out, err = _run_drift_gate(cwd=non_git)
        assert rc == 2, f"expected GATE_INVALID (2), got {rc}"
        assert "GATE_INVALID" in (out + err)

    def test_not_on_main_branch(self, fixture_repo):
        """Being on a feature branch → GATE_INVALID."""
        repo = fixture_repo["repo"]
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feature-x"], check=True, capture_output=True
        )
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(fixture_repo["prod"]),
            cwd=str(repo),
        )
        assert rc == 2
        assert "GATE_INVALID" in (out + err)

    def test_head_behind_origin(self, fixture_repo):
        """HEAD != origin/main (local behind remote) → GATE_INVALID."""
        repo = fixture_repo["repo"]
        bare = fixture_repo["bare"]

        # Push a new commit to bare via a temp clone, making origin/main ahead
        temp = fixture_repo["tmp_path"] / "temp_push"
        subprocess.run(["git", "clone", str(bare), str(temp)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(temp), "checkout", "main"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(temp), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(temp), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        (temp / "marker.txt").write_text("new commit on remote")
        subprocess.run(["git", "-C", str(temp), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(temp), "commit", "-m", "remote commit"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(temp), "push", "origin", "main"], check=True, capture_output=True
        )

        # Now the working repo's HEAD is behind origin/main after fetch
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(fixture_repo["prod"]),
            cwd=str(repo),
        )
        assert rc == 2
        assert "GATE_INVALID" in (out + err)

    def test_dirty_webhook_scripts_tree(self, fixture_repo):
        """Uncommitted changes in webhook-scripts/ → GATE_INVALID."""
        repo = fixture_repo["repo"]
        # Dirty the working tree in webhook-scripts/
        (repo / "webhook-scripts" / "trigger-droid.sh").write_text("#!/bin/bash\necho 'dirty'\n")
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(fixture_repo["prod"]),
            cwd=str(repo),
        )
        assert rc == 2
        assert "GATE_INVALID" in (out + err)

    def test_dirty_engine_tree(self, fixture_repo):
        """Uncommitted changes in src/infra_core/engine/ → GATE_INVALID."""
        repo = fixture_repo["repo"]
        (repo / "src" / "infra_core" / "engine" / "extract_anchor.py").write_text(
            "# dirty engine\n"
        )
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(fixture_repo["prod"]),
            cwd=str(repo),
        )
        assert rc == 2
        assert "GATE_INVALID" in (out + err)


class TestInSync:
    """IN_SYNC (exit 0): baseline trustworthy and --check reports no drift."""

    def test_all_files_match(self, fixture_repo):
        """Repo and production identical → IN_SYNC."""
        repo = fixture_repo["repo"]
        prod = fixture_repo["prod"]
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(prod),
            cwd=str(repo),
        )
        assert rc == 0, f"expected IN_SYNC (0), got {rc}. stdout={out} stderr={err}"
        assert "IN_SYNC" in (out + err)


class TestDrift:
    """DRIFT (exit 1): baseline trustworthy but --check reports drift."""

    def test_production_behind(self, fixture_repo):
        """Production has older version of a file → DRIFT (not IN_SYNC)."""
        repo = fixture_repo["repo"]
        prod = fixture_repo["prod"]
        # Make production different (older content)
        (prod / "trigger-droid.sh").write_text("#!/bin/bash\necho 'version-OLD'\n")
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(prod),
            cwd=str(repo),
        )
        assert rc == 1, f"expected DRIFT (1), got {rc}. stdout={out} stderr={err}"
        assert "DRIFT" in (out + err)

    def test_production_missing_file(self, fixture_repo):
        """Production missing a managed file → DRIFT."""
        repo = fixture_repo["repo"]
        prod = fixture_repo["prod"]
        (prod / "trigger-droid.sh").unlink()
        rc, out, err = _run_drift_gate(
            "--repo-root",
            str(repo),
            "--prod-root",
            str(prod),
            cwd=str(repo),
        )
        assert rc == 1
        assert "DRIFT" in (out + err)


class TestGateNeverTriggersSync:
    """VAL-GATE-002: Gate must NEVER call sync without --check."""

    def test_no_sync_call_in_script(self):
        """The script source must not invoke sync-webhook-scripts.sh without --check."""
        text = DRIFT_GATE_PATH.read_text(encoding="utf-8")
        import re

        for i, line in enumerate(text.splitlines(), 1):
            # Skip comments
            if line.strip().startswith("#"):
                continue
            # Skip variable assignments (SYNC_SCRIPT=...)
            if "=" in line and not line.strip().startswith(("bash", "$", '"$')):
                continue
            # Only check actual invocations: lines starting with bash/exec/source
            # or lines that run $SYNC_SCRIPT as a command (not in [[ ]] tests)
            stripped = line.strip()
            if stripped.startswith(("bash ", "exec ", "source ")):
                if re.search(r"\$SYNC_SCRIPT|sync-webhook-scripts\.sh", line):
                    assert "--check" in line, (
                        f"drift-gate.sh line {i} invokes sync without --check: {line!r}"
                    )
            # Also catch direct invocation like: "$SYNC_SCRIPT" --check
            elif re.search(r'^(bash\s+)?"\$SYNC_SCRIPT"', stripped):
                assert "--check" in line, (
                    f"drift-gate.sh line {i} invokes sync without --check: {line!r}"
                )
