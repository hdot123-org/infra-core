# Phase 4 遗留决策记录

本文档记录治理加固 mission 中发现的遗留项，**仅报告、不执行**。后续 mission 或独立 PR 处理。

---

## 1. linear-dashboard 退役引用

**发现位置**：`docs/architecture.md` §7 演进路线（M6 条目）

**现状**：
- `~/tool/shared-workflows` 目录存在多个 workflow 文件引用 `linear-dashboard` 仓库
- 这些引用指向已退役的 linear-dashboard 项目
- 当前引用状态：代码中存在但实际不可用（404）

**退役建议**：
1. **清理引用**：搜索并移除所有指向 linear-dashboard 的 workflow 引用
   ```bash
   # 查找所有引用
   grep -r "linear-dashboard" ~/tool/shared-workflows/
   ```
2. **替代方案**：
   - 如果这些 workflow 仍有价值，应迁移到 infra-core 或独立的 shared-workflows 仓库
   - 如果已废弃，直接从源文件删除
3. **优先级**：低（当前不影响 CI，仅文档/引用清理）

**相关 commit**：
- M6 条目（`docs/architecture.md`）已记录退役决策
- 本 mission 未执行清理（避免跨域改动）

---

## 2. ~/tool/shared-workflows 目录处置建议

**发现位置**：用户主目录 `~/tool/shared-workflows/`

**现状**：
- 目录包含多个 reusable workflow 文件
- 部分 workflow 已被 infra-core 的 `.github/workflows/` 吸收
- 部分 workflow 仍被外部仓库引用（如 memory-core）
- 目录本身不在 git 管理下（本地工具目录）

**处置建议**：

### 方案 A：正式化（推荐）
1. 将 `~/tool/shared-workflows/` 迁移到 Git 仓库管理
2. 建立独立仓库：`hdot123-org/shared-workflows`（或并入 infra-core）
3. 明确版本策略：
   - 使用 tag（如 `@v1.0.0`）而非 `@main`
   - 与 infra-core 版本解耦，独立发布
4. 更新所有引用方（memory-core 等）

### 方案 B：逐步吸收
1. 盘点现有 workflow：
   ```bash
   ls ~/tool/shared-workflows/
   ```
2. 对每个 workflow：
   - 如果已被 infra-core 吸收 → 删除本地副本，更新引用
   - 如果仍有独立价值 → 迁移到 infra-core 或独立仓库
   - 如果已废弃 → 直接删除
3. 最终清空 `~/tool/shared-workflows/` 目录

### 方案 C：维持现状（不推荐）
- 保持本地目录状态
- 风险：版本混乱、引用断裂、难以审计
- 仅适合个人实验环境

**优先级**：中（影响引用稳定性，但当前 CI 正常）

**决策人**：用户（需确认长期策略）

---

## 3. 未执行的原因

本 mission（治理加固）聚焦于：
1. **代码层**：SHA 锁定、权限最小化、bash 容错
2. **平台层**：Actions 策略、Rulesets 迁移

遗留项涉及：
- 跨仓库协调（linear-dashboard、memory-core）
- 本地工具目录治理（~/tool/shared-workflows）
- 文档清理（退役引用）

这些超出本 mission 范围，且需要用户决策（如 shared-workflows 的长期归属）。

**后续行动**：
- 用户阅读本文档后决定是否启动新 mission 或独立 PR
- 本 mission 仅完成记录义务，不执行变更

---

## 参考

- `docs/architecture.md` §7：M6 条目（linear-dashboard 退役）
- F7 守护测试：`tests/test_platform_governance_contract.py`
- F8 Rulesets 迁移：`main-branch-protection` ruleset (ID 21965084)
