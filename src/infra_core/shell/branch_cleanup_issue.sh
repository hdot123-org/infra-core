#!/usr/bin/env bash
# Branch cleanup tracking-issue manager (INFRA-385)
#
# Deduplicates the "Branch cleanup" tracking issues created by the
# branch-cleanup workflow. Before INFRA-385 every scheduled run that ended
# with protected branches opened a NEW issue, so a permanently protected
# branch (e.g. content landed via a different PR and then evolved on main)
# generated one duplicate issue per run (every 5 hours).
#
# Contract:
#   * Zero actionable items  -> auto-close the tracking issue (resolved)
#   * Protected-only run with no open tracker -> CREATE the single reusable
#     tracking issue (INFRA-557): residual protected branches must be visible
#     to humans instead of exiting silently
#   * Same actionable items  -> NO new issue, NO duplicate comment
#   * Changed actionable items -> update the single tracking issue in place
#       - added items   -> comment on the existing issue
#       - deleted items -> comment
#       - removed protected items -> comment (+ auto-close when empty)
#   * At most ONE open tracking issue exists at any time; pre-INFRA-385
#     duplicate open issues are closed with a pointer to the active tracker.
#   * After create/update/close, sync the Linear issue to the correct project
#     (VAL-GATE-118, INFRA-586): Linear GitHub integration does not sync the
#     project field, so we do it explicitly via LINEAR_API_KEY + LINEAR_PROJECT_ID.
#
# Environment variables for Linear project sync (VAL-GATE-118):
#   LINEAR_API_KEY        — Linear personal API key (secret)
#   LINEAR_PROJECT_ID     — Linear project UUID to link the issue to (from
#                           workflow vars: LINEAR_PROJECT_INFRA_CORE_ID or
#                           LINEAR_PROJECT_MEMORY_CORE_ID)
#   Both are optional; when absent the sync step is skipped silently.
#
# Usage (from the branch-cleanup workflow):
#   bash scripts/branch_cleanup_issue.sh \
#     --deleted /tmp/deleted_branches.txt \
#     --protected /tmp/protected_branches.txt \
#     --run-url <workflow run url> --run-date "<YYYY-MM-DD HH:MM UTC>"
#
# Input files may be missing or empty when the corresponding list is empty.
# Exit code is always 0: notification failures must not fail the workflow
# (branch cleanup itself has already run at this point).
set -euo pipefail

LABELS="automation,branch-cleanup"
# Unique marker for the single reusable tracking issue (INFRA-385). HTML
# comments are rendered invisibly on GitHub, so the marker does not clutter
# the issue body.
MARKER="<!-- branch-cleanup-tracker -->"

DELETED_FILE=""
PROTECTED_FILE=""
RUN_URL=""
RUN_DATE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --deleted)
      DELETED_FILE="$2"
      shift 2
      ;;
    --protected)
      PROTECTED_FILE="$2"
      shift 2
      ;;
    --run-url)
      RUN_URL="$2"
      shift 2
      ;;
    --run-date)
      RUN_DATE="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 --deleted <file> --protected <file> --run-url <url> --run-date <date>" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$DELETED_FILE" || -z "$PROTECTED_FILE" || -z "$RUN_URL" || -z "$RUN_DATE" ]]; then
  echo "Error: --deleted, --protected, --run-url and --run-date are all required." >&2
  exit 1
fi

# Read a branch-list file into a newline-separated string (may be empty).
# Nonexistent files are treated as empty lists.
read_list() {
  local file="$1"
  if [[ -f "$file" ]]; then
    grep -v '^[[:space:]]*$' "$file" || true
  fi
}

DELETED_ITEMS=$(read_list "$DELETED_FILE")
PROTECTED_ITEMS=$(read_list "$PROTECTED_FILE")

DELETED_COUNT=$(echo -n "$DELETED_ITEMS" | grep -c . || true)
PROTECTED_COUNT=$(echo -n "$PROTECTED_ITEMS" | grep -c . || true)

if [[ "$DELETED_COUNT" -gt 0 ]]; then
  echo "deleted_branches:"
  echo "$DELETED_ITEMS"
