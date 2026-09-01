#!/usr/bin/env bash
# Zero-red check-runs aggregator for ci-ok gate
# User mandate (2026-08-28): "写死不允许红色合并，一个都不允许"
#
# Scans all completed check-runs for a commit and fails if any has a conclusion
# other than success/skipped/neutral. This catches advisory jobs with
# continue-on-error that would otherwise pass through.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <repository> <commit_sha>"
  echo "  repository: GitHub repository in owner/repo format"
  echo "  commit_sha: The commit SHA to check"
  exit 1
fi

REPOSITORY="$1"
COMMIT_SHA="$2"

echo "Scanning all check-runs for commit: $COMMIT_SHA"

# Fetch all check-runs (handle pagination)
ALL_CHECKS=$(gh api "repos/${REPOSITORY}/commits/${COMMIT_SHA}/check-runs" \
  --paginate \
  --jq '.check_runs[] | select(.status == "completed") | "\(.name)\t\(.conclusion)"')

echo "All completed check-runs:"
echo "$ALL_CHECKS"
echo ""

# Check for any non-success conclusions
RED_CHECKS=$(echo "$ALL_CHECKS" | grep -vE $'\t(success|skipped|neutral)$' || true)

if [[ -n "$RED_CHECKS" ]]; then
  echo "❌ RED CHECKS DETECTED (zero-red policy violation):"
  echo "$RED_CHECKS"
  echo ""
  echo "User mandate: 写死不允许红色合并，一个都不允许"
  echo "All checks (including advisory) must be green/skipped/neutral."
  exit 1
fi

echo "✅ Zero-red verification passed: all check-runs are success/skipped/neutral"
