"""Fork guard contract tests for droid-review chains.

Locks the fail-closed identity check added to both droid-review workflow files:
- droid-review-shards.yml (reusable, setup job "Resolve PR context")
- droid-review.yml (self-hosted inline implementation, setup "Resolve PR context")

Guard semantics (truth table):
- pull_request_target + head.repo == github.repository → ALLOW
- pull_request_target + head.repo != github.repository → DENY (exit 1)
- pull_request_target + head.repo empty/missing → DENY (fail-closed)
- push / workflow_dispatch / other events → ALLOW (guard not triggered)

Note: YAML `on:` key is parsed as True by PyYAML (YAML 1.1 spec), so we use
doc.get(True) fallback when accessing trigger configuration.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARDS_WORKFLOW = REPO_ROOT / ".github/workflows/droid-review-shards.yml"
SELF_WORKFLOW = REPO_ROOT / ".github/workflows/droid-review.yml"


@pytest.fixture(scope="module")
def shards_workflow_data() -> dict:
    return yaml.safe_load(SHARDS_WORKFLOW.read_text())


@pytest.fixture(scope="module")
def self_workflow_data() -> dict:
    return yaml.safe_load(SELF_WORKFLOW.read_text())


class TestGuardPresence:
    """Guard code must be present in both workflow files."""

    def test_shards_setup_contains_guard(self, shards_workflow_data):
        """droid-review-shards.yml setup job must contain fork guard."""
        setup_job = shards_workflow_data["jobs"]["setup"]
        resolve_step = next(
            (s for s in setup_job["steps"] if s.get("id") == "resolve"), None
        )
        assert resolve_step is not None, "setup job must have 'resolve' step"
        run_block = resolve_step["run"]

        # Guard must check head.repo.full_name against github.repository
        assert "github.event.pull_request.head.repo.full_name" in run_block
        assert "github.repository" in run_block
        # Guard must exit 1 on mismatch
        assert "exit 1" in run_block
        # Guard must emit error message
        assert "::error::" in run_block

    def test_self_workflow_setup_contains_guard(self, self_workflow_data):
        """droid-review.yml setup job must contain fork guard."""
        setup_job = self_workflow_data["jobs"]["setup"]
        resolve_step = next(
            (s for s in setup_job["steps"] if s.get("id") == "resolve"), None
        )
        assert resolve_step is not None, "setup job must have 'resolve' step"
        run_block = resolve_step["run"]

        # Guard must check head.repo.full_name against github.repository
        assert "github.event.pull_request.head.repo.full_name" in run_block
        assert "github.repository" in run_block
        # Guard must exit 1 on mismatch
        assert "exit 1" in run_block
        # Guard must emit error message
        assert "::error::" in run_block


class TestGuardTruthTable:
    """Guard logic truth table (mirrored implementation for testability).

    Since the guard is inline bash in YAML, we mirror the logic in Python
    for testability. The YAML presence is locked by TestGuardPresence.
    """

    @staticmethod
    def evaluate_guard(
        event_name: str,
        head_repo_full_name: str,
        github_repository: str = "hdot123-org/infra-core",
    ) -> bool:
        """Mirror the bash guard logic.

        Returns True if request should proceed, False if rejected.

        Guard logic (from workflow):
        if event_name == "pull_request_target" AND
           head_repo_full_name != github.repository:
            reject (exit 1)
        """
        if event_name == "pull_request_target":
            # Fail-closed: if head.repo is empty/missing, it won't equal
            # github.repository, so the check naturally rejects
            if head_repo_full_name != github_repository:
                return False  # REJECT
        # All other events pass through
        return True  # ALLOW

    def test_same_repo_pr_target_allowed(self):
        """Same-repo pull_request_target should pass the guard."""
        result = self.evaluate_guard(
            event_name="pull_request_target",
            head_repo_full_name="hdot123-org/infra-core",
            github_repository="hdot123-org/infra-core",
        )
        assert result is True, "Same-repo PR should be allowed"

    def test_fork_pr_target_denied(self):
        """Fork pull_request_target should be rejected by the guard."""
        result = self.evaluate_guard(
            event_name="pull_request_target",
            head_repo_full_name="attacker/malicious-fork",
            github_repository="hdot123-org/infra-core",
        )
        assert result is False, "Fork PR should be denied"

    def test_empty_head_repo_denied(self):
        """Empty/missing head.repo should be rejected (fail-closed)."""
        result = self.evaluate_guard(
            event_name="pull_request_target",
            head_repo_full_name="",  # Empty string
            github_repository="hdot123-org/infra-core",
        )
        assert result is False, "Empty head.repo should be denied (fail-closed)"

    def test_push_allowed(self):
        """Push events should not be affected by the guard."""
        result = self.evaluate_guard(
            event_name="push",
            head_repo_full_name="any/repo",
            github_repository="hdot123-org/infra-core",
        )
        assert result is True, "Push events should pass through"

    def test_dispatch_allowed(self):
        """workflow_dispatch events should not be affected by the guard."""
        result = self.evaluate_guard(
            event_name="workflow_dispatch",
            head_repo_full_name="any/repo",
            github_repository="hdot123-org/infra-core",
        )
        assert result is True, "workflow_dispatch events should pass through"


class TestYamlParsingTrap:
    """YAML `on:` key is parsed as True by PyYAML (YAML 1.1 spec).

    This test documents the trap and verifies we handle it correctly.
    """

    def test_on_key_parsed_as_true(self, shards_workflow_data):
        """Verify that the `on:` trigger key is accessible via True."""
        # PyYAML parses `on:` as True (boolean), not "on" (string)
        # We must use doc.get(True) or doc.get("on", doc.get(True))
        triggers = shards_workflow_data.get(True, {})
        assert triggers is not None, "Triggers must be accessible via True key"
        # The shards workflow uses workflow_call
        assert "workflow_call" in triggers

    def test_self_workflow_on_key_parsed_as_true(self, self_workflow_data):
        """Verify that droid-review.yml `on:` key is accessible via True."""
        triggers = self_workflow_data.get(True, {})
        assert triggers is not None, "Triggers must be accessible via True key"
        # The self workflow uses pull_request_target and workflow_dispatch
        assert "pull_request_target" in triggers
        assert "workflow_dispatch" in triggers
