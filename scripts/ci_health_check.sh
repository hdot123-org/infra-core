#!/usr/bin/env bash
# CI health check: validates infra-core structural integrity
# Three checks: (1) gateway/key module import smoke, (2) ci.yml structure, (3) guard script existence
#
# Usage: bash scripts/ci_health_check.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

ERRORS=0

# ─── Check 1: Gateway/key module import smoke ───
echo "=== Gateway/key module import smoke ==="

# In CI, the package is installed via setup-venv. Locally, we might need to add src to PYTHONPATH.
# Try importing with the package as-is, and if that fails, try with src in PYTHONPATH.
python3 -c "
import sys
from pathlib import Path

# Try importing directly first (works in CI where package is installed)
modules = [
    'infra_core.engine.evolution_scanner',
    'infra_core.engine.evolution_utils',
    'infra_core.engine.evolution_adapters',
    'infra_core.engine.evolution_heartbeat',
    'infra_core.engine.version_sync',
    'infra_core.packs.memory',
]

failed = []
for mod in modules:
    try:
        __import__(mod)
        print(f'✓ {mod}')
    except ImportError as e:
        failed.append((mod, str(e)))

# If all imports failed, try adding src to PYTHONPATH (for local testing)
if len(failed) == len(modules):
    src_path = str(Path('src').resolve())
    sys.path.insert(0, src_path)
    print(f'Retrying with src/ in PYTHONPATH...')
    failed = []
    for mod in modules:
        try:
            __import__(mod)
            print(f'✓ {mod}')
        except Exception as e:
            print(f'✗ {mod}: {e}')
            failed.append(mod)

if failed:
    sys.exit(1)
" || { echo "✗ Module import check failed"; ERRORS=$((ERRORS + 1)); }

if [[ "$ERRORS" -eq 0 ]]; then
    echo "✓ All key modules importable"
fi

# ─── Check 2: ci.yml self-structure validation ───
echo ""
echo "=== CI config integrity check ==="

CI_FILE=".github/workflows/ci.yml"

# 2a. Check ci.yml is non-empty
if [[ ! -s "$CI_FILE" ]]; then
    echo "✗ $CI_FILE is empty or missing"
    ERRORS=$((ERRORS + 1))
else
    echo "✓ $CI_FILE is non-empty"
fi

# 2b. Validate YAML syntax
if [[ "$ERRORS" -eq 0 ]]; then
    if ! python3 -c "
import yaml
with open('$CI_FILE', 'r') as f:
    data = yaml.safe_load(f)
if data is None:
    print('YAML parsed as empty/null')
    exit(1)
if 'jobs' not in data:
    print('Missing required top-level key: jobs')
    exit(1)
" 2>/dev/null; then
        echo "✗ YAML syntax validation failed"
        ERRORS=$((ERRORS + 1))
    else
        echo "✓ YAML syntax is valid"
    fi
fi

# 2c. Verify core required jobs exist
if [[ "$ERRORS" -eq 0 ]]; then
    REQUIRED_JOBS=("pytest" "ruff" "actionlint" "mypy" "ci-ok")
    MISSING_JOBS=""
    for job in "${REQUIRED_JOBS[@]}"; do
        if ! python3 -c "
import yaml
with open('$CI_FILE', 'r') as f:
    data = yaml.safe_load(f)
jobs = data.get('jobs', {})
import sys
sys.exit(0 if '$job' in jobs else 1)
" 2>/dev/null; then
            if [[ -z "$MISSING_JOBS" ]]; then
                MISSING_JOBS="$job"
            else
                MISSING_JOBS="$MISSING_JOBS, $job"
            fi
        fi
    done

    if [[ -n "$MISSING_JOBS" ]]; then
        echo "✗ Missing required jobs: $MISSING_JOBS"
        ERRORS=$((ERRORS + 1))
    else
        echo "✓ Required jobs (pytest, ruff, actionlint, mypy, ci-ok) present"
    fi
fi

# ─── Check 3: Guard script 4-piece existence ───
echo ""
echo "=== Guard script existence check ==="

GUARD_SCRIPTS=(
    "scripts/check_boundary.py"
    "scripts/check_doc_classification.py"
    "scripts/check_fix_has_test.py"
    "scripts/check_pr_ref_consistency.py"
)

for script in "${GUARD_SCRIPTS[@]}"; do
    if [[ -f "$script" ]]; then
        echo "✓ $script exists"
    else
        echo "✗ $script missing"
        ERRORS=$((ERRORS + 1))
    fi
done

# ─── Summary ───
echo ""
if [[ "$ERRORS" -gt 0 ]]; then
    echo "✗ CI health check FAILED ($ERRORS error(s))"
    exit 1
fi

echo "✓ CI health check OK"
