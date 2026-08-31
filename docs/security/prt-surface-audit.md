# pull_request_target 安全面审计（PRT Surface Audit）

> **范围**：4 个 `pull_request_target` / `workflow_run` 面的 workflow
> **基线**：2026-08-31（F5 bash 加固 + 权限最小化完成后）
> **威胁模型**：公开仓 + self-hosted runner (pve-linux) + fork PR
>
> `pull_request_target` / `workflow_run` 触发的 workflow 不受 fork PR 审批门禁
> (`all_external_contributors`) 约束——base 被视为 trusted，外部贡献者的 PR 代码
> 不会自动执行。但任何 **checkout PR head + 执行 PR 代码** 的组合都是毒丸入口。
> 本审计是这类 workflow 的唯一真实防线。

---

## 审计面 1：droid-review.yml（自仓 Droid Auto Review）

### 轴 1：checkout PR head + 执行链与 workspace guard 覆盖

**执行链**：
```
setup → plan-shards → review-shard (并行矩阵) → droid-review (聚合)
```

**checkout 配置**：
- `review-shard` job 执行 **双 checkout**：
  1. `Checkout repository (BASE)` — `ref: ${{ needs.setup.outputs.base_sha }}`（可信源：main 分支）
  2. `Checkout PR head (HEAD → head-src/)` — `ref: ${{ needs.setup.outputs.head_sha }}`（**不可信源：PR 代码**）

**workspace guard 覆盖**：
- **第一次 checkout 前**：Workspace guard (sparse residue detox) — 检测 sparse-checkout 残留并清除
- **第二次 checkout 前**：Workspace guard (sparse residue detox) — 再次检测
- guard 逻辑：`rm -rf "$GITHUB_WORKSPACE/.git"`（强制全新克隆）

**执行内容**：
- `setup-venv` 使用 BASE checkout 的 `.github/actions/setup-venv`（可信）
- `run_shard.sh` 从 BASE checkout 的 `scripts/droid_review/` 执行（可信）
- **PR 代码仅作为 diff 素材被读取**（`head-src/` 目录），不被直接执行

**风险等级**：**低**
- 双 checkout 隔离设计正确：脚本/prompt 从 BASE 取（可信），PR 代码仅作为上下文素材
- workspace guard 在每次 checkout 前执行，防护 sparse-checkout 残留污染
- PR 代码不直接执行（仅 `cat`/`grep` 等读取操作）

### 轴 2：GITHUB_TOKEN / secrets 暴露面

**凭证使用**：
- `GITHUB_TOKEN`（自动注入）：用于 `gh pr view`/`gh api` 读取 PR 信息、上传 artifact
- `FACTORY_API_KEY`：BYOM 调用 Kong 代理（非 PR 代码可见）
- `NVIDIA_KONG_PROXY_KEY`：BYOM 链路认证（非 PR 代码可见）

**暴露面分析**：
- `GITHUB_TOKEN` 权限：`contents: read` + `actions: write`（upload-artifact）+ `pull-requests: read`
- PR 代码（`head-src/`）**无法访问环境变量**（GitHub Actions 隔离）
- `run_shard.sh` 从 BASE 执行，PR 代码仅通过 `cat`/`jq` 读取，**无命令注入路径**

**PAT 盲区**：
- 本 workflow **不使用 DISPATCH_TOKEN**（PAT），仅用 `GITHUB_TOKEN`
- 即使 PR 代码存在注入漏洞，攻击者无法获取 PAT 权限（PAT 不在本 workflow 暴露）

**风险等级**：**低**
- 凭证最小化：仅 `GITHUB_TOKEN`，权限已收紧至只读 + artifact 写入
- PR 代码无法访问 secrets（GitHub Actions 运行时隔离）
- 无 PAT 暴露面（DISPATCH_TOKEN 仅在 auto-merge 系使用）

### 轴 3：artifact 投毒面

**artifact 生产**：
- `upload-artifact` 上传 `.factory/sessions/*.json`（Factory 审查会话 transcript）
- artifact 名：`droid-review-debug-{run_id}-{shard_id}`

**跨 job 消费**：
- `droid-review` (聚合) job 通过 `download-artifact` 下载所有 shard 的 findings
- findings 文件：`findings-shard-*.json`（JSON 格式，由 `publish_findings.py` 解析）

