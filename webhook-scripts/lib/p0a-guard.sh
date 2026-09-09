#!/bin/bash
# shellcheck disable=SC2034
# lib/p0a-guard.sh — P0-A watchdog 源感知三查守卫（R1 补丁）
#
# 在 watchdog/trigger-ci-droid fallback 开枪前执行三项检查：
#
#   Check ①: gh pr view 查评论含 <!-- droid-autofix-attempt-N --> sentinel
#            → 让路（只记日志，不开枪）
#   Check ②: pending-ci source == "runner" → 静默（runner 来源自管 CI）
#   Check ③: AUTOFIX_AUTO_ENABLED=true 且 source != runner → 降级告警不开枪
#            （autofix 是第一修复者，Mac watchdog 不应与 runner autofix 竞争）
#
# 返回值通过 P0A_GUARD_RESULT 传递（避免 subshell 吞掉调用方变量）：
#   P0A_GUARD_RESULT="proceed"        — 无拦截，正常开枪
#   P0A_GUARD_RESULT="yield_sentinel" — autofix 已介入（sentinel），让路
#   P0A_GUARD_RESULT="silent_runner"  — runner 来源，静默跳过
#   P0A_GUARD_RESULT="alert_only"     — autofix 活跃，降级为告警
#
# 调用约定：
#   source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/p0a-guard.sh"
#
#   _p0a_guard_run "$PR_NUMBER" "$SOURCE" "$PR_REPO"
#   case "$P0A_GUARD_RESULT" in
#     proceed)        spawn_fallback ... ;;
#     yield_sentinel) echo "P0-A: yielding (autofix sentinel found)" ;;
#     silent_runner)  echo "P0-A: runner source, silent cleanup" ;;
#     alert_only)     send_posthog_event "p0a_autofix_degraded" ... ;;
#   esac
#
# 测试干跑：
#   P0A_DRY_RUN=1           — 跳过 gh pr view（CI 测试环境无 gh 或网络）
#   P0A_DRY_RUN_SENTINEL=1  — 模拟 sentinel 存在（让路场景）
#   P0A_DRY_RUN_SENTINEL=0  — 模拟 sentinel 不存在

# shellcheck disable=SC2034
P0A_GUARD_RESULT="proceed"

# _p0a_check_sentinel — 检查 PR 评论中是否含 autofix sentinel
# 参数: $1=pr_number, $2=repo_slug（owner/repo 格式，可为空）
# 输出: "found" | "none"
# 副作用: 无（纯读操作）
_p0a_check_sentinel() {
  local pr_num="$1"
  local repo_slug="${2:-}"

  # 测试干跑模式
  if [ "${P0A_DRY_RUN:-0}" = "1" ]; then
    if [ "${P0A_DRY_RUN_SENTINEL:-0}" = "1" ]; then
      echo "found"
    else
      echo "none"
    fi
    return 0
  fi

  # gh 不可用时返回 none（不阻塞 fallback 开枪——保守路径）
  if ! command -v gh &>/dev/null; then
    echo "none"
    return 0
  fi

  local gh_args=()
  if [ -n "$repo_slug" ]; then
    gh_args=(-R "$repo_slug")
  fi
  gh_args+=(pr view "$pr_num" --json comments --jq '[.comments[].body | select(contains("<!-- droid-autofix-attempt"))] | length')

  local count
  count=$(gh "${gh_args[@]}" 2>/dev/null) || { echo "none"; return 0; }

  # count 为数字且 > 0 → found
  if [[ "$count" =~ ^[0-9]+$ ]] && [ "$count" -gt 0 ]; then
    echo "found"
  else
    echo "none"
  fi
}

# _p0a_guard_run — 三查主入口
# 参数: $1=pr_number, $2=source, $3=repo_slug（可为空）
# 返回: P0A_GUARD_RESULT（全局变量）
_p0a_guard_run() {
  local pr_num="$1"
  local p0a_source="${2:-}"
  local p0a_repo="${3:-}"

  P0A_GUARD_RESULT="proceed"

  # Check ②: runner source → 静默（最快路径，无外部调用）
  if [ "$p0a_source" = "runner" ]; then
    P0A_GUARD_RESULT="silent_runner"
    return 0
  fi

  # Check ①: sentinel → 让路
  local sentinel
  sentinel=$(_p0a_check_sentinel "$pr_num" "$p0a_repo")
  if [ "$sentinel" = "found" ]; then
    P0A_GUARD_RESULT="yield_sentinel"
    return 0
  fi

  # Check ③: AUTOFIX_AUTO_ENABLED=true + 非 runner → 降级告警
  # 注意：runner 已在 Check ② 拦截，此处剩余来源均为非 runner
  if [ "${AUTOFIX_AUTO_ENABLED:-false}" = "true" ]; then
    P0A_GUARD_RESULT="alert_only"
    return 0
  fi

  P0A_GUARD_RESULT="proceed"
}
