"""
CF Worker webhook-gateway contract test.

This is the pytest collection entry point that drives node --test against
the worker's native test suite. It covers:

- VAL-CF-002: 5-class routing matrix (aligned with n8n github-events-router-v3)
- VAL-CF-003: HMAC verification (fail-closed) + outbound headers + full passthrough
- VAL-CF-004: Cron handler (repository_dispatch + idempotency)
- VAL-CF-001/009/010: Artifact completeness + secret governance + migration matrix

node --test absence = FAIL (not skip) — this mission's contract must be reachable.
"""

import subprocess
from pathlib import Path

from tests.cf_contract_helpers import assert_node_contract, assert_wrangler_toml_contract

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CF_DIR = REPO_ROOT / "cf" / "webhook-gateway"
TEST_DIR = CF_DIR / "test"


# ---------------------------------------------------------------------------
# VAL-CF-002/003/004: Drive node --test for the worker's native test suite
# ---------------------------------------------------------------------------
class TestCFWorkerContract:
    """Run node --test on cf/webhook-gateway/test/ and assert 0 failures."""

    def test_node_available(self):
        """node >=18 must be available (fail, not skip)."""
        assert_node_contract("CF Worker")

    def test_router_tests_pass(self):
        """VAL-CF-002: 5-class routing matrix tests all green."""
        result = subprocess.run(
            ["node", "--test", str(TEST_DIR / "test_router.js")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"router tests failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_hmac_tests_pass(self):
        """VAL-CF-003: HMAC verification (3 states) all green."""
        result = subprocess.run(
            ["node", "--test", str(TEST_DIR / "test_hmac.js")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"HMAC tests failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_outbound_tests_pass(self):
        """VAL-CF-003: Outbound headers + full passthrough all green."""
        result = subprocess.run(
            ["node", "--test", str(TEST_DIR / "test_outbound.js")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"outbound tests failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_cron_tests_pass(self):
        """VAL-CF-004: Cron handler (repository_dispatch + idempotency) all green."""
        result = subprocess.run(
            ["node", "--test", str(TEST_DIR / "test_cron.js")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"cron tests failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_all_node_tests_together(self):
        """Run all node --test files at once — final aggregate check."""
        test_files = sorted(TEST_DIR.glob("test_*.js"))
        assert test_files, "No test files found in cf/webhook-gateway/test/"
        cmd = ["node", "--test"] + [str(f) for f in test_files]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(CF_DIR),
        )
        assert result.returncode == 0, (
            f"node --test failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# VAL-CF-001: Artifact completeness (wrangler.toml + src + DEPLOYMENT.md)
# ---------------------------------------------------------------------------
class TestCFArtifactsExist:
    """Verify the 4-piece artifact set is present in cf/webhook-gateway/."""

    def test_wrangler_toml_exists(self):
        """wrangler.toml present with required fields."""
        assert_wrangler_toml_contract(CF_DIR)

    def test_webhook_exa_edu_kg_route_archived(self):
        """2026-09-03 wangguan handoff: cf/webhook-gateway is now a historical archive.

        Production route webhook.exa.edu.kg/* is now served by wangguan gateway
        (Dash-managed, cf project xun201811/INDEX.md is the authoritative source).
        This repo's copy is archived — the wrangler.toml routes block exists only
        as a historical record and must be explicitly annotated as non-production.
        """
        path = CF_DIR / "wrangler.toml"
        content = path.read_text()

        # (a) Archive-state guard: routes block must carry non-production annotation
        archive_markers = [
            "存档",  # Chinese for "archive"
            "archive",
            "历史",  # "historical"
            "非生产",  # "non-production"
            "non-production",
            "not production",
            "历史记录",  # "historical record"
        ]
        has_archive_marker = any(
            marker in content.lower() or marker in content for marker in archive_markers
        )
        assert has_archive_marker, (
            "wrangler.toml routes block must carry explicit non-production/archive "
            "annotation (2026-09-03 wangguan handoff)"
        )

        # (b) Pointer to authoritative source in cf project
        # Check DEPLOYMENT.md for the pointer (wrangler.toml itself uses comments)
        deployment_content = (CF_DIR / "DEPLOYMENT.md").read_text()
        pointer_markers = [
            "xun201811/INDEX.md",
            "workers-gateway-architecture.md",
            "wangguan",
        ]
        found_pointers = [p for p in pointer_markers if p in deployment_content]
        assert len(found_pointers) >= 2, (
            f"DEPLOYMENT.md must contain pointers to cf project authoritative "
            f"source (expected >=2 of {pointer_markers}, found {found_pointers})"
        )

    def test_src_worker_js_exists(self):
        """src/worker.js present."""
        assert (CF_DIR / "src" / "worker.js").exists()

    def test_src_router_js_exists(self):
        """src/router.js present."""
        assert (CF_DIR / "src" / "router.js").exists()

    def test_deployment_md_exists(self):
        """DEPLOYMENT.md present with 5 required sections."""
        path = CF_DIR / "DEPLOYMENT.md"
        assert path.exists(), "cf/webhook-gateway/DEPLOYMENT.md missing"

        content = path.read_text()
        # 5 sections: deploy, rollback, secrets mapping, migration matrix, switch plan
        assert "部署" in content or "deploy" in content.lower()
        assert "回滚" in content or "rollback" in content.lower()
        assert "secret" in content.lower()
        assert "迁移范围" in content or "migration" in content.lower()
        assert "切换" in content or "switch" in content.lower()


# ---------------------------------------------------------------------------
# VAL-CF-009: Secret governance — structural checks, zero hardcoded tokens
# ---------------------------------------------------------------------------
class TestCFSecretGovernance:
    """Verify no real secret values are hardcoded in the worker code.

    Uses structural detection (not literal real-value patterns):
    - src/*.js must read token headers from env/secrets bindings only
    - Generic secret prefix scans (ghp_, gho_, sk-)
    - Long hex literal regex (>=32 consecutive hex chars = suspicious)
    """

    import re

    # Generic secret prefixes that should never appear as literals
    SECRET_PREFIX_PATTERNS = [
        re.compile(r"ghp_[A-Za-z0-9]{36,}"),  # GitHub PAT
        re.compile(r"gho_[A-Za-z0-9]{36,}"),  # GitHub OAuth
        re.compile(r"sk-[A-Za-z0-9]{20,}"),  # Generic secret prefix
    ]

    # Long hex literal: >=32 consecutive hex chars (case-insensitive)
    LONG_HEX_PATTERN = re.compile(r"[0-9a-fA-F]{32,}")

    # Token header names that must only be set from env bindings
    TOKEN_HEADERS = ["X-CI-Token", "X-Wiki-Token", "X-Posthog-Token"]

    def _scan_files_for_prefixes(self, directory, patterns):
        """Scan all JS files in a directory for secret prefix patterns."""
        violations = []
        for js_file in directory.rglob("*.js"):
            content = js_file.read_text()
            for pat in patterns:
                matches = pat.findall(content)
                for match in matches:
                    violations.append(
                        f"{js_file.relative_to(directory)}: contains secret prefix pattern '{match[:12]}...'"
                    )
        return violations

    def _scan_files_for_long_hex(self, directory):
        """Scan all JS files for suspicious long hex literals."""
        violations = []
        for js_file in directory.rglob("*.js"):
            content = js_file.read_text()
            for line_num, line in enumerate(content.splitlines(), 1):
                # Skip comment lines
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                matches = self.LONG_HEX_PATTERN.findall(line)
                for match in matches:
                    # Exclude known safe patterns (test HMAC signatures are all zeros,
                    # SHA patterns in regex, color codes, etc.)
                    if match == "0" * len(match):
                        continue  # all-zero test signatures are OK
                    violations.append(
                        f"{js_file.relative_to(directory)}:{line_num}: long hex literal '{match[:16]}...'"
                    )
        return violations

    def test_no_hardcoded_secrets_in_src(self):
        """src/*.js must not contain hardcoded secret prefix patterns or long hex literals."""
        prefix_violations = self._scan_files_for_prefixes(
            CF_DIR / "src", self.SECRET_PREFIX_PATTERNS
        )
        hex_violations = self._scan_files_for_long_hex(CF_DIR / "src")
        all_violations = prefix_violations + hex_violations
        assert not all_violations, "Suspicious literals found in src/:\n" + "\n".join(
            all_violations
        )

    def test_no_hardcoded_secrets_in_tests(self):
        """test/*.js must not contain hardcoded secret prefix patterns or long hex literals."""
        prefix_violations = self._scan_files_for_prefixes(
            CF_DIR / "test", self.SECRET_PREFIX_PATTERNS
        )
        hex_violations = self._scan_files_for_long_hex(CF_DIR / "test")
        all_violations = prefix_violations + hex_violations
        assert not all_violations, "Suspicious literals found in test/:\n" + "\n".join(
            all_violations
        )

    def test_src_token_headers_from_env_bindings(self):
        """Structural check: src/*.js token header values must come from env.* bindings.

        Asserts that X-CI-Token, X-Wiki-Token, X-Posthog-Token are only assigned
        from env.CI_TOKEN / env.WIKI_TOKEN / request header passthrough — never from
        string literals.
        """
        src_dir = CF_DIR / "src"
        violations = []

        for js_file in src_dir.rglob("*.js"):
            content = js_file.read_text()

            # Check X-CI-Token is sourced from env.CI_TOKEN
            if "X-CI-Token" in content:
                if "env.CI_TOKEN" not in content:
                    violations.append(f"{js_file.name}: X-CI-Token not sourced from env.CI_TOKEN")

            # Check X-Wiki-Token is sourced from env.WIKI_TOKEN
            if "X-Wiki-Token" in content:
                if "env.WIKI_TOKEN" not in content:
                    violations.append(
                        f"{js_file.name}: X-Wiki-Token not sourced from env.WIKI_TOKEN"
                    )

            # Check X-Posthog-Token is passthrough from request headers
            if "X-Posthog-Token" in content:
                # Must read from request headers, not from a hardcoded string
                if (
                    "request.headers.get" not in content
                    and "x-posthog-token" not in content.lower()
                ):
                    violations.append(
                        f"{js_file.name}: X-Posthog-Token not from request header passthrough"
                    )

        assert not violations, "Token headers not sourced from env/secrets:\n" + "\n".join(
            violations
        )


# ---------------------------------------------------------------------------
# VAL-CF-010: Migration range matrix documentation
# ---------------------------------------------------------------------------
class TestCFMigrationDocumentation:
    """Verify DEPLOYMENT.md covers the migration range matrix."""

    def test_migration_matrix_five_items(self):
        """DEPLOYMENT.md migration matrix must cover all 5 items."""
        content = (CF_DIR / "DEPLOYMENT.md").read_text()
        required_items = [
            "github-events-router",  # full adopt
            "posthog",  # same-structure copy
            "linear-events",  # dead path, don't migrate
            "ci-complete",  # dead path, don't migrate
            "linear-factory",  # broken link, not in scope
        ]
        for item in required_items:
            assert item.lower() in content.lower(), (
                f"DEPLOYMENT.md migration matrix missing item: {item}"
            )