**投毒路径**：
- 攻击者需控制 `run_shard.sh` 输出（但脚本从 BASE checkout，PR 代码无法修改）
- findings JSON 由脚本生成，非 PR 代码直接写入
- 聚合 job 通过 `jq` 解析 JSON，无命令注入风险（JSON 仅作为数据读取）

**风险等级**：**低**
- artifact 内容受脚本控制，PR 代码无法直接写入
- JSON 解析使用 `jq`（安全解析，无命令注入）
- artifact 仅用于调试，不影响合并决策（合并决策基于 check-runs API）

---

## 审计面 2：droid-review-shards.yml（reusable workflow 版）

### 轴 1：checkout PR head + 执行链与 workspace guard 覆盖

**执行链**：
```
setup → plan-shards → review-shard (并行矩阵)
```

**与自仓版的差异**：
- 本 workflow 是 **reusable workflow**，被 memory-core 等消费仓调用
- checkout 配置与自仓版 **完全相同**（双 checkout：BASE + HEAD）
- workspace guard 在每次 checkout 前执行（逻辑相同）

**执行内容**：
- 引擎脚本从 `engine_ref`（默认 `main`）checkout（**可信源**：infra-core 仓）
- PR 代码仅作为 diff 素材读取（`head-src/` 目录）

**风险等级**：**低**
- 与自仓版同构：双 checkout 隔离 + workspace guard + 引擎脚本可信源
- 消费仓无法篡改引擎脚本（`engine_ref` 指向 infra-core 仓，非消费仓）

### 轴 2：GITHUB_TOKEN / secrets 暴露面

**凭证使用**：
- `GITHUB_TOKEN`（自动注入）：读取 PR 信息、上传 artifact
- `FACTORY_API_KEY`：BYOM 调用（非 PR 代码可见）

**暴露面分析**：
- 权限：`contents: read` + `actions: write`（与自仓版相同）
- reusable workflow **不继承 caller 的 secrets**（GitHub 隔离）
- caller 需显式传入 `dispatch-token`（本 workflow 不使用，仅 auto-merge 系需要）

**风险等级**：**低**
- 凭证最小化 + reusable workflow 隔离
- PR 代码无法访问 secrets

### 轴 3：artifact 投毒面

**与自仓版相同**：
- artifact 生产：`.factory/sessions/*.json`（transcript）
- 跨 workflow 消费：caller（memory-core）通过 `download-artifact` 获取 findings

**投毒路径**：
- 同自仓版：artifact 由脚本生成，PR 代码无法直接写入
- caller 通过 `jq` 解析 JSON，无命令注入风险

**风险等级**：**低**
- 与自仓版同构：artifact 受脚本控制，JSON 解析安全

---

## 审计面 3：evolution-governance.yml（Evolution Governance）

### 轴 1：checkout PR head + 执行链与 workspace guard 覆盖

**执行链**：
```
governance (单 job) → uses: hdot123-org/infra-core/actions/governance-check@SHA
```

**checkout 配置**：
- **无 checkout**（零工作区足迹）
- 使用 composite action `governance-check`（从 SHA 锁定版本加载）

**workspace guard 覆盖**：
- 无需 workspace guard（无 checkout = 无工作区污染风险）

**执行内容**：
- composite action 从 GitHub 服务端下载（SHA 锁定，不可篡改）
- action 内部通过 `gh api` 读取 PR diff（**仅读取，不执行 PR 代码**）
- 检查 `.evolution/` 目录变更是否符合治理规则

**风险等级**：**极低**
- 无 checkout = 零工作区足迹
- PR 代码不执行（仅通过 API 读取 diff）
- composite action SHA 锁定，不可篡改

### 轴 2：GITHUB_TOKEN / secrets 暴露面

**凭证使用**：
- `GITHUB_TOKEN`（自动注入）：`gh api` 读取 PR 信息
- 权限：`contents: read` + `pull-requests: read`（只读）

**暴露面分析**：
- composite action 仅读取 PR diff，**不写入任何资源**
- PR 代码无法访问环境变量（GitHub Actions 隔离）

**风险等级**：**极低**
- 凭证最小化：仅只读权限
- 无 PAT 暴露面

### 轴 3：artifact 投毒面

**无 artifact**：
- 本 workflow 不生产/消费 artifact

