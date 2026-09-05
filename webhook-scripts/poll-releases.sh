#!/bin/bash
# shellcheck disable=SC2034
# poll-releases.sh — 列表式轮询 GitHub Releases，发现新 tag 后调用既有 trigger-release.sh
#
# 架构：architecture.md §3 C9（2026-09-05 裁定：轮询为默认触发面）
# 行为：
# 1. `gh api 'repos/hdot123-org/infra-core/releases?per_page=20'` 列表式轮询
#    （凭据用 gh 已有 auth，不落日志）
# 2. 遍历非 draft release 的 tag，latest 与非 latest 一视同仁
# 3. per-tag 锁为"已见状态"：有锁 → 跳过记日志；无锁 → 调用 trigger-release.sh
# 4. --init 首装自举：一次性为全部现存 tag 预建锁（防历史 tag 首跑全量派发）
# 5. bash 3.2.57 兼容；API 失败/超时 → 日志留痕 + exit 0
#
# 参照：trigger-release.sh 锁体系与日志惯例

set -uo pipefail

# === Env-overridable constants (测试友好) ===
WEBHOOK_BASE="${WEBHOOK_BASE:-${HOME}/.factory/webhook}"
LOCKS_DIR="${LOCKS_DIR:-${WEBHOOK_BASE}/locks}"
LOG_DIR="${LOG_DIR:-${WEBHOOK_BASE}/logs}"
REPO="hdot123-org/infra-core"
TRIGGER_SCRIPT="${TRIGGER_SCRIPT:-${HOME}/.factory/webhook/scripts/trigger-release.sh}"

# === 日志 ===
LOG_FILE="${LOG_DIR}/poll-releases.log"
mkdir -p "$LOG_DIR" 2>/dev/null

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# === 参数 ===
INIT_MODE=0
if [ "${1:-}" = "--init" ]; then
    INIT_MODE=1
fi

# === tag 含 / 时安全转换锁文件名（与 trigger-release.sh 同口径）===
safe_lock_filename() {
    local tag="$1"
    echo "$tag" | sed 's/\//-/g'
}

# === --init 首装自举 ===
if [ "$INIT_MODE" -eq 1 ]; then
    log "=== --init 自举模式开始 ==="

    # 调用 GitHub API 获取全部非 draft release
    api_output=$(gh api "repos/${REPO}/releases?per_page=100" 2>&1) || {
        log "ERROR: --init API 调用失败: $api_output"
        exit 0
    }

    # 提取全部非 draft release 的 tag_name
    tags=$(echo "$api_output" | python3 -c "
import json, sys
try:
    releases = json.load(sys.stdin)
    for r in releases:
        if not r.get('draft', False):
            print(r['tag_name'])
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
") || {
        log "ERROR: --init JSON 解析失败"
        exit 0
    }

    if [ -z "$tags" ]; then
        log "--init: 无 release 可自举"
        exit 0
    fi

    count=0
    echo "$tags" | while IFS= read -r tag || [ -n "${tag:-}" ]; do
        [ -z "${tag:-}" ] && continue
        safe_tag=$(safe_lock_filename "$tag")
        lock_file="${LOCKS_DIR}/release-announce-${safe_tag}.json"

        if [ -f "$lock_file" ]; then
            log "--init: 锁已存在，跳过 $tag"
            continue
        fi

        mkdir -p "$LOCKS_DIR" 2>/dev/null
        # 创建占位锁（表示"已见"，无 consumers）
        created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        python3 -c "
import json, sys
data = {
    'tag': sys.argv[1],
    'repo': sys.argv[2],
    'consumers': [],
    'created_at': sys.argv[3],
    'bootstrap': True
}
with open(sys.argv[4], 'w') as f:
    json.dump(data, f, indent=2)
" "$tag" "$REPO" "$created_at" "$lock_file"

        log "--init: 预建锁 $tag → $lock_file"
        count=$((count + 1))
    done

    log "=== --init 自举完成 ==="
    exit 0
fi

# === 正常轮询模式 ===
log "=== 轮询开始 ==="

# 调用 GitHub API（认证，凭据用 gh 已有 auth）
api_output=$(gh api "repos/${REPO}/releases?per_page=20" 2>&1) || {
    log "ERROR: API 调用失败，下周期重试: $api_output"
    exit 0
}

# 提取非 draft release 的 tag_name 和 html_url
releases=$(echo "$api_output" | python3 -c "
import json, sys
try:
    releases = json.load(sys.stdin)
    for r in releases:
        if not r.get('draft', False):
            tag = r['tag_name']
            url = r.get('html_url', '')
            print(f'{tag}|{url}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
") || {
    log "ERROR: JSON 解析失败，下周期重试"
    exit 0
}

if [ -z "$releases" ]; then
    log "无 release 可轮询"
    exit 0
fi

# 遍历每个 release
echo "$releases" | while IFS='|' read -r tag release_url || [ -n "${tag:-}" ]; do
    [ -z "${tag:-}" ] && continue

    safe_tag=$(safe_lock_filename "$tag")
    lock_file="${LOCKS_DIR}/release-announce-${safe_tag}.json"

    if [ -f "$lock_file" ]; then
        log "锁已存在，跳过 $tag"
        continue
    fi

    log "发现新 release: $tag，调用 trigger-release.sh"

    # 调用既有 trigger-release.sh（锁创建与逐仓派发由其负责）
    if [ -x "$TRIGGER_SCRIPT" ]; then
        "$TRIGGER_SCRIPT" "$tag" "$release_url" "$REPO" >> "$LOG_FILE" 2>&1 || {
            log "WARN: trigger-release.sh 非零退出，错误隔离继续下一个 tag"
        }
    else
        log "ERROR: trigger-release.sh 不存在或不可执行: $TRIGGER_SCRIPT"
    fi
done

log "=== 轮询完成 ==="
exit 0
