#!/bin/bash
# MANIFEST.sh - 受管文件清单与环境差异声明
# 本文件定义 webhook-scripts/ 中受版本控制的脚本及其与生产环境的已知差异
#
# 所有权（M5 shrink，INFRA mission）：webhook 生产同步的真源自本仓库
# （hdot123-org/infra-core）。memory-core 侧同名 manifest 已随 M5 收缩删除，
# 过渡期两 manifest 不双 claim 同一生产文件名。
#
# M5 回滚窗口关闭口径（INFRA-738 对齐）：权威口径以 memory 仓处置记录
# docs/specs/M5-SHRINK-DISPOSITION.md 为准（memory #1104 追加 §6 窗口关闭
# 记录），本 manifest 叙述与其不一致时以处置记录为准：
# - 窗口载体是 evolution 四件套回滚副本 scripts/evolution_{scanner,
#   heartbeat,utils,adapters}.py（处置记录 §2 保留窗口），由 memory #1097
#   删除；关闭门为「release v0.45.0（2026-08-30T09:44:45Z）+ ≥3 天稳定期」
#   （门成熟 2026-09-02T09:44Z，#1097 早于门约 29.5h，零 revert 敞口损失）。
# - 锚点助手副本 scripts/{extract_anchor,anchor_gate}.py 不设窗口，随 M5
#   收缩 PR 直接删除（处置记录 §1），并非回滚窗口的一部分。
#
# 注意：本文件被 source 时不应改变调用方的 shell 选项（如 errexit/nounset）
# 因此故意不使用 set -euo pipefail

# ============================================================================
# 受管文件清单 (Managed Files)
# ============================================================================
# 列出 webhook-scripts/ 中受版本控制的所有脚本
# sync-webhook-scripts.sh 会同步这些文件到生产环境

MANAGED_FILES=(
    "trigger-droid.sh"
    "trigger-ci-droid.sh"
    "trigger-release.sh"
    "poll-releases.sh"
    "reconcile-evolution.sh"
    "ci-timeout-watchdog.sh"
    "trigger-error-droid.sh"
    "wiki-refresh.sh"
    "write-pending-ci.sh"
    "ci-failed.sh"
    "webhook-hygiene.sh"
    "local_branch_cleanup.sh"
    "write_comment.py"
    "drift-gate.sh"
)

# lib/ 子目录下的受管文件（source 依赖，非独立脚本）
MANAGED_LIB_FILES=(
    "lib/posthog.sh"
    "lib/op-mcp.sh"
)

# ============================================================================
# 跨目录同步映射 (Cross-Directory Sync Mappings)
# ============================================================================
# 锚点助手依赖链部署副本（M5 起自本仓路径同步）。
# sync-webhook-scripts.sh 会将这些文件从仓库相对路径同步到生产目录。
# 背景 (INFRA-357): 生产 extract_anchor.py 缺少 evolution_utils.py /
# evolution_adapters.py 依赖导致 ModuleNotFoundError —— 依赖链必须与调用方
# 一同受管部署，堵住部署漂移。anchor_gate.py 为补偿层关闭路径的锚点守卫
# （trigger-droid.sh L1166，与 extract_anchor.py 同链部署）。
#
# 血缘收敛（INFRA-679）：M5 迁移时点曾在本仓 webhook-scripts/cross-dir/
# 维护 memory-core 生产血统的逐字节快照作为同步源，与 src/infra_core/engine/
# 的引擎演化线形成双副本（CODE_HYGIENE_DUPLICATE_BLOCK 重复块根因）。
# memory 侧回滚窗口四件套（evolution_{scanner,heartbeat,utils,adapters}.py）
# 随 memory #1097 删除、窗口按处置记录 §6 权威口径关闭后，本清单收敛到
# 引擎单源 src/infra_core/engine/——与 CI/CLI 的 python -m
# infra_core.engine.* 消费面同源，快照副本目录 cross-dir/ 随之退役。
# 引擎版本与旧快照在生产消费面（extract_linkback_anchor / sanitize_* /
# quarantine_corrupted_file / anchor gate 判定）逐字等价，差异仅为
# ruff 格式化与加性增强（INFRA-601 gh_repo_args、audit_layout P 档映射），
# 由 INFRA-679 PR 承载行为等价评审。
#
# 格式: "<仓库相对路径>:<部署目标文件名>"