**风险等级**：**无**
- 无 artifact = 无投毒面

---

## 审计面 4：auto-merge 系（auto-merge.yml + auto-merge-pipeline.yml）

### 轴 1：checkout PR head + 执行链与 workspace guard 覆盖

**执行链**：
```
resolve → triage → auto-merge (composite action)
```

**checkout 配置**：
- **无 checkout**（防毒铁律：auto-merge job 严禁 `actions/checkout`）
- 使用 composite action `auto-merge`（SHA 锁定）

**workspace guard 覆盖**：
- `auto-merge` job 首步：Workspace guard (sparse residue detox)
- guard 逻辑：检测 sparse-checkout 残留并清除（`rm -rf "$GITHUB_WORKSPACE/.git"`）

**执行内容**：
- triage 脚本通过 heredoc 内联到 `RUNNER_TEMP`（每 run 独立临时目录）
- triage 脚本与 `src/infra_core/shell/auto_merge_triage.sh` 字节一致（契约测试锁定）
- composite action 从 SHA 锁定版本加载（不可篡改）

**风险等级**：**极低**
- 无 checkout = 零工作区足迹
- triage 脚本从 heredoc 生成（可信源：main 分支的 workflow 文件）
- workspace guard 防护 sparse-checkout 残留污染

### 轴 2：GITHUB_TOKEN / secrets 暴露面

**凭证使用**：
- **DISPATCH_TOKEN（PAT）**：用于 `gh pr merge`（合并 PR）
- 权限：PAT owner=hdot123（OWNER），具备完整仓库权限

**暴露面分析**：
- PAT 通过 `env: GITHUB_TOKEN: ${{ secrets.DISPATCH_TOKEN }}` 注入
- composite action 内部使用 `gh pr merge`（**命令执行，非 PR 代码**）
- PR 代码无法访问环境变量（GitHub Actions 隔离）

**PAT 盲区**：
- **DISPATCH_TOKEN 是 PAT，权限不受 `permissions:` 块约束**（结构性盲区）
- 即使 `permissions: contents: write`，PAT 实际权限由 GitHub 用户权限决定
- 最小化措施：PAT owner=hdot123（单一用户），权限范围可控

**风险等级**：**中**
- PAT 暴露面存在（结构性盲区，无法通过 `permissions:` 收紧）
- 缓解措施：PAT 仅用于 `gh pr merge`（单一命令），composite action SHA 锁定
- PR 代码无法直接访问 PAT（GitHub Actions 运行时隔离）

### 轴 3：artifact 投毒面

**无 artifact**：
- auto-merge 系不生产/消费 artifact

**风险等级**：**无**
- 无 artifact = 无投毒面

---

## 风险等级汇总

| 审计面 | 轴 1：checkout + guard | 轴 2：凭证暴露 | 轴 3：artifact 投毒 |
|---|---|---|---|
| droid-review | 低（双 checkout 隔离 + guard） | 低（GITHUB_TOKEN 最小化） | 低（脚本控制 + jq 解析） |
| droid-review-shards | 低（同自仓版） | 低（同自仓版） | 低（同自仓版） |
| evolution-governance | 极低（无 checkout） | 极低（只读权限） | 无（无 artifact） |
| auto-merge 系 | 极低（无 checkout + guard） | **中**（PAT 暴露面） | 无（无 artifact） |

---

## 低风险修复（本 PR 落地）

### 修复 1：bash 容错统一（VAL-M2-201）

**问题**：多行 `run:` 块缺少 `set -euo pipefail`，导致错误被静默吞掉

**修复**：
- 升级 33 处 `set -eu` → `set -euo pipefail`
- 补齐 41 处无 `set` 的多行 run 块
- 保留显式降级（`|| true`、`|| code=$?`、`continue-on-error`、局部 `set +e`）

**影响面**：
- `.github/workflows/`：ci.yml、qa.yml、droid-review.yml、droid-review-shards.yml、auto-merge.yml、auto-merge-pipeline.yml、evolution-heartbeat.yml、evolution-scan.yml、droid-review-watchdog.yml、droid-review-watchdog-handlers.yml
- `actions/`：auto-merge/action.yml、branch-cleanup/action.yml、droid-review-aggregate/action.yml、governance-check/action.yml

**风险**：**低**
- 升级是防御性加固（显式失败 > 静默吞错）
- 保留显式降级（有意降级合法）

