#!/usr/bin/env bash
# audit_telemetry_coverage.sh — Audit telemetry instrumentation in engine modules
#
# Checks key engine modules (scanner/heartbeat/adapters) for telemetry imports.
# Always exits 0 (advisory only, non-blocking).
#
# Usage: bash scripts/audit_telemetry_coverage.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
ENGINE_DIR="${REPO_ROOT}/src/infra_core/engine"

# Key engine modules to check for telemetry instrumentation
ENGINE_MODULES=(
    "evolution_scanner.py"
    "evolution_heartbeat.py"
    "evolution_adapters.py"
    "evolution_utils.py"
    "version_sync.py"
)

total=0
covered=0
uncovered_files=()

echo "========================================"
echo "  Telemetry Coverage Audit Report"
echo "========================================"
echo ""
echo "Engine directory: ${ENGINE_DIR}"
echo ""

for f in "${ENGINE_MODULES[@]}"; do
    filepath="${ENGINE_DIR}/${f}"
    total=$((total + 1))

    if [[ ! -f "$filepath" ]]; then
        echo "  [SKIP] ${f} — file not found"
        total=$((total - 1))
        continue
    fi

    # Check for telemetry import or instrumentation
    if grep -qE "(telemetry|otel|opentelemetry|tracing)" "$filepath" 2>/dev/null; then
        covered=$((covered + 1))
        echo "  [OK]   ${f} — telemetry instrumented"
    else
        uncovered_files+=("$f")
        echo "  [MISS] ${f} — no telemetry instrumentation"
    fi
done

echo ""
echo "----------------------------------------"
if [[ $total -gt 0 ]]; then
    pct=$(( (covered * 100) / total ))
else
    pct=0
fi
echo "Coverage: ${covered}/${total} (${pct}%)"
echo "----------------------------------------"

if [[ ${#uncovered_files[@]} -gt 0 ]]; then
    echo ""
    if [[ $covered -eq 0 ]]; then
        echo "Status: telemetry not yet instrumented"
        echo ""
        echo "Note: Telemetry infrastructure is planned for M6 harden phase."
        echo "This audit is a structural placeholder and will become active"
        echo "once telemetry instrumentation is implemented."
    else
        echo "Uncovered files:"
        for f in "${uncovered_files[@]}"; do
            echo "  - ${f}"
        done
        echo ""
        echo "Suggestion: Add telemetry imports to achieve full coverage."
        echo "Example:"
        echo '  try:'
        echo '      from infra_core.telemetry import tracer'
        echo '  except ImportError:'
        echo '      tracer = None'
    fi
fi

echo ""
echo "========================================"
echo "  Audit complete (advisory, non-blocking)"
echo "========================================"

# Always exit 0: advisory only
exit 0
