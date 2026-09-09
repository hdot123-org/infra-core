# 3 主仓不一致修正方案

**对象**：hdot123-org 3 个主仓（infra-core / memory / mencbo）  
**性质**：修正方案（批准即执行，本 mission 不执行任何设置变更）  
**日期**：2026-09-09  
**上游产物**：治理规范 `org-governance-spec.md` + 分层变更 playbook `change-playbook.md` + 残余面模板 `templates/`

---

## 0. 概述

3 主仓存在 4 类不一致问题：
1. **mencbo 合并策略**：三种合并方式全开（merge commit / rebase / squash），未统一为 squash-only
2. **POSTHOG_INGESTION_KEY**：明文存于 mencbo Actions variables（应迁 secrets）
3. **分支保护机制**：memory / mencbo 用 classic protection，infra-core 用 rulesets
4. **checkout action 版本**：三仓 workflow 混用 v4 / v5（应统一 v7）

本方案逐仓独立成节，每节含五要素：**现状值 / 目标值 / 操作 / 验证 / 回滚**，无跨仓执行硬依赖。

---

## 1. infra-core

### 1.1 合并策略

| 要素 | 值 |
|---|---|
| **现状值** | `allow_squash_merge=true, allow_merge_commit=false, allow_rebase_merge=false, delete_branch_on_merge=true`（已统一为 squash-only） |
| **目标值** | 无需变更（已达标） |
| **操作** | 无 |
| **验证** | `gh api /repos/hdot123-org/infra-core --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge, delete_branch_on_merge}'`（应输出 squash=true, merge=false, rebase=false, delete=true） |
| **回滚** | 不适用 |

### 1.2 POSTHOG_INGESTION_KEY

| 要素 | 值 |
|---|---|
| **现状值** | infra-core 不使用 POSTHOG（无该变量/secret） |
| **目标值** | 无需变更 |
| **操作** | 无 |
| **验证** | `gh api /repos/hdot123-org/infra-core/actions/variables --jq '.variables[] | select(.name=="POSTHOG_INGESTION_KEY")'`（应返回空） |
| **回滚** | 不适用 |

### 1.3 分支保护 rulesets

| 要素 | 值 |
|---|---|
| **现状值** | 已使用 rulesets（`main-branch-protection`，enforcement=active，含 required_status_checks / required_linear_history / deletion / non_fast_forward / pull_request） |
| **目标值** | 无需变更（已达标） |
| **操作** | 无 |
| **验证** | `gh api /repos/hdot123-org/infra-core/rulesets --jq '.[].name'`（应输出 `main-branch-protection`） |
| **回滚** | 不适用 |

### 1.4 checkout action 版本

| 要素 | 值 |
|---|---|
| **现状值** | 部分 workflow 使用 `actions/checkout@v5-pin`（SHA: `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09`） |
| **目标值** | 统一为 `actions/checkout@<SHA>`（v7 最新 SHA） |
| **操作** | 1. 查询 checkout v7 最新 SHA：`gh api /repos/actions/checkout/releases/latest --jq '.tag_name'` 获取 tag，再从 commit 获取 SHA<br>2. 替换全部 `uses: actions/checkout@<old-sha>` 为 `uses: actions/checkout@<new-sha> # v7`<br>3. `git add .github/workflows/`<br>4. `git commit -m "chore: upgrade actions/checkout to v7"`<br>5. `git push` |
| **验证** | `grep -rn 'actions/checkout@' .github/workflows/ \| grep -vE '@[0-9a-f]{40}'`（应返回空）<br>`grep -rn 'actions/checkout@' .github/workflows/ \| grep '# v7'`（应全命中） |
| **回滚** | `git revert <commit-sha>`（回退 checkout 版本升级） |

**影响说明**：
- **对进行中 PR**：无影响（checkout 版本升级后行为不变）
- **对运行中 CI**：新 PR 触发 CI 时使用新版本 checkout
- **对引擎管线**：无影响（auto-merge / droid-review 等继续使用相同 action，仅版本变化）

---

## 2. memory

### 2.1 合并策略

| 要素 | 值 |
|---|---|
| **现状值** | `allow_squash_merge=true, allow_merge_commit=false, allow_rebase_merge=false, delete_branch_on_merge=true`（已统一为 squash-only） |
| **目标值** | 无需变更（已达标） |
| **操作** | 无 |
| **验证** | `gh api /repos/hdot123-org/memory --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge, delete_branch_on_merge}'`（应输出 squash=true, merge=false, rebase=false, delete=true） |
| **回滚** | 不适用 |

### 2.2 POSTHOG_INGESTION_KEY

