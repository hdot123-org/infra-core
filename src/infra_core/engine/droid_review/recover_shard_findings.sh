#!/usr/bin/env bash
# recover_shard_findings.sh — exit 137 完成期竞态的 session jsonl 兜底恢复
#
# 背景（2026-08-29 #40/#45/#47 多次实证，run 33226955612 debug artifact）：
# droid exec 完成审查（session jsonl 最后一行已是完整 findings JSON）但在最终
# stdout flush 前被 SIGKILL（137），tee 捕获 0 字节。stdout 路报废时，本脚本从
# 本 run 的会话产物恢复 findings——stdout 与会话两路皆空才允许 fail-closed。
#
# 用法：
#   recover_shard_findings.sh <droid_cwd> <start_epoch> <shard_id> <out_file>
#   环境变量：RUN_ID（本 run id）、FACTORY_SESSIONS_DIR（默认 ~/.factory/sessions）
#
# Factory 会话存储布局（实证）：
#   ~/.factory/sessions/<cwd 中 / 替换为 ->/<session-id>.jsonl
#   例：/var/lib/actions-runner-02/_work/infra-core/infra-core/head-src
#    → -var-lib-actions-runner-02-_work-infra-core-infra-core-head-src
#
# 候选选择规则（自共享持久 runner 的串扰防护，逐条硬校验）：
#   1. mtime ≥ start_epoch（本次 droid exec 启动时刻，1 秒余量）——排除历史 run 会话
#   2. 文件含本 run 唯一 prompt 标记 droid-review-shard-marker:<RUN_ID>-<SHARD_ID>
#      ——排除同机并行的其他 run / 其他 shard 会话
#   3. 最后一行 assistant text 中提取 ```json 块，.shard_id 匹配且 .findings 为数组
#      ——排除被 SIGKILL 截断的半成品 JSON
#   候选按最新优先迭代（最多 5 个），全部不满足 → 非零退出（fail-closed）。
#
# bash 3.2 兼容（macOS 自带 bash 可直接测试）：不用 readarray/mapfile。
set -euo pipefail

DROID_CWD="${1:-}"
START_EPOCH="${2:-}"
SHARD_ID="${3:-}"
OUT_FILE="${4:-}"

if [ -z "$DROID_CWD" ] || [ -z "$START_EPOCH" ] || [ -z "$SHARD_ID" ] || [ -z "$OUT_FILE" ]; then
  echo "usage: recover_shard_findings.sh <droid_cwd> <start_epoch> <shard_id> <out_file>" >&2
  exit 2
fi

SESSIONS_ROOT="${FACTORY_SESSIONS_DIR:-$HOME/.factory/sessions}"
SESSION_DIR="$SESSIONS_ROOT/$(printf '%s' "$DROID_CWD" | tr '/' '-')"
MARKER="droid-review-shard-marker:${RUN_ID:-unknown}-${SHARD_ID}"

if [ ! -d "$SESSION_DIR" ]; then
  echo "session recovery: sessions dir not found: $SESSION_DIR"
  exit 1
fi

# mtime 参照文件（便携：GNU/BSD find 都支持 -newer <file>；1 秒余量防同秒误杀）
REF_FILE=$(mktemp "${TMPDIR:-/tmp}/droid-recovery-ref.XXXXXX")
trap 'rm -f "$REF_FILE"' EXIT
python3 -c "import os,sys; open(sys.argv[1], 'w').close(); os.utime(sys.argv[1], (int(sys.argv[2]), int(sys.argv[2])))" \
  "$REF_FILE" "$((START_EPOCH - 1))"

CANDIDATES=()
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  grep -F -q -- "$MARKER" "$f" 2>/dev/null || continue
  CANDIDATES+=("$f")
done < <(find "$SESSION_DIR" -name '*.jsonl' -newer "$REF_FILE" 2>/dev/null)

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
  echo "session recovery: no candidate sessions (marker: $MARKER, window: >= $START_EPOCH)"
  exit 1
fi

# 最新优先（候选名为 UUID，无空格；ls -t 失败则保持 find 顺序兜底）
SORTED=""
SORTED=$(printf '%s\n' "${CANDIDATES[@]}" | xargs ls -t 2>/dev/null) || SORTED=$(printf '%s\n' "${CANDIDATES[@]}")

N=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  N=$((N + 1))
  if [ "$N" -gt 5 ]; then
    break
  fi
  # 最后一行 assistant text（两级管道容错：-R 逐行 fromjson，尾行截断不影响已完整行）
  TEXT=""
  TEXT=$(jq -R 'fromjson? // empty' "$f" 2>/dev/null \
    | jq -rs '
        map(select(.type == "message" and .message.role == "assistant"))
        | last
        | .message.content[]? | select(.type == "text") | .text // empty
      ' 2>/dev/null) || TEXT=""
  if [ -z "$TEXT" ]; then
    echo "session recovery: no assistant text in candidate: $f"
    continue
  fi
  JSON_BLOCK=""
  # shellcheck disable=SC2016  # ```json 是字面量 markdown 围栏，不需要展开
  JSON_BLOCK=$(printf '%s\n' "$TEXT" | sed -n '/```json/,/```/p' | sed '1d;$d' | sed '/^$/d') || JSON_BLOCK=""
  if [ -n "$JSON_BLOCK" ] && printf '%s\n' "$JSON_BLOCK" | jq -e --arg sid "$SHARD_ID" \
      '.shard_id != null and (.shard_id | tostring) == $sid and (.findings | type == "array")' \
      >/dev/null 2>&1; then
    printf '%s\n' "$JSON_BLOCK" | jq '.' > "$OUT_FILE"
    echo "::warning::droid exec stdout 为空（exit 137 完成期竞态），findings 自 session jsonl 恢复：$f"
    exit 0
  fi
  echo "session recovery: candidate rejected (truncated / shard_id mismatch): $f"
done <<< "$SORTED"

echo "session recovery: all candidates exhausted — no valid findings"
exit 1
