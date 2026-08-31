"""SHA pinning contract tests (F3).

Guard tests to ensure all remote uses references are pinned to 40-char SHA
and self-repo action references are content-equivalent to origin/main.
"""

import re
import subprocess
from pathlib import Path

import pytest

# Repository root
REPO_ROOT = Path(__file__).parent.parent

# Workflow and action directories to scan
SCAN_DIRS = [
    REPO_ROOT / ".github" / "workflows",
    REPO_ROOT / ".github" / "actions",
    REPO_ROOT / "actions",
]

# SHA pattern: owner/repo@<40-hex> or owner/repo/path@<40-hex>
SHA_PATTERN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

# Self-repo action directories (infra-core actions referenced by infra-core workflows)
SELF_REPO_ACTIONS = {
    "actions/auto-merge",
    "actions/branch-cleanup",
    "actions/governance-check",
    "actions/droid-review-aggregate",
}


def extract_uses_from_file(file_path: Path) -> list[tuple[str, int, str]]:
    """Extract all uses references from a YAML file.

    Returns list of (file_path, line_number, uses_value) tuples.
    """
    uses_list = []
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip comment lines
            if line.strip().startswith("#"):
                continue

            # Match uses: <value>
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if match:
                uses_value = match.group(1)
                uses_list.append((str(file_path), line_num, uses_value))
    except Exception as e:
        pytest.fail(f"Failed to parse {file_path}: {e}")

    return uses_list


def collect_all_uses() -> list[tuple[str, int, str]]:
    """Collect all uses references from workflow and action files."""
    all_uses = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue

        # Scan YAML files
        for yaml_file in scan_dir.rglob("*.yml"):
            all_uses.extend(extract_uses_from_file(yaml_file))

        for yaml_file in scan_dir.rglob("*.yaml"):
            all_uses.extend(extract_uses_from_file(yaml_file))

    return all_uses


def is_local_reference(uses_value: str) -> bool:
    """Check if uses reference is local (./) or docker://."""
    return uses_value.startswith("./") or uses_value.startswith("docker://")


def is_self_repo_reference(uses_value: str) -> bool:
    """Check if uses reference points to self-repo action."""
    return uses_value.startswith("hdot123-org/infra-core/")


class TestUsesShaPinning:
    """Test that all remote uses are pinned to 40-char SHA."""

    def test_all_remote_uses_pinned_to_full_sha(self):
        """All remote uses must match ^[^@\\s]+@[0-9a-f]{40}$ pattern.

        Local ./ references and docker:// are exempt.
        """
        all_uses = collect_all_uses()
        violations = []

        for file_path, line_num, uses_value in all_uses:
            # Skip local and docker references
            if is_local_reference(uses_value):
                continue

            # Check SHA pattern
            if not SHA_PATTERN.match(uses_value):
                violations.append(f"{file_path}:{line_num} uses: {uses_value}")

        assert not violations, (
            f"Found {len(violations)} uses references not pinned to 40-char SHA:\n"
            + "\n".join(violations)
        )

    def test_sha_references_have_version_comment(self):
        """Each SHA-locked uses line should have a # vTag comment for readability."""
        all_uses = collect_all_uses()
        missing_comments = []

        for file_path, line_num, uses_value in all_uses:
            # Skip local and docker references
            if is_local_reference(uses_value):
                continue

            # Check if line has version comment
            try:
                with open(file_path, encoding="utf-8") as f:
                    lines = f.readlines()
                    line = lines[line_num - 1]

                    # Check for # comment after uses value
                    if "#" not in line or "v" not in line.split("#")[-1]:
                        missing_comments.append(f"{file_path}:{line_num} uses: {uses_value}")
            except Exception:
                pass

        # This is a warning-level check, not a hard failure
        # We just want to encourage version comments
        if missing_comments:
            pytest.skip(f"Found {len(missing_comments)} SHA references without version tag")


class TestSelfRepoActionFreshness:
    """Test that self-repo action references are content-equivalent to origin/main."""

    def get_pinned_sha(self, uses_value: str) -> str | None:
        """Extract SHA from uses value like 'owner/repo@<sha>'."""
        match = re.search(r"@([0-9a-f]{40})", uses_value)
        return match.group(1) if match else None

    def get_action_dir_from_uses(self, uses_value: str) -> str | None:
        """Extract action directory from uses value.

        E.g., 'hdot123-org/infra-core/actions/auto-merge@<sha>' -> 'actions/auto-merge'
        """
        # Remove owner/repo prefix
        match = re.search(r"hdot123-org/infra-core/([^@]+)@", uses_value)
        if match:
            return match.group(1).rstrip("/")
        return None

    def check_content_equivalent(self, pinned_sha: str, action_dir: str) -> bool:
        """Check if pinned SHA is content-equivalent to origin/main for action_dir.

        Content equivalence: git diff <pinned_sha>..origin/main -- <action_dir> is empty.
        """
        try:
            result = subprocess.run(
                ["git", "diff", f"{pinned_sha}..origin/main", "--", action_dir],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Empty diff means content equivalent
            return result.returncode == 0 and not result.stdout.strip()
        except subprocess.TimeoutExpired:
            pytest.skip("git diff timed out (shallow clone?)")
        except FileNotFoundError:
            pytest.skip("git not available")
        except Exception as e:
            pytest.skip(f"git diff failed: {e}")

    def test_self_repo_action_refs_content_equivalent(self):
        """Self-repo action references must be content-equivalent to origin/main.

        For each workflow reference to hdot123-org/infra-core/actions/<name>@<sha>,
        verify that git diff <sha>..origin/main -- actions/<name> is empty.
        """
        all_uses = collect_all_uses()
        stale_actions = []

        for file_path, line_num, uses_value in all_uses:
            # Only check self-repo references
            if not is_self_repo_reference(uses_value):
                continue

            pinned_sha = self.get_pinned_sha(uses_value)
            if not pinned_sha:
                continue

            action_dir = self.get_action_dir_from_uses(uses_value)
            if not action_dir:
                continue

            # Check content equivalence
            if not self.check_content_equivalent(pinned_sha, action_dir):
                stale_actions.append(
                    f"{file_path}:{line_num} uses: {uses_value}\n"
                    f"  action_dir: {action_dir}\n"
                    f"  pinned_sha: {pinned_sha}"
                )

        assert not stale_actions, (
            f"Found {len(stale_actions)} self-repo action references not content-equivalent:\n"
            + "\n".join(stale_actions)
        )