fi
if [[ "$PROTECTED_COUNT" -gt 0 ]]; then
  echo "protected_branches:"
  echo "$PROTECTED_ITEMS"
fi
echo "deleted_count=$DELETED_COUNT protected_count=$PROTECTED_COUNT"

# ---------------------------------------------------------------------------
# Find the single open tracking issue via its unique marker. We search for
# the marker's stable prefix because GitHub's text search splits
# "<!-- branch-cleanup-tracker -->" into words.
# ---------------------------------------------------------------------------
TRACKER_URL=""
LABELED=""

# 仓库上下文守卫（INFRA-601）：自建 runner insteadOf 镜像重写使 gh 无法从
# workspace remote 解析 host。GITHUB_REPOSITORY（Actions 默认注入）→ 所有
# 依赖仓库解析的 gh 调用追加显式 --repo；未设置（本地调试）→ 原命令形态。
GH_REPO_ARGS=()
if [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
  GH_REPO_ARGS=(--repo "${GITHUB_REPOSITORY}")
fi

# shellcheck disable=SC2016  # marker must reach gh search verbatim
SEARCH_RESULT=$(gh search issues ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} '"branch-cleanup-tracker"' --state open --json repository,url --limit 100 2>/dev/null || true)

if [[ -n "$SEARCH_RESULT" && "$SEARCH_RESULT" != "[]" ]]; then
  OURS=$(echo "$SEARCH_RESULT" | jq -r --arg repo "$GH_REPO_KEY" '[.[] | select(.repository == $repo)] | .[0].url // ""')
  if [[ -n "$OURS" ]]; then
    TRACKER_URL="$OURS"
  fi
fi

# Always resolve this repository's labeled open issues (fallback tracker
# resolution AND duplicate detection share the result).
# shellcheck disable=SC2016
LABELED=$(gh search issues --repo "$GH_REPO_KEY" ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} 'label:branch-cleanup' --state open --json url --limit 100 2>/dev/null || true)
if [[ -z "$TRACKER_URL" && -n "$LABELED" && "$LABELED" != "[]" ]]; then
  TRACKER_URL=$(echo "$LABELED" | jq -r '.[0].url // ""')
fi

gh_view_field() {
  gh issue view "$1" ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --json body --jq "$2" 2>/dev/null || echo ""
}

gh_close_with_comment() {
  gh issue close "$1" ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --comment "$2" 2>/dev/null || true
}

# Strip the markdown bullet/backticks from a tracked entry line, producing
# the same "branch (N unique commits)" string PROTECTED_ITEMS contains.
entry_of() {
  # shellcheck disable=SC2016
  sed -E 's/^- `([^`]+)`$/\1/' <<<"$1"
}

# Resolve a tracking-issue URL to its plain issue number (gh issue subcommands
# accept both, but a plain number keeps logs and mock tests unambiguous).
# grep exits 1 on no-match, which under `set -e -o pipefail` inside a command
# substitution would abort the script — normalize to an empty string instead.
issue_number_of() {
  local num
  num=$(echo "$1" | grep -oE '[0-9]+$') || num=""
  echo "$num"
}

# Close duplicate open branch-cleanup issues (pre-INFRA-385 leftovers) that
# are not the active tracker. No-op when the tracker is the only open one.
close_duplicate_trackers() {
  if [[ -z "$LABELED" || "$LABELED" == "[]" || -z "$TRACKER_NUMBER" ]]; then
    return 0
  fi
  local dupes dupe_url dupe_number
  dupes=$(echo "$LABELED" | jq -r '.[].url' | grep -vE "/$TRACKER_NUMBER$" || true)
  if [[ -z "$dupes" ]]; then
    return 0
  fi
  while IFS= read -r dupe_url; do
    [[ -z "$dupe_url" ]] && continue
    echo "Closing duplicate tracking issue $dupe_url"
    dupe_number=$(issue_number_of "$dupe_url")
    gh_close_with_comment "$dupe_number" \
"Duplicate branch-cleanup tracking issue: superseded by $TRACKER_URL (run of $RUN_DATE, $RUN_URL). Closing.

$MARKER"
  done <<< "$dupes"
}

