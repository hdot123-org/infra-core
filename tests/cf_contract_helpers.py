"""Shared contract helpers for the CF Worker pytest entry points.

cf/webhook-gateway (test_cf_worker_contract.py) and cf/gh-proxy
(test_gh_proxy_contract.py) both assert the same wrangler.toml artifact
contract shape. The shared assertion lives here so each entry point stays
a thin wrapper instead of a near-identical block (INFRA-743).
"""

from __future__ import annotations

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
