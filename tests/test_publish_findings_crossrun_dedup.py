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


def _mock_gh_paginated_comments(comments: list[dict], max_per_page: int = 30) -> MagicMock:
    """Mock subprocess.run to return paginated comments (multiple JSON arrays).

    gh api --paginate outputs one JSON array per line for list endpoints.
    """
    mock = MagicMock()
    pages = []
    for i in range(0, len(comments), max_per_page):
        page = comments[i : i + max_per_page]
        pages.append(json.dumps(page))
    mock.stdout = "\n".join(pages).encode()
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

    def test_finds_marker_in_paginated_comments_page2(self):
        """Marker comment on page 2 of paginated results → still found.

        Regression test for pagination truncation: gh api without --paginate
        only returns first 30 comments. With --paginate, all pages are fetched
        and the parser must correctly aggregate across pages.
        """
        # Create 35 comments: marker is #32 (on page 2 with page_size=30)
        comments = [{"id": i, "body": f"Regular comment #{i}"} for i in range(1, 32)]
        comments.append(
            {"id": 999, "body": f"{SUMMARY_MARKER}\n## Droid Auto Review — Findings Summary"}
        )
        # Add more comments after the marker
        comments.extend([{"id": i, "body": f"More comments #{i}"} for i in range(33, 36)])

        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result == 999

    def test_handles_single_page_response(self):
        """Single page (≤30 comments) → works like before."""
        comments = [
            {"id": 42, "body": f"{SUMMARY_MARKER}\n## Summary"},
        ]
        # Single page: one JSON array
        mock = MagicMock()
        mock.stdout = json.dumps(comments).encode()
        with patch("subprocess.run", return_value=mock):
            result = find_existing_summary_comment(pr_number=1, repository="o/r")
        assert result == 42

    def test_handles_empty_pages(self):
        """No comments → returns None even with pagination."""
        with patch("subprocess.run", return_value=_mock_gh_paginated_comments([], max_per_page=30)):
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


# ══════════════════════════════════════════════════════════════════════
# Part E: Pagination boundary conditions for find_existing_inline_comments
# ══════════════════════════════════════════════════════════════════════


class TestInlineCommentsPagination:
    """find_existing_inline_comments must handle pagination correctly."""

    def test_paginated_inline_comments_across_pages(self):
        """Inline comments spanning 2 pages → all (path, line) tuples collected."""
        # 35 comments: target at position 32 (page 2 with page_size=30)
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i * 10, "body": f"comment {i}"}
            for i in range(1, 36)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        # All 35 comments should be found
        assert len(result) == 35
        assert ("file1.py", 10) in result
        assert ("file32.py", 320) in result  # was on page 2
        assert ("file35.py", 350) in result

    def test_zero_comments(self):
        """0 comments → empty set."""
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments([], max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert result == set()

    def test_one_comment(self):
        """1 comment → single (path, line) tuple."""
        comments = [{"id": 1, "path": "a.py", "line": 10, "body": "only one"}]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert result == {("a.py", 10)}

    def test_exactly_29_comments(self):
        """29 comments (just under page boundary) → all in single page."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 30)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 29

    def test_exactly_30_comments(self):
        """30 comments (exactly one page) → single page response."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 31)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 30

    def test_exactly_31_comments(self):
        """31 comments (just over page boundary) → 2 pages."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 32)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 31
        # The 31st comment should be present (was on page 2)
        assert ("file31.py", 31) in result

    def test_50_comments(self):
        """50 comments → spans 2 pages with page_size=30."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 51)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 50
        assert ("file50.py", 50) in result

    def test_100_comments(self):
        """100 comments → spans 4 pages with page_size=30."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 101)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 100
        assert ("file100.py", 100) in result

    def test_extreme_pagination_per_page_1(self):
        """max_per_page=1 → each comment is its own page (extreme stress test)."""
        comments = [
            {"id": i, "path": f"file{i}.py", "line": i, "body": f"c{i}"} for i in range(1, 6)
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=1),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert len(result) == 5
        assert ("file1.py", 1) in result
        assert ("file5.py", 5) in result

    def test_pagination_fail_open_on_api_error(self):
        """gh api failure during pagination → empty set (fail-open for dedup)."""
        error = subprocess.CalledProcessError(1, "gh")
        error.stderr = b"rate limit exceeded"
        with patch("subprocess.run", side_effect=error):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        assert result == set()

    def test_pagination_handles_missing_path_or_line(self):
        """Comments missing path or line → skipped gracefully."""
        comments = [
            {"id": 1, "path": "a.py", "line": 10, "body": "ok"},
            {"id": 2, "path": "b.py", "body": "missing line"},  # no line
            {"id": 3, "line": 30, "body": "missing path"},  # no path
            {"id": 4, "path": "d.py", "line": 40, "body": "ok"},
        ]
        with patch(
            "subprocess.run",
            return_value=_mock_gh_paginated_comments(comments, max_per_page=30),
        ):
            result = find_existing_inline_comments(pr_number=1, repository="o/r")
        # Only comments with both path and line should be included
        assert len(result) == 2
        assert ("a.py", 10) in result
        assert ("d.py", 40) in result


# ══════════════════════════════════════════════════════════════════════
# Part F: _parse_paginated_json edge cases
# ══════════════════════════════════════════════════════════════════════


class TestParsePaginatedJson:
    """_parse_paginated_json must handle various input formats."""

    def test_single_json_array(self):
        """Single JSON array → parsed correctly."""
        from droid_review.publish_findings import _parse_paginated_json

        output = '[{"id": 1}, {"id": 2}]'
        result = _parse_paginated_json(output)
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_multiple_json_arrays(self):
        """Multiple JSON arrays (one per line) → concatenated."""
        from droid_review.publish_findings import _parse_paginated_json

        output = '[{"id": 1}, {"id": 2}]\n[{"id": 3}]\n[{"id": 4}, {"id": 5}]'
        result = _parse_paginated_json(output)
        assert len(result) == 5

    def test_empty_string(self):
        """Empty string → empty list."""
        from droid_review.publish_findings import _parse_paginated_json

        result = _parse_paginated_json("")
        assert result == []

    def test_empty_json_array(self):
        """Empty JSON array → empty list."""
        from droid_review.publish_findings import _parse_paginated_json

        result = _parse_paginated_json("[]")
        assert result == []

    def test_blank_lines_between_arrays(self):
        """Blank lines between arrays → handled gracefully."""
        from droid_review.publish_findings import _parse_paginated_json

        output = '[{"id": 1}]\n\n\n[{"id": 2}]\n'
        result = _parse_paginated_json(output)
        assert len(result) == 2

    def test_single_dict_response(self):
        """Single dict (not array) → wrapped in list."""
        from droid_review.publish_findings import _parse_paginated_json

        output = '{"id": 1, "body": "test"}'
        result = _parse_paginated_json(output)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_malformed_json_lines_skipped(self):
        """Malformed JSON lines → skipped, valid ones parsed."""
        from droid_review.publish_findings import _parse_paginated_json

        output = '[{"id": 1}]\nnot valid json\n[{"id": 2}]'
        result = _parse_paginated_json(output)
        assert len(result) == 2