| 要素 | 值 |
|---|---|
| **现状值** | memory 不使用 POSTHOG（无该变量/secret） |
| **目标值** | 无需变更 |
| **操作** | 无 |
| **验证** | `gh api /repos/hdot123-org/memory/actions/variables --jq '.variables[] | select(.name=="POSTHOG_INGESTION_KEY")'`（应返回空） |
| **回滚** | 不适用 |

### 2.3 分支保护 rulesets

| 要素 | 值 |
|---|---|
| **现状值** | 使用 classic branch protection（`main` 分支：required_status_checks=[ci-ok, Block non-owner governance modifications, droid-review]；enforce_admins=true；required_linear_history=true；allow_force_pushes=false；allow_deletions=false） |
| **目标值** | 迁移到 repo 级 rulesets（同构复制 infra-core 的 `main-branch-protection` 模板，适配 memory 的 CI check 名） |
| **操作** | 参见 playbook `change-playbook.md` **PB-13**<br><br>1. 复制模板：`cp docs/governance/templates/ruleset.json memory-ruleset.json`<br>2. 修改 `rules[0].parameters.required_status_checks[].context` 为 memory 的实际 check 名：<br>   - `ci-ok`<br>   - `Block non-owner governance modifications`<br>   - `droid-review`<br>3. 删除 `integration_id` 字段（按仓自适应）<br>4. 创建 ruleset：`gh api -X POST /repos/hdot123-org/memory/rulesets --input memory-ruleset.json`<br>5. 验证后删除 classic protection（UI：Settings > Branches > main > Delete）<br>6. `rm memory-ruleset.json` |
| **验证** | `gh api /repos/hdot123-org/memory/rulesets --jq '.[].name'`（应输出 `main-branch-protection`）<br>`gh api /repos/hdot123-org/memory/branches/main/protection`（应返回 404 "Branch not protected"——保护走 rulesets） |
| **回滚** | `gh api -X DELETE /repos/hdot123-org/memory/rulesets/<ID>`（删 ruleset）<br>classic protection 需手动重建（UI：Settings > Branches > Add rule） |

**影响说明**：
- **对进行中 PR**：无影响（ruleset 与 classic protection 语义一致）
- **对运行中 CI**：无影响
- **对引擎管线**：无影响

**org 覆盖不到论证**：org 级 rulesets 需 Team+（Free plan 不可用），只能 repo 级 rulesets（产物 A §8.1：`GET /orgs/hdot123-org/rulesets` → 403）。参见差距矩阵产物 C `LR-01`。

### 2.4 checkout action 版本

| 要素 | 值 |
|---|---|
| **现状值** | 部分 workflow 使用 `actions/checkout@v5-pin`（SHA pin 形式） |
| **目标值** | 统一为 `actions/checkout@<SHA>`（v7 最新 SHA） |
| **操作** | 同 infra-core 1.4 |
| **验证** | `gh api /repos/hdot123-org/memory/contents/.github/workflows --jq '.[].name'` 列出 workflow，逐个读取并 `grep 'actions/checkout@' \| grep -vE '@[0-9a-f]{40}'`（应返回空） |
| **回滚** | `git revert <commit-sha>` |

**影响说明**：同 infra-core 1.4

---

## 3. mencbo

### 3.1 合并策略

| 要素 | 值 |
|---|---|
| **现状值** | `allow_squash_merge=true, allow_merge_commit=true, allow_rebase_merge=true, delete_branch_on_merge=false`（三种合并方式全开） |
| **目标值** | `allow_squash_merge=true, allow_merge_commit=false, allow_rebase_merge=false, delete_branch_on_merge=true`（统一为 squash-only + 自动删分支） |
| **操作** | 参见 playbook `change-playbook.md` **PB-16**<br><br>1. 盘点当前 open PR：`gh pr list -R hdot123-org/mencbo --state open --json number,title,mergeable`<br>2. 执行变更：`gh api -X PATCH /repos/hdot123-org/mencbo -F allow_merge_commit=false -F allow_rebase_merge=false -F delete_branch_on_merge=true`<br>3. 通知 open PR 作者：合并方式仅剩 squash |
| **验证** | `gh api /repos/hdot123-org/mencbo --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge, delete_branch_on_merge}'`（应输出 squash=true, merge=false, rebase=false, delete=true） |
| **回滚** | `gh api -X PATCH /repos/hdot123-org/mencbo -F allow_merge_commit=true -F allow_rebase_merge=true -F delete_branch_on_merge=false` |

**影响说明**：
- **对进行中 PR**：合并方式选项变化（仅剩 squash），待合并 PR 需确认合并按钮行为
- **对运行中 CI**：无影响
- **对引擎管线**：无影响（mencbo 无引擎管线）

