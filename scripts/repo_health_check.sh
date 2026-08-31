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

# ─── Check 1b: uv.lock root package version alignment (INFRA-712) ───
# release-please 的 Release PR 只 bump pyproject.toml 不 relock（PR #136 实证：
# 仅改 manifest/CHANGELOG/pyproject/__init__，uv.lock 根包版本原地踏步），0.7.2
# 漂移即由此而来（PR #163 补救）。本检查把 uv.lock 根包版本纳入交付一致性，
# 漂移在 lint-bundle 即红，不再等到运行时依赖解析失败。
# 解析用 tomllib（uv.lock 是 TOML），根包条目按 pyproject [project].name 匹配，
# 不硬编码包名（重命名包时检查自动跟随）。
echo ""
echo "=== uv.lock root package version ==="

if [[ -f "uv.lock" ]]; then
    # set -e 下命令替换失败会直接退出，用 if ! 包裹转入错误分支
    if ! UVLOCK_STATUS=$(python3 -c "
import json, sys, tomllib

with open('pyproject.toml', 'rb') as f:
    project = tomllib.load(f)['project']
pkg_name = project['name']

with open('uv.lock', 'rb') as f:
    lock = tomllib.load(f)

root = next((p for p in lock.get('package', []) if p.get('name') == pkg_name), None)
if root is None:
    print(json.dumps({'error': f'root package {pkg_name!r} not found in uv.lock'}))
    sys.exit(1)

print(json.dumps({'name': pkg_name, 'version': root['version']}))
"); then
        echo "✗ Failed to parse uv.lock root package: $UVLOCK_STATUS"
        ERRORS=$((ERRORS + 1))
    else
        UVLOCK_VERSION=$(echo "$UVLOCK_STATUS" | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])")

        if [[ "$PYPROJECT_VERSION" == "$UVLOCK_VERSION" ]]; then
            echo "✓ Versions aligned (root package = $UVLOCK_VERSION)"
        else
            echo "✗ Version mismatch: pyproject=$PYPROJECT_VERSION uv.lock root=$UVLOCK_VERSION"
            echo "  Run 'uv lock' to relock, then commit uv.lock together with pyproject.toml"
            ERRORS=$((ERRORS + 1))
        fi
    fi
else
    echo "⚠ uv.lock not found (skipped; repos without a lockfile are out of scope)"
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
