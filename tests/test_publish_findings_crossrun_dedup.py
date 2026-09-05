"""VAL-DEDUP-001: publish_findings cross-run dedup tests.

When the aggregate job reruns on the same PR, it must not post duplicate
inline or summary comments. The second run should detect existing comments
(via marker retrieval) and skip or update instead of creating new ones.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "infra_core" / "engine"))

from droid_review.publish_findings import (  # noqa: E402
    SUMMARY_MARKER,
    find_existing_inline_comments,
    find_existing_summary_comment,
    post_inline_comment,
    post_summary_comment,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_subprocess_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    """Build a mock subprocess.CompletedProcess-like return value."""
    result = MagicMock()
    result.stdout = stdout.encode()
    result.returncode = returncode
    return result


def _mock_gh_comments(comments: list[dict]) -> MagicMock:
    """Mock subprocess.run to return a list of existing comments as JSON."""
    mock = MagicMock()
    mock.stdout = json.dumps(comments).encode()
    return mock


# ══════════════════════════════════════════════════════════════════════
# Part A: Summary comment marker detection
# ══════════════════════════════════════════════════════════════════════


class TestSummaryMarker:
    """Summary comment must carry a detectable marker for cross-run dedup."""

    def test_summary_marker_constant_defined(self):
        """SUMMARY_MARKER must be a non-empty string."""
        assert isinstance(SUMMARY_MARKER, str)
        assert len(SUMMARY_MARKER) > 0

    def test_summary_body_contains_marker(self):
        """post_summary_comment body must include the SUMMARY_MARKER."""
        findings = [{"severity": "P1", "file": "a.py", "line": 10, "message": "bug", "shard_id": 0}]
        by_shard = {0: findings}

        captured_body = {}

        def capture_subprocess(*args, **kwargs):
            # Capture the input payload to inspect the comment body
            input_data = kwargs.get("input", b"")
            if isinstance(input_data, bytes):
                payload = json.loads(input_data.decode())
            else:
                payload = json.loads(input_data)
            captured_body["body"] = payload.get("body", "")
            mock = MagicMock()
            mock.stdout = b""
            return mock

        with patch("subprocess.run", side_effect=capture_subprocess):
            post_summary_comment(findings, pr_number=1, repository="o/r", by_shard=by_shard)

        assert SUMMARY_MARKER in captured_body["body"]


class TestFindExistingSummaryComment:
    """find_existing_summary_comment must detect existing marker comments."""

    def test_returns_none_when_no_existing_comment(self):
        """No existing comments → returns None."""
        with patch("subprocess.run", return_value=_mock_gh_comments([])):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result is None

    def test_returns_none_when_no_marker_match(self):
        """Existing comments but none with marker → returns None."""
        comments = [{"id": 100, "body": "Some unrelated comment"}]
        with patch("subprocess.run", return_value=_mock_gh_comments(comments)):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result is None

    def test_returns_comment_id_when_marker_found(self):
        """Existing comment with marker → returns its ID."""
        comments = [
            {"id": 42, "body": f"{SUMMARY_MARKER}\n## Droid Auto Review — Findings Summary"},
        ]
        with patch("subprocess.run", return_value=_mock_gh_comments(comments)):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result == 42

    def test_finds_marker_among_multiple_comments(self):
        """Marker comment is the 3rd of 5 comments → still found."""
        comments = [
            {"id": 1, "body": "LGTM"},
            {"id": 2, "body": "Nice work"},
            {"id": 99, "body": f"{SUMMARY_MARKER}\n## Summary"},
            {"id": 4, "body": "Thanks"},
            {"id": 5, "body": "Reviewed"},
        ]
        with patch("subprocess.run", return_value=_mock_gh_comments(comments)):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result == 99

    def test_returns_none_on_api_failure(self):
        """gh api failure → returns None (fail-open for dedup, not fail-closed)."""
        error = subprocess.CalledProcessError(1, "gh")
        error.stderr = b"rate limit exceeded"
        with patch("subprocess.run", side_effect=error):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# Part B: Summary comment skip/update on rerun
# ══════════════════════════════════════════════════════════════════════


class TestSummaryDedup:
    """post_summary_comment must skip or update when marker exists."""

    def test_skips_post_when_existing_comment_found(self):
        """When existing summary found, must NOT call POST to create a new one."""
        findings = [{"severity": "P1", "file": "a.py", "line": 10, "message": "bug", "shard_id": 0}]
        by_shard = {0: findings}

        call_log = []

        def track_subprocess(*args, **kwargs):
            call_list = args[0] if args else kwargs.get("args", [])
            call_log.append(call_list)
            # First call: list existing comments (GET) → return one with marker
            if "GET" in call_list or "--method" not in call_list:
                return _mock_gh_comments([{"id": 42, "body": f"{SUMMARY_MARKER}\n## Summary"}])
            # Subsequent calls: should NOT happen (skip)
            mock = MagicMock()
            mock.stdout = b""
            return mock

        # Mock the find_existing call to return an existing comment ID
        with patch(
            "droid_review.publish_findings.find_existing_summary_comment",
            return_value=42,
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"")
                result = post_summary_comment(
                    findings, pr_number=1, repository="o/r", by_shard=by_shard
                )

        # Should NOT have called subprocess.run for POST (skipped posting)
        assert result is True  # Still "success" — we handled it gracefully
        mock_run.assert_not_called()

    def test_posts_when_no_existing_comment(self):
        """No existing summary → should POST normally."""
        findings = [{"severity": "P1", "file": "a.py", "line": 10, "message": "bug", "shard_id": 0}]
        by_shard = {0: findings}

        with patch(
            "droid_review.publish_findings.find_existing_summary_comment",
            return_value=None,
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"")
                result = post_summary_comment(
                    findings, pr_number=1, repository="o/r", by_shard=by_shard
                )

        assert result is True
        mock_run.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# Part C: Inline comment dedup
# ══════════════════════════════════════════════════════════════════════


class TestFindExistingInlineComments:
    """find_existing_inline_comments must retrieve existing PR review comments."""

    def test_returns_empty_set_when_no_comments(self):
        """No existing review comments → empty set."""
        with patch("subprocess.run", return_value=_mock_gh_comments([])):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert result == set()

    def test_returns_set_of_tuples(self):
        """Existing comments → set of (path, line) tuples."""
        comments = [
            {"id": 1, "path": "a.py", "line": 10, "body": "**[P1]** bug"},
            {"id": 2, "path": "b.py", "line": 20, "body": "**[P2]** other"},
        ]
        with patch("subprocess.run", return_value=_mock_gh_comments(comments)):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert ("a.py", 10) in result
        assert ("b.py", 20) in result
        assert len(result) == 2

    def test_returns_empty_on_api_failure(self):
        """gh api failure → empty set (fail-open for dedup)."""
        error = subprocess.CalledProcessError(1, "gh")
        error.stderr = b"not found"
        with patch("subprocess.run", side_effect=error):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert result == set()


class TestInlineDedup:
    """post_inline_comment must skip when equivalent comment exists."""

    def test_skips_when_same_file_line_exists(self):
        """Existing inline at same (file, line) → skip posting."""
        finding = {"severity": "P1", "file": "a.py", "line": 10, "message": "bug"}

        with patch(
            "droid_review.publish_findings.find_existing_inline_comments",
            return_value={("a.py", 10)},
        ):
            with patch("subprocess.run") as mock_run:
                result = post_inline_comment(
                    finding, pr_number=1, repository="o/r", commit_id="abc"
                )

        assert result is True  # Handled gracefully
        mock_run.assert_not_called()  # Did NOT post

    def test_posts_when_no_existing_at_same_location(self):
        """No existing inline at (file, line) → post normally."""
        finding = {"severity": "P1", "file": "a.py", "line": 10, "message": "bug"}

        with patch(
            "droid_review.publish_findings.find_existing_inline_comments",
            return_value=set(),
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"")
                result = post_inline_comment(
                    finding, pr_number=1, repository="o/r", commit_id="abc"
                )

        assert result is True
        mock_run.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# Part D: Full rerun scenario
# ══════════════════════════════════════════════════════════════════════


class TestFullRerunScenario:
    """End-to-end rerun: second invocation must not duplicate comments."""

    def test_rerun_skips_all_comments(self):
        """Second run: existing summary + inline comments → zero new posts."""
        findings = [{"severity": "P1", "file": "a.py", "line": 10, "message": "bug", "shard_id": 0}]
        by_shard = {0: findings}

        post_calls = []

        def track_posts(*args, **kwargs):
            post_calls.append(args)
            return MagicMock(stdout=b"")

        with (
            patch(
                "droid_review.publish_findings.find_existing_summary_comment",
                return_value=42,
            ),
            patch(
                "droid_review.publish_findings.find_existing_inline_comments",
                return_value={("a.py", 10)},
            ),
            patch("subprocess.run", side_effect=track_posts),
        ):
            # Post inline
            result_inline = post_inline_comment(
                findings[0], pr_number=1, repository="o/r", commit_id="abc"
            )
            # Post summary
            result_summary = post_summary_comment(
                findings, pr_number=1, repository="o/r", by_shard=by_shard
            )

        # Neither should have made API calls (all skipped)
        assert len(post_calls) == 0
        assert result_inline is True
        assert result_summary is True