**org 覆盖不到论证**：合并策略为 repo 级设置（`PATCH /repos/{owner}/{repo}`），org 级无统一端点（org 级 rulesets 可覆盖但需 Team——产物 A §8.1）。参见差距矩阵产物 C `LR-04`。

### 3.2 POSTHOG_INGESTION_KEY

| 要素 | 值 |
|---|---|
| **现状值** | `POSTHOG_INGESTION_KEY` 明文存于 mencbo Actions variables（13 个 variables 之一） |
| **目标值** | 迁移到 mencbo Actions secrets |
| **操作** | 参见 playbook `change-playbook.md` **PB-15**<br><br>**并行期四步设计**：<br>1. **建 secret**：`gh secret set POSTHOG_INGESTION_KEY --repo hdot123-org/mencbo --body "<VALUE>"`（从 variables 读取当前值）<br>2. **改 workflow 引用**：mencbo 仓内 workflow 文件中 `${{ variables.POSTHOG_INGESTION_KEY }}` → `${{ secrets.POSTHOG_INGESTION_KEY }}`<br>3. **验证**：`gh api /repos/hdot123-org/mencbo/actions/secrets --jq '.secrets[] \| select(.name=="POSTHOG_INGESTION_KEY")'`（应返回存在）<br>4. **末步删 variable**：`gh api -X DELETE /repos/hdot123-org/mencbo/actions/variables/POSTHOG_INGESTION_KEY` |
| **验证** | `gh api /repos/hdot123-org/mencbo/actions/secrets --jq '.secrets[] \| select(.name=="POSTHOG_INGESTION_KEY")'`（应返回存在）<br>`gh api /repos/hdot123-org/mencbo/actions/variables --jq '.variables[] \| select(.name=="POSTHOG_INGESTION_KEY")'`（应返回空） |
| **回滚** | 并行期内：改回读 variables（`variables.POSTHOG_INGESTION_KEY`）<br>并行期结束后：`gh api -X DELETE /repos/hdot123-org/mencbo/actions/secrets/POSTHOG_INGESTION_KEY` + 重新创建 variable |

**影响说明**：
- **对进行中 PR**：无影响
- **对运行中 CI**：并行期内若 workflow 仍读 variables 会失败（需并行期过渡）
- **对引擎管线**：无影响（mencbo 无引擎管线）

**org 覆盖不到论证**：repo 级 secrets/variables 无法由 org 级规则自动迁移（产物 A §5.1/5.2：org 级只能集中，不能自动迁移 repo 级存量值）。参见差距矩阵产物 C `LR-03`。

### 3.3 分支保护 rulesets

| 要素 | 值 |
|---|---|
| **现状值** | 使用 classic branch protection（`main` 分支：required_status_checks=[Test (Node 22/24), Test (Daemon), Block non-owner governance modifications, droid-review, Desktop / Detect, Desktop / Client, Desktop / Tauri]；enforce_admins=true；required_linear_history=false；allow_force_pushes=false；allow_deletions=false） |
| **目标值** | 迁移到 repo 级 rulesets（同构复制 infra-core 的 `main-branch-protection` 模板，适配 mencbo 的 CI check 名） |
| **操作** | 参见 playbook `change-playbook.md` **PB-13**<br><br>1. 复制模板：`cp docs/governance/templates/ruleset.json mencbo-ruleset.json`<br>2. 修改 `rules[0].parameters.required_status_checks[].context` 为 mencbo 的实际 check 名：<br>   - `Test (Node 22/24)`<br>   - `Test (Daemon)`<br>   - `Block non-owner governance modifications`<br>   - `droid-review`<br>   - `Desktop / Detect`<br>   - `Desktop / Client`<br>   - `Desktop / Tauri`<br>3. 删除 `integration_id` 字段（按仓自适应）<br>4. 创建 ruleset：`gh api -X POST /repos/hdot123-org/mencbo/rulesets --input mencbo-ruleset.json`<br>5. 验证后删除 classic protection（UI：Settings > Branches > main > Delete）<br>6. `rm mencbo-ruleset.json` |
| **验证** | `gh api /repos/hdot123-org/mencbo/rulesets --jq '.[].name'`（应输出 `main-branch-protection`）<br>`gh api /repos/hdot123-org/mencbo/branches/main/protection`（应返回 404 "Branch not protected"——保护走 rulesets） |
| **回滚** | `gh api -X DELETE /repos/hdot123-org/mencbo/rulesets/<ID>`（删 ruleset）<br>classic protection 需手动重建（UI：Settings > Branches > Add rule） |

**影响说明**：同 memory 2.3

**org 覆盖不到论证**：同 memory 2.3

### 3.4 checkout action 版本

