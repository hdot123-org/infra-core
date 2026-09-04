#!/bin/bash
# shellcheck disable=SC2034
# trigger-release.sh — 发版公告 → droid exec 异步触发器
# 由 adnanh/webhook 调用，立即返回 accepted，后台执行 droid + release-gateway skill
#
# 架构：architecture.md §3 C3
# 行为：
# 1. 读 repositories.yml 选 engineConsumer: true 的仓
# 2. per-tag 幂等锁 ~/.factory/webhook/locks/release-announce-{tag}.json
# 3. 逐仓（错误隔离）：cd repoPath → git pull --ff-only → droid exec --tag release-gateway
# 4. --dry-run 模式：只打印 tag/锁路径/选仓清单，零副作用
#
# 参照：trigger-droid.sh 解析、write-pending-ci.sh 原子锁、trigger-error-droid.sh 错误隔离

set -uo pipefail

# === Env-overridable constants (测试友好) ===
WEBHOOK_BASE="${WEBHOOK_BASE:-${HOME}/.factory/webhook}"
LOCKS_DIR="${LOCKS_DIR:-${WEBHOOK_BASE}/locks}"
LOG_DIR="${LOG_DIR:-${WEBHOOK_BASE}/logs}"
REPO_CONFIG="${REPO_CONFIG:-${HOME}/.factory/config/repositories.yml}"

# === 参数 ===
TAG="${1:-}"
RELEASE_URL="${2:-}"
SOURCE_REPO="${3:-}"

# === 日志 ===
LOG_FILE="${LOG_DIR}/trigger-release.log"
mkdir -p "$LOG_DIR" 2>/dev/null

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# === Python binary ===
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

# === 辅助函数 ===

