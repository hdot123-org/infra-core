# Phase 4 遗留决策记录

本文档记录治理加固 mission 中发现的遗留项，**仅报告、不执行**。后续 mission 或独立 PR 处理。

---

## 1. linear-dashboard 退役引用

**发现位置**：`docs/architecture.md` §7 演进路线（M6 条目）

**现状**：
- `linear-dashboard` 仓库引用了 `~/tool/shared-workflows` 的 workflow（依赖方向：linear-dashboard → shared-workflows@main，未钉版本）
- 这些引用指向未版本控制的本地工具目录
- 当前引用状态：`linear-dashboard` 依赖 `shared-workflows@main`（浮动引用，未钉 tag/SHA）

**退役建议**：
1. **澄清依赖方向**：原清理建议 #1（搜索 shared-workflows 中对 linear-dashboard 的引用）是 no-op，因为实际依赖方向是反向的
2. **正确清理方向**：
   - 搜索并钉住 `linear-dashboard` 中对 `shared-workflows` 的浮动引用
   - 如果 `linear-dashboard` 仍有价值，应将 `shared-workflows@main` 钉到具体版本
   - 如果已废弃，整个 `linear-dashboard` 仓库可归档
3. **优先级**：低（当前不影响 CI，仅引用治理）

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