### 修复 2：auto-merge 静默假绿修复（VAL-M2-202）

**问题**：`gh pr merge` 失败后 `else echo "Merge command failed..."` 静默继续（退出 0）

**修复**：
```bash
if gh pr merge "$PR_NUMBER" --repo "$REPO" --squash --delete-branch 2>&1; then
  echo "PR #$PR_NUMBER merged successfully."
else
  # Merge failed — check if it's a race condition (PR already merged)
  echo "Merge command failed. Checking PR state..."
  CURRENT_STATE=$(gh pr view "$PR_NUMBER" --repo "$REPO" --json state --jq '.state' 2>/dev/null || echo "UNKNOWN")
  if [ "$CURRENT_STATE" = "MERGED" ]; then
    echo "PR already merged (race condition). Treating as success."
    exit 0
  else
    echo "PR state is $CURRENT_STATE. Merge failed for non-race reason."
    exit 1
  fi
fi
```

**降级例外**：仅当 `gh pr view` 确认 PR 已合并（竞态性降级）时允许成功退出

**风险**：**低**
- 显式失败 > 静默吞错
- 竞态性降级有日志说明

### 修复 3：actionlint fallback 下载网络加固（VAL-M2-204）

**问题**：actionlint fallback 下载的 `curl` 无重试/超时，网络波动导致 CI 红

**修复**：
```yaml
bash <(curl --retry 3 --max-time 60 https://raw.githubusercontent.com/.../download-actionlint.bash)
```

**风险**：**低**
- 防御性加固（网络韧性）

---

## 高风险项（移交编排器决策）

### 高风险 1：DISPATCH_TOKEN PAT 权限不受 `permissions:` 块约束

**问题**：
- `DISPATCH_TOKEN` 是 PAT，权限由 GitHub 用户权限决定，不受 workflow `permissions:` 块约束
- 即使声明 `permissions: contents: read`，PAT 实际权限仍为完整仓库权限

**影响面**：
- auto-merge.yml / auto-merge-pipeline.yml 使用 `DISPATCH_TOKEN` 执行 `gh pr merge`
- 若 PAT 被泄露，攻击者具备完整仓库权限

**建议**：
1. **短期**：PAT owner=hdot123（单一用户），权限范围可控；PAT 仅用于 `gh pr merge`（单一命令）
2. **中期**：评估是否可改用 GitHub App token（权限可精细控制）
3. **长期**：迁移到 GitHub Actions 的 OIDC 认证（零凭证泄露风险）

**风险等级**：**中**
- 结构性盲区，无法通过 `permissions:` 收紧
- 缓解措施：PAT 使用范围最小化（单一命令）

---

## 审计结论

### 总体风险等级：**低**

**理由**：
1. **droid-review 系**：双 checkout 隔离设计正确，PR 代码仅作为素材读取，不直接执行；workspace guard 防护工作区污染；凭证最小化（仅 `GITHUB_TOKEN`）
2. **evolution-governance**：无 checkout，零工作区足迹；仅读取 PR diff，不执行 PR 代码
3. **auto-merge 系**：无 checkout，triage 脚本从 heredoc 生成（可信源）；workspace guard 防护污染

**唯一中风险**：auto-merge 系使用 `DISPATCH_TOKEN`（PAT），权限不受 `permissions:` 块约束（结构性盲区）。缓解措施已到位（PAT 使用范围最小化），但长期需评估 GitHub App token 或 OIDC 迁移。

### 守护测试覆盖

本审计涉及的不变量已由以下契约测试锁定：
- `test_auto_merge_workflow_contract.py`：防毒契约（禁 checkout）+ triage heredoc 字节一致
- `test_auto_merge_pipeline_hardening.py`：workspace guard 覆盖
- `test_droid_review_watchdog_quota_sweep.py`：quota-sweep job 不可达状态锁定
- `test_ci_structure_contract.py`：workspace guard 在每个 checkout 前存在

### 建议后续行动

1. **本 PR 落地低风险修复**（bash 容错统一 + auto-merge 静默假绿修复 + actionlint 网络加固）
2. **PAT 权限评估**（中期）：评估 auto-merge 系是否可改用 GitHub App token
3. **PRT 审计定期复盘**（每 6 个月）：随着 workflow 演进，重新评估安全面