# 选仓：读 repositories.yml，返回 engineConsumer: true 的仓清单（repoKey|repoPath 格式）
select_consumers() {
    if [ ! -f "$REPO_CONFIG" ]; then
        return
    fi

    "$PYTHON_BIN" -c "
import yaml, sys
try:
    with open('$REPO_CONFIG') as f:
        cfg = yaml.safe_load(f)
    for team in cfg.get('teams', {}).values():
        for repo in team.get('repos', []):
            if repo.get('engineConsumer', False):
                repo_key = repo.get('repoKey', '')
                repo_path = repo.get('repoPath', '')
                if repo_key and repo_path:
                    print(f'{repo_key}|{repo_path}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
}

# 原子写锁（tmp + mv）
write_lock_atomic() {
    local lock_file="$1"
    local tag="$2"
    local repo="$3"
    local consumers="$4"
    local created_at
    created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local tmp_file="${lock_file}.tmp.$$"

    "$PYTHON_BIN" -c "
import json, sys
data = {
    'tag': sys.argv[1],
    'repo': sys.argv[2],
    'consumers': sys.argv[3].split(',') if sys.argv[3] else [],
    'created_at': sys.argv[4]
}
with open(sys.argv[5], 'w') as f:
    json.dump(data, f, indent=2)
" "$tag" "$repo" "$consumers" "$created_at" "$tmp_file"

    # 验证 JSON 合法
    if ! "$PYTHON_BIN" -c "import json; json.load(open('$tmp_file'))" 2>/dev/null; then
        rm -f "$tmp_file"
        return 1
    fi

    mv -f "$tmp_file" "$lock_file"
}

# tag 含 / 时安全转换锁文件名
safe_lock_filename() {
    local tag="$1"
    # 将 / 替换为 -
    echo "$tag" | sed 's/\//-/g'
}

# === 主流程 ===

# 参数校验
if [ -z "$TAG" ]; then
    log "ERROR: TAG parameter required"
    exit 1
fi

# dry-run 模式
DRY_RUN=0
if [ "$TAG" = "--dry-run" ]; then
    DRY_RUN=1
    TAG="${2:-}"
    RELEASE_URL="${3:-}"
    SOURCE_REPO="${4:-}"
fi

if [ -z "$TAG" ]; then
    log "ERROR: TAG parameter required"
    exit 1
fi

# 锁文件路径（tag 含 / 时安全转换）
safe_tag=$(safe_lock_filename "$TAG")
LOCK_FILE="${LOCKS_DIR}/release-announce-${safe_tag}.json"
mkdir -p "$LOCKS_DIR" 2>/dev/null

# 选仓
CONSUMERS_LIST=$(select_consumers)
if [ -z "$CONSUMERS_LIST" ]; then
    CONSUMER_COUNT=0
else
    CONSUMER_COUNT=$(echo "$CONSUMERS_LIST" | wc -l | tr -d ' ')
fi

# dry-run：只打印，零副作用
if [ "$DRY_RUN" -eq 1 ]; then
    echo "=== DRY-RUN MODE ==="
    echo "Tag: $TAG"
    echo "Lock path: $LOCK_FILE"
    echo "Selected consumers:"
    if [ "$CONSUMER_COUNT" -gt 0 ]; then
        echo "$CONSUMERS_LIST" | while IFS='|' read -r repo_key repo_path; do
            echo "  - $repo_key ($repo_path)"
        done
    else
        echo "  (none)"
    fi
    exit 0
fi

# 无消费者：安静退出，不写锁
if [ "$CONSUMER_COUNT" -eq 0 ]; then
    log "无消费者（engineConsumer: true），跳过派发"
    exit 0
fi

# 幂等检查：锁已存在则跳过
if [ -f "$LOCK_FILE" ]; then
    log "幂等跳过：锁已存在 $LOCK_FILE"
    exit 0
fi

# 提取消费者清单（逗号分隔的 repoKey 列表）
CONSUMER_KEYS=$(echo "$CONSUMERS_LIST" | cut -d'|' -f1 | tr '\n' ',' | sed 's/,$//')

# 写锁（原子 tmp + mv）
if ! write_lock_atomic "$LOCK_FILE" "$TAG" "$SOURCE_REPO" "$CONSUMER_KEYS"; then
    log "ERROR: 锁写入失败"
    exit 1
fi

log "锁已创建: $LOCK_FILE (consumers: $CONSUMER_KEYS)"

# 后台派发（hook 立即应答）
(
    # 遍历消费者
    echo "$CONSUMERS_LIST" | while IFS='|' read -r repo_key repo_path; do
        [ -z "$repo_key" ] && continue

        log "=== 派发 $repo_key ($repo_path) ==="

        # cd 到仓
        if ! cd "$repo_path" 2>/dev/null; then
            log "ERROR: cd $repo_path 失败，跳过"
            continue
        fi

        # 检查工作树是否干净
        if ! git diff-index --quiet HEAD -- 2>/dev/null; then
            log "跳过 $repo_key: 工作树脏（有未提交改动）"
            continue
        fi

        # git pull --ff-only
        if ! git pull --ff-only >/dev/null 2>&1; then
            log "跳过 $repo_key: git pull --ff-only 失败（可能是分叉或网络问题）"
            continue
        fi

        # droid exec
        log "执行 droid exec for $repo_key"

        PROMPT="infra-core ${TAG} 已发布，请按 release-gateway skill 执行升级。

## 公告信息
- **Tag**: ${TAG}
- **Release URL**: ${RELEASE_URL}
- **Source Repo**: ${SOURCE_REPO}
- **Trigger Source**: release-announce

请按 release-gateway skill 的 bump 配方执行：
1. 验证目标 tag 已真实上线
2. 全仓搜索 infra-core pin 面
3. bump 到新 tag
4. 跑测试
5. 开 PR + write-pending-ci.sh --source session --context engine-upgrade <PR>
"

        if [ "${ECHO_DROID:-0}" = "1" ]; then
            log "[STUB_DROID] Would run: droid exec --auto high --output-format json --tag '{\"name\":\"release-gateway\",\"metadata\":{\"tag\":\"${TAG}\",\"sourceRepo\":\"${SOURCE_REPO}\",\"triggerSource\":\"release-announce\"}}' \"<prompt>\""
            DROID_OUTPUT='{"type":"result","session_id":"stub-session-id-12345","result":"dry-run ok"}'
        else
            DROID_OUTPUT=$(droid exec \
                --auto high \
                --output-format json \
                --tag "{\"name\":\"release-gateway\",\"metadata\":{\"tag\":\"${TAG}\",\"sourceRepo\":\"${SOURCE_REPO}\",\"triggerSource\":\"release-announce\"}}" \
                "$PROMPT" 2>&1) || true
        fi

        # 提取 session_id
        SESSION_ID=$(echo "$DROID_OUTPUT" | "$PYTHON_BIN" -c "
import json, sys
try:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get('type') == 'result' and 'session_id' in d:
            print(d['session_id'])
            break
except:
    pass
" 2>/dev/null)

        if [ -n "$SESSION_ID" ]; then
            log "session_id: $SESSION_ID"
        else
            log "WARN: 无法提取 session_id"
        fi

        log "=== 完成 $repo_key ==="
    done
) >> "$LOG_FILE" 2>&1 &
SUBSHELL_PID=$!

log "后台派发已启动: PID=$SUBSHELL_PID"

# 立即返回（hook 应答）
exit 0
