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

# ─── 2026-09-01 用户裁定一次性 bootstrap 豁免 ───────────────────────────
# infra-core 转私有后 GITHUB_TOKEN 缺 actions:read，导致 Auto Merge workflow
# 的 "Auto-merge PR" job 结构性必红（GraphQL statusCheckRollup.workflowRun
# 报 'Resource not accessible by integration'）。本 PR (#176) 修复了 permissions
# 块加 actions:read，但 CI 跑的 Auto Merge workflow 仍是 main 旧码（鸡先有蛋）。
# 豁免 scope：仅忽略 check name 以 "Auto-merge PR" 开头的 check-run。
# 合并后必须立即移除本豁免（小 PR 收尾）。
BOOTSTRAP_EXEMPT_PREFIX="Auto-merge PR"
if [[ -n "$RED_CHECKS" ]]; then
  FILTERED_RED_CHECKS=$(echo "$RED_CHECKS" | grep -v "^${BOOTSTRAP_EXEMPT_PREFIX}" || true)
  if [[ -z "$FILTERED_RED_CHECKS" ]]; then
    echo "⚠️  Bootstrap exemption applied: only '$BOOTSTRAP_EXEMPT_PREFIX' check(s) red."
    echo "   Exempted checks:"
    echo "$RED_CHECKS"
    echo "   (2026-09-01 用户裁定一次性 bootstrap 豁免，合并后必须移除)"
    RED_CHECKS=""
  else
    RED_CHECKS="$FILTERED_RED_CHECKS"
  fi
fi

if [[ -n "$RED_CHECKS" ]]; then
  echo "❌ RED CHECKS DETECTED (zero-red policy violation):"
  echo "$RED_CHECKS"
  echo ""
  echo "User mandate: 写死不允许红色合并，一个都不允许"
  echo "All checks (including advisory) must be green/skipped/neutral."
  exit 1
fi

echo "✅ Zero-red verification passed: all check-runs are success/skipped/neutral"
