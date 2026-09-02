"""Shared pending-ci test file factory (INFRA-735 dedup).

INFRA-735: ``_create_pending_file`` had 92% AST similarity across 2 test files
(test_trigger_ci_droid_routing: 11 lines / 97 tokens;
test_ci_fallback_repo_routing: 10 lines / 84 tokens) — triggering
CODE_HYGIENE_DUPLICATE_BLOCK.

Both variants are folded into a single ``create_pending_file`` factory. Test
modules import it under their original local names (``_create_pending_file``)
so existing call sites stay unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def create_pending_file(
    locks_dir: Path,
    pr_number: int,
    *,
    cwd: str | None = "/test/repo",
    source: str | None = None,
    created_at: str | None = None,
) -> Path:
    """Create a ``pending-ci-{pr_number}.json`` test file and return its path.

    INFRA-735: extracted from the 92%-similar ``_create_pending_file`` bodies
    in test_trigger_ci_droid_routing (cwd always ``/test/repo``，source /
    created_at 可选) and test_ci_fallback_repo_routing（cwd 不传则省略键，
    created_at 恒为当前时间）。

    Args:
        locks_dir: Directory hosting the pending-ci lock files (``LOCK_DIR``).
        pr_number: Pull request number embedded in the filename and payload.
        cwd: Repo path recorded in the file. Defaults to ``/test/repo``
            (routing-file semantics); pass ``None`` to omit the key entirely
            (fallback-routing M5 schema semantics).
        source: Optional source marker (``session`` / ``scanner``).
        created_at: Optional explicit creation timestamp; defaults to now.

    Returns:
        Path to the written pending-ci file.
    """
    data = {
        "pr_number": str(pr_number),
        "created_at": created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if cwd is not None:
        data["cwd"] = cwd
    if source is not None:
        data["source"] = source
    file_path = locks_dir / f"pending-ci-{pr_number}.json"
    file_path.write_text(json.dumps(data))
    return file_path
