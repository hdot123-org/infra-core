"""Shared contract helpers for the CF Worker pytest entry points.

cf/webhook-gateway (test_cf_worker_contract.py) and cf/gh-proxy
(test_gh_proxy_contract.py) both assert the same wrangler.toml artifact
contract shape (INFRA-743) and the same node >=18 availability gate
(INFRA-744). The shared assertions live here so each entry point stays
a thin wrapper instead of a near-identical block.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def assert_wrangler_toml_contract(cf_dir: Path) -> None:
    """Assert the worker's wrangler.toml exists with the required shared fields.

    Covers the fields both CF workers must declare identically: account_id
    (with the expected account), the src/worker.js main entry, and
    compatibility_date.
    """
    rel = cf_dir.relative_to(REPO_ROOT)
    path = cf_dir / "wrangler.toml"
    assert path.exists(), f"{rel}/wrangler.toml missing"

    content = path.read_text()
    assert "account_id" in content
    assert "97d8129421b7b8e445718ff9891be1d9" in content
    assert 'main = "src/worker.js"' in content
    assert "compatibility_date" in content


def assert_node_contract(contract_label: str) -> None:
    """Assert node >= 18 is available (fail, not skip).

    Shared node-availability gate for both CF Worker entry points;
    ``contract_label`` ("CF Worker" / "gh-proxy") carries the only
    per-file difference, the assertion wording. Re-land of the INFRA-728
    dedup (PR #194, owner-closed after droid-review P2): unlike the
    abandoned attempt, ``node --version`` stdout is parsed only after
    asserting ``returncode == 0`` so a broken node shim surfaces as a
    clean assertion failure instead of a confusing ValueError.
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
    assert result.returncode == 0, (
        f"node --version exited {result.returncode} — required for {contract_label} contract"
        f"{': ' + result.stderr.strip() if result.stderr.strip() else ''}"
    )
    version_str = result.stdout.strip().lstrip("v")
    major = int(version_str.split(".")[0])
    assert major >= 18, f"node version {version_str} < 18"