CROSS_DIR_MAPPINGS=(
    "src/infra_core/engine/extract_anchor.py:extract_anchor.py"
    "src/infra_core/engine/evolution_utils.py:evolution_utils.py"
    "src/infra_core/engine/evolution_adapters.py:evolution_adapters.py"
    "src/infra_core/engine/anchor_gate.py:anchor_gate.py"
)

# ============================================================================
# 环境差异声明 (Environment-Specific Differences)
# ============================================================================
# 声明仓库副本与生产副本之间的已知环境特定差异
# 这些差异是预期的，不会导致同步失败
#
# 格式: "文件名:行号或模式:说明"
# 示例: "trigger-droid.sh:42:生产环境使用 /opt/homebrew/bin/python3"

ENV_DIFF_LINES=(
    # trigger-droid.sh 中的硬编码路径（macOS 特定）
    "trigger-droid.sh:硬编码路径:/Users/busiji/.factory/webhook - 生产环境基础路径"
    "trigger-droid.sh:硬编码路径:/opt/homebrew/bin/python3 - macOS Python 路径"
    "trigger-droid.sh:硬编码路径:/opt/homebrew/bin/flock - macOS flock 路径"
    "trigger-droid.sh:硬编码路径:/Users/busiji/.factory/config/repositories.yml - 仓库配置路径"

    # reconcile-evolution.sh 中的硬编码路径
    "reconcile-evolution.sh:硬编码路径:/Users/busiji/.factory/webhook - 生产环境基础路径"
    "reconcile-evolution.sh:硬编码路径:/opt/homebrew/bin/python3 - macOS Python 路径"

    # local_branch_cleanup.sh 中的硬编码路径（TD-BR-01）
    "local_branch_cleanup.sh:硬编码路径:$HOME/.factory/webhook/locks/branch_cleanup_backup - 备份目录"
    "local_branch_cleanup.sh:硬编码路径:PostHog API endpoint - 事件上报端点"

    # 权限差异（生产脚本可能需要特定权限位）
    "trigger-droid.sh:权限:生产环境可能需要可执行权限"
    "reconcile-evolution.sh:权限:生产环境可能需要可执行权限"
    "local_branch_cleanup.sh:权限:生产环境可能需要可执行权限"

    # Shellcheck 指令差异（仓库侧添加以通过 CI 门禁）
    "trigger-droid.sh:shellcheck指令:仓库侧添加 disable=SC1091,SC2317,SC2054,SC2155 指令以通过 CI 静态分析"
)

# ============================================================================
# 辅助函数
# ============================================================================

# 获取受管文件列表
get_managed_files() {
    for file in "${MANAGED_FILES[@]}"; do
        echo "$file"
    done
}

# 获取跨目录同步映射列表（INFRA-357 锚点依赖链）
get_cross_dir_mappings() {
    for mapping in "${CROSS_DIR_MAPPINGS[@]}"; do
        echo "$mapping"
    done
}

# 检查文件是否在受管清单中
is_managed_file() {
    local file="$1"
    # 检查主脚本清单
    for managed in "${MANAGED_FILES[@]}"; do
        if [[ "$managed" == "$file" ]]; then
            return 0
        fi
    done
    # 检查 lib/ 子目录清单
    for managed in "${MANAGED_LIB_FILES[@]}"; do
        if [[ "$managed" == "$file" ]]; then
            return 0
        fi
    done
    return 1
}

# 获取文件的声明差异数量
get_declared_diff_count() {
    local file="$1"
    local count=0
    for diff_line in "${ENV_DIFF_LINES[@]}"; do
        if [[ "$diff_line" == "$file:"* ]]; then
            ((count++))
        fi
    done
    echo "$count"
}
