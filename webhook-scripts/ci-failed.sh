#!/usr/bin/env bash
# shellcheck disable=SC2034
# CI failed webhook handler
# In production, this script is routed via hooks.json (line 216) when ISSUE_ID is not set.
# The Linear issue reference is parameterized via ISSUE_ID env var; when unset, it falls back
# to legacy hardcoded INFRA-5. UseISSUE_ID when calling to avoid the legacy fallback.
# For CI failures, the primary route should be through the main droid-task pipeline via Linear gateway.
set -uo pipefail

LOG_DIR="/Users/busiji/.factory/webhook/logs"
LOG_FILE="$LOG_DIR/ci-failed-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG_FILE"
}

# === PostHog 事件上报 (lib/posthog.sh 统一实现) ===
POSTHOG_EVENT_NAME="ci_failed_mcp_failure"
POSTHOG_DISTINCT_ID="ci-webhook"
# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/posthog.sh"

log "CI failed hook triggered: pipeline=$CI_PIPELINE_ID project=$CI_PROJECT branch=$CI_BRANCH sha=$CI_SHA"

# Write comment to Linear issue about CI failure (triggers Droid via Linear webhook)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/op-mcp.sh"
LINEAR_API_KEY=$(op_get_field "$OP_VAULT_SEVER" "uxsq45aoumghdysj3r5fe2fvqm" "凭据" || true)

if [ -z "$LINEAR_API_KEY" ]; then
    log "ERROR: Linear API key not found"
    send_posthog_event "mcp_key_retrieval_failed" "${CI_PIPELINE_ID:-unknown}" "auth" "MCP: op_get_field returned empty"
    exit 1
fi

# Get issue ID from Linear - parameterized via environment variable, with legacy fallback
# IN Momentum: Use ISSUE_ID env var from caller; otherwise use legacy hardcoded fallback
ISSUE_ID="${ISSUE_ID:-}"
if [ -z "$ISSUE_ID" ]; then
    # Legacy fallback for backward compatibility (legacy event: memory-core MR #41)
    ISSUE_ID="f023acdf-71d9-4121-8edf-a9ed8c7c05f7"
    log "WARNING: ISSUE_ID not provided, using legacy fallback (INFRA-5)"
fi

log "Using Linear issue ID: $ISSUE_ID"

# Write comment to Linear (this triggers the Linear webhook -> trigger-droid.sh -> Droid)
# Note: COMMENT_BODY is intentionally left generic; callers should provide via env var
COMMENT_BODY="${COMMENT_BODY:-CI 流水线失败，请修复。Pipeline: $CI_PIPELINE_ID, Branch: $CI_BRANCH}"

curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"mutation { commentCreate(input: { issueId: \\\"$ISSUE_ID\\\", body: \\\"$COMMENT_BODY\\\" }) { success } }\"}" >> "$LOG_FILE" 2>&1

log "Comment posted to Linear issue via webhook"

log "CI failed hook completed"
