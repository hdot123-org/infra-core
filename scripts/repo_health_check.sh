#!/usr/bin/env bash
# Repo delivery consistency check: version alignment across release artifacts
# Checks: (1) pyproject version, (2) .release-please-manifest.json, (3) latest tag
#
# Usage: bash scripts/repo_health_check.sh [--ci|--full]
#   --ci:   Local-only checks (default)
#   --full: Include gh CLI remote checks
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

MODE="ci"
case "${1:-}" in
    --ci)   MODE="ci" ;;
    --full) MODE="full" ;;
    "")     MODE="ci" ;;
    *)      echo "Usage: $0 [--ci|--full]"; exit 2 ;;
esac

ERRORS=0

echo "=== Repo Delivery Consistency Check (${MODE} mode) ==="
echo ""

# ─── Extract version from pyproject.toml ───
# Note: Using python tomllib instead of grep+sed for reliability.
# (memory-core used grep+sed due to ubuntu python inline parsing issues,
# but infra-core's CI venv is fresh and reliable.)
PYPROJECT_VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
print(data['project']['version'])
")

echo "pyproject.toml version: $PYPROJECT_VERSION"

# ─── Check 1: .release-please-manifest.json alignment ───
echo ""
echo "=== .release-please-manifest.json version ==="

if [[ -f ".release-please-manifest.json" ]]; then
    MANIFEST_VERSION=$(python3 -c "
import json
with open('.release-please-manifest.json', 'r') as f:
    data = json.load(f)
# The manifest uses '.' as the key for the root package
print(data.get('.', data.get('infra-core', 'NOT_FOUND')))
")

    echo "Manifest version: $MANIFEST_VERSION"

    if [[ "$PYPROJECT_VERSION" == "$MANIFEST_VERSION" ]]; then
        echo "✓ Versions aligned"
    else
        echo "✗ Version mismatch: pyproject=$PYPROJECT_VERSION manifest=$MANIFEST_VERSION"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ .release-please-manifest.json not found"
    ERRORS=$((ERRORS + 1))
fi

# ─── Check 2 (FULL only): Latest tag alignment ───
if [[ "$MODE" == "full" ]]; then
    echo ""
    echo "=== Latest git tag alignment ==="

    LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

    if [[ -z "$LATEST_TAG" ]]; then
        echo "⚠ No git tags found (first release pending)"
    else
        # Strip leading 'v' if present
        TAG_VERSION="${LATEST_TAG#v}"
        echo "Latest tag: $LATEST_TAG (version: $TAG_VERSION)"

        if [[ "$PYPROJECT_VERSION" == "$TAG_VERSION" ]]; then
            echo "✓ Tag aligned with pyproject"
        else
            echo "⚠ Tag mismatch: pyproject=$PYPROJECT_VERSION tag=$TAG_VERSION"
            echo "  (This is expected if release-please hasn't run yet)"
        fi
    fi
fi

# ─── Summary ───
echo ""
if [[ "$ERRORS" -gt 0 ]]; then
    echo "✗ Repo consistency check FAILED ($ERRORS error(s))"
    exit 1
fi

echo "✓ Repo consistency check OK"