| 要素 | 值 |
|---|---|
| **现状值** | 部分 workflow 使用 `actions/checkout@v5-pin`（SHA pin 形式） |
| **目标值** | 统一为 `actions/checkout@<SHA>`（v7 最新 SHA） |
| **操作** | 同 infra-core 1.4 |
| **验证** | `gh api /repos/hdot123-org/mencbo/contents/.github/workflows --jq '.[].name'` 列出 workflow，逐个读取并 `grep 'actions/checkout@' \| grep -vE '@[0-9a-f]{40}'`（应返回空） |
| **回滚** | `git revert <commit-sha>` |

**影响说明**：同 infra-core 1.4

---

## 4. checkout v7 升级清单（三仓全覆盖）

### 4.1 infra-core 使用 `pull_request_target` 的 workflow（基线 7 个）

1. `auto-merge.yml`
2. `auto-merge-pipeline.yml`
3. `droid-review.yml`
4. `droid-review-shards.yml`
5. `droid-review-watchdog.yml`
6. `droid-review-watchdog-handlers.yml`
7. `evolution-governance.yml`

### 4.2 memory 使用 `pull_request_target` 的 workflow

1. `auto-merge.yml`
2. `droid-review-watchdog.yml`
3. `droid-review.yml`
4. `evolution-governance.yml`
5. `ci.yml`（仅注释提及 pull_request_target，按注释含括政策计入）

### 4.3 mencbo 使用 `pull_request_target` 的 workflow

1. `auto-merge.yml`
2. `droid-review-watchdog.yml`
3. `droid-review.yml`
4. `evolution-governance.yml`

**验证方法**：
```bash
# infra-core（本地）
grep -rln 'pull_request_target' .github/workflows/

# memory / mencbo（远端）
gh api repos/hdot123-org/<repo>/contents/.github/workflows --jq '.[].name' | while read f; do
  gh api "repos/hdot123-org/<repo>/contents/.github/workflows/$f" --jq '.content' | base64 -d | grep -q 'pull_request_target' && echo "$f"
done
```

---

## 5. 交叉引用索引

| 整改项 | Playbook 条目 | 模板文件 | 差距矩阵条目 |
|---|---|---|---|
| mencbo 合并策略 | `change-playbook.md` **PB-16** | — | 产物 C `LR-04` |
| POSTHOG 迁移 | `change-playbook.md` **PB-15** | — | 产物 C `LR-03` |
| memory/mencbo rulesets 化 | `change-playbook.md` **PB-13** | `templates/ruleset.json` | 产物 C `LR-01` |
| checkout v7 升级 | — | — | — |

---

## 6. 现状陈述与审计矩阵一致性

本方案现状陈述与 `memory/artifacts/2026-09-09-org-state-audit.md` 第 2 节矩阵一致：

| 数据点 | 本方案陈述 | 审计矩阵行 |
|---|---|---|
| mencbo allow_merge_commit | `true` | `allow_merge_commit \| false \| false \| **true**` |
| mencbo allow_rebase_merge | `true` | `allow_rebase_merge \| false \| false \| **true**` |
| mencbo delete_branch_on_merge | `false` | `delete_branch_on_merge \| true \| true \| **false**` |
| mencbo required_linear_history | `false` | `required_linear_history \| true（ruleset）\| true \| **false**` |
| POSTHOG_INGESTION_KEY 位置 | mencbo Actions variables（明文） | `repo Actions variables \| 7 个 \| 12 个 \| 13 个（**POSTHOG_INGESTION_KEY（明文变量，非 secret）**）` |
| 分支保护模型 | infra-core=rulesets / memory=mencbo=classic | `分支保护模型 \| **Rulesets**（1 条 active）\| **Classic protection** \| **Classic protection**` |
| CODEOWNERS/dependabot.yml | 仅 memory 有 | `CODEOWNERS \| **不存在** \| **.github/CODEOWNERS ✓** \| **不存在**` |

---

## 7. 公开仓铁律

本文档落入公开仓 infra-core，必须满足：
- **无本地绝对路径**
- **无 secret 值**（POSTHOG_INGESTION_KEY 等只允许出现键名，值用 `<VALUE>` 占位符）

---

## 8. 参考索引

- 治理规范：`org-governance-spec.md`
- 分层变更 playbook：`change-playbook.md`
- 残余面模板：`templates/`（ruleset.json / CODEOWNERS / dependabot.yml）
- 差距矩阵：`memory/artifacts/2026-09-09-gap-matrix-org-first.md`（产物 C）
- 能力普查：`memory/artifacts/2026-09-09-org-capability-census.md`
- 现状审计：`memory/artifacts/2026-09-09-org-state-audit.md`

---

**修正方案完**