TRACKER_NUMBER=$(issue_number_of "$TRACKER_URL")

# ---------------------------------------------------------------------------
# Linear project sync (VAL-GATE-118, INFRA-586)
# The Linear GitHub integration does not sync the project field, so we must
# explicitly link the GitHub issue to the correct Linear project after
# create/update/close. This is idempotent and fails silently if credentials
# are missing or the sync fails (notification failures must not fail workflow).
# ---------------------------------------------------------------------------
sync_linear_project() {
  # Skip if credentials or project ID not provided
  if [[ -z "${LINEAR_API_KEY:-}" || -z "${LINEAR_PROJECT_ID:-}" ]]; then
    echo "linear_sync=skipped (missing LINEAR_API_KEY or LINEAR_PROJECT_ID)"
    return 0
  fi

  # Skip if no tracker issue exists (nothing to sync)
  if [[ -z "$TRACKER_URL" ]]; then
    echo "linear_sync=skipped (no tracker issue)"
    return 0
  fi

  echo "Attempting to sync Linear project for issue $TRACKER_URL..."

  # Extract the GitHub issue URL and search for matching Linear issue
  # The Linear-GitHub integration creates a Linear issue with the same title
  # We'll search by the issue title and link it to the project

  ISSUE_TITLE="Branch cleanup tracking"

  # Query Linear for tracking issues scoped to THIS repository. The
  # Linear-GitHub integration mirrors the GitHub issue body into the Linear
  # description, which embeds the per-repo workflow run URL
  # (github.com/<owner>/<repo>/actions/runs/<id>). Title alone is ambiguous
  # across repos (memory and infra-core both track "Branch cleanup tracking"
  # in the same Linear workspace), so we filter on GH_REPO_KEY client-side;
  # otherwise one repo's run would tag the other repo's Linear issue.
  LINEAR_MATCHES=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: ${LINEAR_API_KEY}" \
    -d "{\"query\": \"query { issues(filter: { title: { eq: \\\"${ISSUE_TITLE}\\\" } }, first: 50) { nodes { id description } } }\"}" \
    https://api.linear.app/graphql 2>/dev/null)

  LINEAR_ISSUE_IDS=$(echo "$LINEAR_MATCHES" | jq -r --arg repo "github.com/${GH_REPO_KEY}/" \
    '[.data.issues.nodes[]? | select((.description // "") | contains($repo)) | .id] | join("\n")')

  if [[ -z "$LINEAR_ISSUE_IDS" ]]; then
    echo "linear_sync=skipped (Linear issue not found or not yet synced)"
    return 0
  fi

  # Sync every same-repo match (current + historical trackers); issueUpdate
  # with projectId is idempotent (re-assigning an issue already in the project
  # is a no-op). VAL-GATE-118 真红根因（2026-08-30, run 33284405687）：此前使用的
  # project-relation mutation 已从 Linear GraphQL schema 移除（直连复现
  # GRAPHQL_VALIDATION_FAILED），LINEAR_API_KEY 轮换后首次 live 执行即三次
  # linear_sync=failed；改用现行 issueUpdate API。回归钉死见
  # tests/test_branch_cleanup_issue.py::test_dead_mutation_name_must_not_reappear。
  while IFS= read -r LINEAR_ISSUE_ID; do
    [[ -z "$LINEAR_ISSUE_ID" ]] && continue

    MUTATION_RESULT=$(curl -s -X POST \
      -H "Content-Type: application/json" \
      -H "Authorization: ${LINEAR_API_KEY}" \
      -d "{\"query\": \"mutation { issueUpdate(id: \\\"${LINEAR_ISSUE_ID}\\\", input: { projectId: \\\"${LINEAR_PROJECT_ID}\\\" }) { success issue { id } } }\"}" \
      https://api.linear.app/graphql 2>/dev/null)

    if echo "$MUTATION_RESULT" | jq -e '.data.issueUpdate.success' >/dev/null; then
      echo "linear_sync=success (issue=${LINEAR_ISSUE_ID} project=${LINEAR_PROJECT_ID})"
    else
      # Fail silently - sync failures must not break the workflow
      echo "linear_sync=failed (mutation unsuccessful)"
    fi
  done <<< "$LINEAR_ISSUE_IDS"
}

# ---------------------------------------------------------------------------
# Nothing actionable: close the tracking issue as resolved, if any.
# ---------------------------------------------------------------------------
if [[ "$DELETED_COUNT" -eq 0 && "$PROTECTED_COUNT" -eq 0 ]]; then
  if [[ -n "$TRACKER_URL" ]]; then
    echo "No actionable branches: closing tracking issue $TRACKER_URL"
    gh_close_with_comment "$TRACKER_NUMBER" \
"All branch-cleanup items resolved (run of $RUN_DATE, $RUN_URL). Closing this tracking issue.

$MARKER"
    echo "issue_action=closed"
    sync_linear_project
  else
    echo "No actionable branches and no open tracking issue. Nothing to do."
    echo "issue_action=none"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Build the report section for the current run.
# ---------------------------------------------------------------------------
REPORT="**Run date:** $RUN_DATE
**Deleted branches:** $DELETED_COUNT
**Protected branches:** $PROTECTED_COUNT
**Workflow run:** $RUN_URL
"
if [[ "$DELETED_COUNT" -gt 0 ]]; then
  REPORT+=$'\n'"### Deleted branches"$'\n'$'\n'
  while IFS= read -r branch; do
    REPORT+="- \`$branch\`"$'\n'
  done <<< "$DELETED_ITEMS"
fi
if [[ "$PROTECTED_COUNT" -gt 0 ]]; then
  REPORT+=$'\n'"### 🛡️ Protected branches (unmerged unique commits)"$'\n'$'\n'
  REPORT+="These branches were protected from deletion because they contain unique commits not in main and their PR was closed without merging:"$'\n'$'\n'
  while IFS= read -r branch; do
    REPORT+="- \`$branch\`"$'\n'
  done <<< "$PROTECTED_ITEMS"
fi

# Extract "- `branch (N unique commits)`" entries from a tracking-issue body.
get_protected_from_body() {
  local body="$1"
  # Emit full entry lines (`- \`branch (N unique commits)\``) verbatim so the
  # tracked set compares equal to PROTECTED_ITEMS entries from this run.
  # Tolerate the plain branch form (`- \`branch\``) for hand-written lists.
  # grep exits 1 on no-match — normalize so the script survives `set -e`.
  # shellcheck disable=SC2016  # $ anchors are regex, not expansions
  grep -oE '^- `[^`]+( \([0-9]+ unique commits\))?`$' <<<"$body" || true
}

if [[ -z "$TRACKER_URL" ]]; then
  # No open tracking issue: create the single reusable one.
  echo "Creating tracking issue"
  BODY="## Automated Branch Cleanup (tracking)

$REPORT
---
*This tracking issue is managed by the [Branch Cleanup]($RUN_URL) workflow; it is updated in place instead of one issue per run ($MARKER).*"
  gh label create automation ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --force >/dev/null 2>&1 || true
  gh label create branch-cleanup ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --force >/dev/null 2>&1 || true
  # 仓库上下文守卫沿用上方 GH_REPO_ARGS（INFRA-601 统一化）
  GH_ISSUE_CREATE_CMD=(gh issue create
    --title "Branch cleanup tracking"
    --body "$BODY"
    --label "$LABELS"
    ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"})
  # create-path gap 修复（live 发现 run 33285476683 / INFRA-632）：回填新建
  # tracker 的 URL/编号，sync_linear_project 才能在创建当轮发起 Linear 同步。
  # 此前 TRACKER_URL 仍为空，同步恒走 skipped (no tracker issue)，新建
  # tracker 的 Linear mirror 永远挂不上 project（后续 run reused-silent 不补）。
  CREATED_URL=$("${GH_ISSUE_CREATE_CMD[@]}" 2>/dev/null | tail -n 1) || CREATED_URL=""
  if [[ -n "$CREATED_URL" ]]; then
    TRACKER_URL="$CREATED_URL"
    TRACKER_NUMBER=$(issue_number_of "$TRACKER_URL")
  fi
  echo "issue_action=created"
  # Sync to Linear project (VAL-GATE-118)。Linear GitHub integration 的 mirror
  # 可能尚未建好——此时按三态语义记 skipped (not yet synced)，后续
  # update/close 路径会补挂。
  sync_linear_project
  exit 0
fi

# ---------------------------------------------------------------------------
# Tracking issue exists: diff the protected lists.
# ---------------------------------------------------------------------------
TRACKER_BODY=$(gh_view_field "$TRACKER_NUMBER" '.body')
CURRENT_PROTECTED="$PROTECTED_ITEMS"
TRACKED_PROTECTED=""
while IFS= read -r entry; do
  [[ -z "$entry" ]] && continue
  TRACKED_PROTECTED+="${TRACKED_PROTECTED:+$'\n'}$(entry_of "$entry")"
done <<< "$(get_protected_from_body "$TRACKER_BODY")"

only_in() { # $1 items not in $2 (comm exits 1 when sets differ — tolerated)
  comm -23 <(echo "$1" | sort -u) <(echo "$2" | sort -u) || true
}

ADDED_PROTECTED=$(only_in "$CURRENT_PROTECTED" "$TRACKED_PROTECTED")
REMOVED_PROTECTED=$(only_in "$TRACKED_PROTECTED" "$CURRENT_PROTECTED")

if [[ -z "$ADDED_PROTECTED" && -z "$REMOVED_PROTECTED" && "$DELETED_COUNT" -eq 0 ]]; then
  echo "Protected branches unchanged (duplicate run): no new issue, no comment."
  # Still close pre-INFRA-385 duplicates: same protected set, separate issues.
  close_duplicate_trackers
  echo "issue_action=reused-silent"
  exit 0
fi

NEW_BODY="## Automated Branch Cleanup (tracking)

$REPORT
---
*This tracking issue is managed by the [Branch Cleanup]($RUN_URL) workflow; it is updated in place instead of one issue per run ($MARKER).*"

COMMENT_BODY=""
if [[ "$DELETED_COUNT" -gt 0 ]]; then
  COMMENT_BODY+="**[$RUN_DATE] Deleted branches:**"$'\n'
  while IFS= read -r branch; do
    COMMENT_BODY+="- \`$branch\`"$'\n'
  done <<< "$DELETED_ITEMS"
fi
if [[ -n "$ADDED_PROTECTED" ]]; then
  [[ -n "$COMMENT_BODY" ]] && COMMENT_BODY+=$'\n'
  COMMENT_BODY+="**[$RUN_DATE] Newly protected branches (unmerged unique commits):**"$'\n'
  while IFS= read -r branch; do
    COMMENT_BODY+="- \`$branch\`"$'\n'
  done <<< "$ADDED_PROTECTED"
fi
if [[ -n "$REMOVED_PROTECTED" ]]; then
  [[ -n "$COMMENT_BODY" ]] && COMMENT_BODY+=$'\n'
  COMMENT_BODY+="**[$RUN_DATE] Resolved branches (no longer protected):**"$'\n'
  while IFS= read -r branch; do
    COMMENT_BODY+="- \`$branch\`"$'\n'
  done <<< "$REMOVED_PROTECTED"
fi

# Update body in place
gh issue edit "$TRACKER_NUMBER" ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --body "$NEW_BODY" >/dev/null 2>&1 || true
# Deletions are also reportable state changes; comment whenever we got here.
if gh issue comment "$TRACKER_NUMBER" ${GH_REPO_ARGS[@]+"${GH_REPO_ARGS[@]}"} --body "$COMMENT_BODY" >/dev/null 2>&1; then
  echo "issue_action=updated"
  # Sync to Linear project (VAL-GATE-118)
  sync_linear_project
else
  echo "issue_action=update-failed"
fi

# Close pre-INFRA-385 duplicate open issues (same label, not the tracker).
close_duplicate_trackers

exit 0
