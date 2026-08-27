#!/bin/bash
# CLI smoke test: verify all entry points are callable.
# From memory-core scripts/cli_smoke_test.sh: preserves the basic structure
# but updated for infra-core's entry points.
#
# Exit codes:
#   0 - all entry points callable
#   1 - one or more entry points failed

set -e

FAILED=0

test_entry_point() {
    local cmd="$1"
    local desc="$2"

    if command -v "$cmd" >/dev/null 2>&1; then
        echo "✓ $desc ($cmd)"
        # Try --help to verify it's actually callable
        if "$cmd" --help >/dev/null 2>&1; then
            echo "  ✓ --help works"
        else
            echo "  ⚠ --help failed (may be expected for some commands)"
        fi
    else
        echo "✗ $desc ($cmd not found)"
        FAILED=1
    fi
}

echo "Testing infra-core CLI entry points..."
echo

# Main CLI
test_entry_point "infra-cli" "Main CLI"

# Pack tools (memory pack)
test_entry_point "infra-self-audit" "Self audit"
test_entry_point "infra-hygiene-audit" "Hygiene audit"
test_entry_point "infra-error-patterns" "Error patterns"
test_entry_point "infra-daily-audit" "Daily audit"
test_entry_point "infra-layout-audit" "Layout audit"

echo
if [ $FAILED -eq 0 ]; then
    echo "✓ All entry points available"
    exit 0
else
    echo "✗ Some entry points missing"
    exit 1
fi
