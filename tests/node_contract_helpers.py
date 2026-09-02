"""Shared node-availability gate for worker contract tests (INFRA-728 dedup).

INFRA-728: ``test_node_available`` had 99% AST similarity across 2 contract
test files (test_gh_proxy_contract.py: 12 lines / 81 tokens;
test_cf_worker_contract.py: 12 lines / 81 tokens) — triggering
CODE_HYGIENE_DUPLICATE_BLOCK.

The node >=18 gate is folded into a single ``require_node`` factory. The only
per-file variance (the assertion-message label) is carried by
``contract_label``.
"""

from __future__ import annotations

import shutil
import subprocess


def require_node(contract_label: str) -> str:
    """Assert node >=18 is available and return the node executable path.

    Fail (not skip) — the worker contract missions must be reachable, so a
    missing or too-old node runtime is a hard failure.

    Args:
        contract_label: Label embedded in the "node not found" assertion
            message (e.g. ``"gh-proxy"``, ``"CF Worker"``).

    Returns:
        Absolute path of the node executable.
    """
    node = shutil.which("node")
    assert node is not None, f"node not found in PATH — required for {contract_label} contract"

    # Verify version >= 18
    result = subprocess.run(
        [node, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    version_str = result.stdout.strip().lstrip("v")
    major = int(version_str.split(".")[0])
    assert major >= 18, f"node version {version_str} < 18"
    return node
