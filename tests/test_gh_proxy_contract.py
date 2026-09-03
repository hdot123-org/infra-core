"""
GH-Proxy CF Worker contract test.

Pytest collection entry point that drives `node --test` against the
gh-proxy worker's native test suite. Mirrors test_cf_worker_contract.py.

Covers:
- IP whitelist (CF-Connecting-IP check in worker code)
- PROXY_KEY authentication
- Host whitelist
- PAT injection for hdot123-org private repos (Basic auth form)
- CORS and header stripping

node --test absence = FAIL (not skip) — this mission's contract must be reachable.
"""

import shutil
import subprocess
from pathlib import Path

from tests.cf_contract_helpers import assert_wrangler_toml_contract

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CF_DIR = REPO_ROOT / "cf" / "gh-proxy"
TEST_DIR = CF_DIR / "test"


# ---------------------------------------------------------------------------
# Drive node --test for the worker's native test suite
# ---------------------------------------------------------------------------
class TestGHProxyContract:
    """Run node --test on cf/gh-proxy/test/ and assert 0 failures."""

    def test_node_available(self):
        """node >=18 must be available (fail, not skip)."""
        node = shutil.which("node")
        assert node is not None, "node not found in PATH — required for gh-proxy contract"

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

    def test_worker_tests_pass(self):
        """All gh-proxy worker tests pass."""
        test_file = TEST_DIR / "worker.test.js"
        result = subprocess.run(
            ["node", "--test", str(test_file)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"gh-proxy tests failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Artifact completeness (wrangler.toml + src + DEPLOYMENT.md)
# ---------------------------------------------------------------------------
class TestGHProxyArtifactsExist:
    """Verify the 3-piece artifact set is present in cf/gh-proxy/."""

    def test_wrangler_toml_exists(self):
        """wrangler.toml present with required fields."""
        assert_wrangler_toml_contract(CF_DIR)

    def test_src_worker_js_exists(self):
        """src/worker.js present."""
        assert (CF_DIR / "src" / "worker.js").exists()

    def test_deployment_md_exists(self):
        """DEPLOYMENT.md present with required sections."""
        path = CF_DIR / "DEPLOYMENT.md"
        assert path.exists(), "cf/gh-proxy/DEPLOYMENT.md missing"

        content = path.read_text()
        # Key sections: deployment info, auth mechanism, secrets, troubleshooting
        assert "IP 白名单" in content or "IP whitelist" in content
        assert "PROXY_KEY" in content
        assert "GH_PRIVATE_PAT" in content
        assert "Basic" in content  # PAT injection uses Basic auth
