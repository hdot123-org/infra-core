# GitHub Org 分层变更 Playbook — hdot123-org

**对象**：github.com/hdot123-org（Free plan，9 仓库，1 成员，5 台 self-hosted Linux runners）
**性质**：逐项变更 playbook（批准即执行，本 mission 不执行任何设置变更）
**日期**：2026-09-09
**上游产物**：治理规范 `org-governance-spec.md` + 差距矩阵 `2026-09-09-gap-matrix-org-first.md`（产物 C）

---

## 0. 结构与约定

### 0.1 分层结构

| 层 | 覆盖范围 | 内容 | 变更项数 |
|---|---|---|---|
| **Layer 1：org 级最大化** | 全部 9 仓库自动继承 | 普查 §7.1 第 1–9 组 org 级 API 命令（Batch A 预备 PB-00/PB-00.5 + Batch B Actions 策略 PB-01~PB-06.5 + Batch C 安全默认 PB-07~PB-09 + Batch D 成员特权 PB-10~PB-11 + Batch E runner 治理 PB-12） | 16 项 |
| **Layer 2：残余面最小集** | 仅 3 主仓 | org 规则在 Free plan 覆盖不到的仓库级变更（Batch F PB-13~PB-17） | 5 项 |
| **Layer 3：仅 UI 层** | 全部 9 仓库自动继承 | 普查 §7.2 仅 UI 可配项（Batch G PB-18~PB-20） | 3 项 |

**升级 Team 评估**：独立章节（不在此 playbook 执行）。secret_scanning / secret_scanning_push_protection 的 org 级 enable_all 端点不在普查 §7.1 十组白名单内（census §7.3 标记为 Free 不可用/需 Team），已迁移至「升级 Team 评估」章节。

### 0.2 每个变更项八要素

每个变更项包含：
1. **编号**（PB-xx）
2. **现状 → 目标**（当前值与目标值成对出现）
3. **免费可用性**（Free 可用/受限/不可用）
4. **API 或 UI**（执行通道）
5. **前置条件**（依赖项或准备工作）
6. **爆炸半径**（影响范围，含对进行中 PR/CI/引擎管线影响）
7. **回滚命令**（同端点反向命令，参数回现状值）
8. **验证命令**（全只读）

### 0.3 顺序安全不变式

**两条依赖不变式**：
- **(A)** 全量 workflow SHA 化预备项（PB-00）先于 sha_pinning_required 开启项（PB-03）
- **(B)** 在用第三方 action 盘点项（PB-00.5）先于 allowlist 收紧项（PB-01/PB-02）

### 0.4 分批策略

**批次单调递增**，每项可独立批准-执行-验证-回滚：
- **Batch A（预备）**：PB-00, PB-00.5（SHA 化 + 盘点，无副作用）
- **Batch B（Actions 策略）**：PB-01 ~ PB-06.5（org 级 Actions 收紧）
- **Batch C（安全默认）**：PB-07 ~ PB-09（enable_all 族）
- **Batch D（成员特权）**：PB-10 ~ PB-11（PATCH /orgs 族）
- **Batch E（runner 治理）**：PB-12（runner-groups）
- **Batch F（残余面）**：PB-13 ~ PB-17（Layer 2 仓库级变更）
- **Batch G（仅 UI）**：PB-18 ~ PB-20（Layer 3 人工操作）

---

## Batch A：预备项（无副作用）

### PB-00：全量 workflow SHA 化

| 要素 | 值 |
|---|---|
| ①编号 | PB-00 |
| ②现状→目标 | 3 主仓全部 workflow 的第三方 action 引用从浮动 tag（`@v1`/`@v2`）改为 full-length commit SHA（40 位 hex） |
| ③免费可用性 | 可用（workflow 层改动，无 plan 限制） |
| ④API 或 UI | 仓库内容文件（git commit + push）——infra-core 已完成，memory/mencbo 待做 |
| ⑤前置条件 | 无（纯预备项） |
| ⑥爆炸半径 | 对进行中 PR 无影响（SHA 化后 workflow 行为不变）；对运行中 CI 无影响（同一 commit SHA）；对引擎管线无影响（auto-merge/droid-review/release-please 等 bot 流程继续使用相同 action，仅引用方式变化） |
| ⑦回滚命令 | 无（SHA 化是单向改进，回滚 = 改回浮动 tag，但无必要） |
| ⑧验证命令 | `grep -rnE 'uses:.*@[a-f0-9]{40}' .github/workflows/`（infra-core 应全命中）；`grep -rnE 'uses:.*@v[0-9]' .github/workflows/`（应为 0 命中） |

**备注**：infra-core 已完成（`.github/` 与 `actions/` 下浮动 tag 引用数 = 0）；memory/mencbo 需执行。

### PB-00.5：在用第三方 action 盘点

| 要素 | 值 |
|---|---|
| ①编号 | PB-00.5 |
| ②现状→目标 | 产出在用第三方 action 清单（owner/repo@version 形式），作为 allowlist 候选 |
| ③免费可用性 | 可用（只读盘点） |
| ④API 或 UI | 仓库内容文件（grep workflow 文件） |
| ⑤前置条件 | 无 |
| ⑥爆炸半径 | 无（纯只读盘点） |
| ⑦回滚命令 | 无（产出清单文件，无需回滚） |
| ⑧验证命令 | `grep -rhEo 'uses: [^ ]+' .github/workflows/ \| sort -u`（输出 action 清单） |

**备注**：参考 infra-core 仓库级现有 allowlist（github_owned + `hdot123-org/infra-core/**` + `googleapis/*`）。

---

## Batch B：Actions 策略（org 级）

### PB-01：allowed_actions 收紧为 selected

| 要素 | 值 |
|---|---|
| ①编号 | PB-01 |
| ②现状→目标 | `allowed_actions: "all"` → `allowed_actions: "selected"` |
| ③免费可用性 | 可用（2026-02-05 起 Free 解锁 allowlist） |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions`（`allowed_actions: "selected"`） |
| ⑤前置条件 | PB-00.5（action 盘点）完成 |
| ⑥爆炸半径 | **对进行中 PR**：无影响（PR 已触发的 workflow 继续运行）；**对运行中 CI**：新 PR 触发时若引用未在 allowlist 的 action 会失败；**对引擎管线**：auto-merge/droid-review/release-please 等 bot 流程需确认其引用的 action 在 allowlist（infra-core 仓库级已收紧，已验证可行） |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions -f allowed_actions=all` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions --jq '.allowed_actions'`（应输出 `selected`） |

### PB-02：selected-actions 配置 allowlist 内容

| 要素 | 值 |
|---|---|
| ①编号 | PB-02 |
| ②现状→目标 | 未配置（409 语义）→ `github_owned_allowed=true, verified_allowed=true, patterns_allowed=[actions/*, googleapis/*, hdot123-org/infra-core/**]` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/selected-actions` |
| ⑤前置条件 | PB-00.5（action 盘点）完成 |
| ⑥爆炸半径 | 同 PB-01（allowlist 内容与 allowed_actions 同步生效） |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions/selected-actions -F github_owned_allowed=false -F verified_allowed=false`（清空 allowlist，配合 PB-01 回滚） |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/selected-actions --jq '{github_owned_allowed, verified_allowed, patterns_allowed}'` |

### PB-03：sha_pinning_required 开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-03 |
| ②现状→目标 | `sha_pinning_required: false` → `sha_pinning_required: true` |
| ③免费可用性 | 可用（2025-08-15 上线） |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions`（`sha_pinning_required: true`） |
| ⑤前置条件 | **PB-00（全量 SHA 化）完成**——否则所有 workflow 会因浮动 tag 引用失败 |
| ⑥爆炸半径 | **对进行中 PR**：无影响（已触发的 workflow 继续运行）；**对运行中 CI**：新 PR 触发时若 action 引用非 SHA 形式会失败；**对引擎管线**：infra-core 已完成 SHA 化，memory/mencbo 需先完成 PB-00 |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions -F sha_pinning_required=false` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions --jq '.sha_pinning_required'`（应输出 `true`） |

### PB-04：default_workflow_permissions 改为 read

| 要素 | 值 |
|---|---|
| ①编号 | PB-04 |
| ②现状→目标 | `default_workflow_permissions: "write"` → `default_workflow_permissions: "read"` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/workflow`（`default_workflow_permissions: "read"`） |
| ⑤前置条件 | 审查引擎层 18 个 workflow 中依赖 write 权限的 job（如 auto-merge、branch-cleanup、release-please），确认是否需要显式 `permissions: write` 声明 |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：新 workflow run 的 GITHUB_TOKEN 默认权限变为 read，需显式 `permissions: write` 的 job 会失败（如 auto-merge 需要 write 权限合并 PR）；**对引擎管线**：auto-merge/branch-cleanup/release-please 需在 workflow 文件中显式声明 `permissions: write`（当前 infra-core 已有显式 permissions，memory/mencbo 需检查） |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions/workflow -f default_workflow_permissions=write` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/workflow --jq '.default_workflow_permissions'`（应输出 `read`） |

### PB-05：can_approve_pull_request_reviews 关闭

| 要素 | 值 |
|---|---|
| ①编号 | PB-05 |
| ②现状→目标 | `can_approve_pull_request_reviews: true` → `can_approve_pull_request_reviews: false` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/workflow`（`can_approve_pull_request_reviews: false`） |
| ⑤前置条件 | 确认无 workflow 依赖「批准 PR」功能（当前 droid-review 使用 GITHUB_TOKEN 做 review 但非 approval） |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：workflow 无法再自动批准 PR（防 workflow 自批）；**对引擎管线**：droid-review 提交 review 但不批准，无影响 |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions/workflow -F can_approve_pull_request_reviews=true` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/workflow --jq '.can_approve_pull_request_reviews'`（应输出 `false`） |

### PB-06：fork-pr-contributor-approval 收紧

| 要素 | 值 |
|---|---|
| ①编号 | PB-06 |
| ②现状→目标 | `approval_policy: "first_time_contributors"` → `approval_policy: "all_external_contributors"` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/fork-pr-contributor-approval`（`approval_policy: "all_external_contributors"`） |
| ⑤前置条件 | 无（单人 org，当前无外部贡献者） |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：fork PR 的 workflow 需 maintainer 手动批准（配合 2026-07-28 平台自动拦截形成双保险）；**对引擎管线**：无影响（当前无 fork PR） |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions/fork-pr-contributor-approval -f approval_policy=first_time_contributors` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/fork-pr-contributor-approval --jq '.approval_policy'`（应输出 `all_external_contributors`） |

### PB-06.4：artifact-and-log-retention 维持 90 天（无变更，确认现状）

| 要素 | 值 |
|---|---|
| ①编号 | PB-06.4 |
| ②现状→目标 | `days: 90` → `days: 90`（维持现状，无变更） |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/artifact-and-log-retention`（`days: 90`） |
| ⑤前置条件 | 无 |
| ⑥爆炸半径 | 无变更，无影响 |
| ⑦回滚命令 | 无（维持现状） |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/artifact-and-log-retention --jq '.days'`（应输出 `90`） |

### PB-06.5：fork-pr-workflows-private-repos require_approval 收紧

| 要素 | 值 |
|---|---|
| ①编号 | PB-06.5 |
| ②现状→目标 | `require_approval_for_fork_pr_workflows: false` → `require_approval_for_fork_pr_workflows: true`（其他三开关维持 false） |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PUT /orgs/hdot123-org/actions/permissions/fork-pr-workflows-private-repos` |
| ⑤前置条件 | 无 |
| ⑥爆炸半径 | **仅私库有意义**（对 5 个私有辅助仓生效；3 公主仓由 PB-06 的 approval_policy 与平台自动拦截覆盖）；**对进行中 PR/CI/引擎管线**：无影响（当前无 fork PR） |
| ⑦回滚命令 | `gh api -X PUT /orgs/hdot123-org/actions/permissions/fork-pr-workflows-private-repos -F require_approval_for_fork_pr_workflows=false` |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/permissions/fork-pr-workflows-private-repos --jq '.require_approval_for_fork_pr_workflows'`（应输出 `true`） |

---

## Batch C：安全默认（org 级 enable_all 族）

### PB-07：dependency_graph enable_all + 新仓默认开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-07 |
| ②现状→目标 | 新仓默认=false + org 级 enable_all=未执行 → 新仓默认=true + 执行 enable_all |
| ③免费可用性 | 可用（公私皆生效） |
| ④API 或 UI | `POST /orgs/hdot123-org/dependency_graph/enable_all` + `PATCH /orgs/hdot123-org`（新仓默认） |
| ⑤前置条件 | 无（dependency graph 是 Dependabot 前置，应先于 PB-08/PB-09） |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：无影响；**对引擎管线**：无影响（Dependabot 是独立 bot，不影响 CI/引擎流程） |
| ⑦回滚命令 | `gh api -X POST /orgs/hdot123-org/dependency_graph/disable_all` + `gh api -X PATCH /orgs/hdot123-org -f dependency_graph_enabled_for_new_repositories=false` |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.dependency_graph_enabled_for_new_repositories'`（应输出 `true`） |

### PB-08：dependabot_alerts enable_all + 新仓默认开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-08 |
| ②现状→目标 | 新仓默认=false + org 级 enable_all=未执行 → 新仓默认=true + 执行 enable_all |
| ③免费可用性 | 可用（公私皆生效） |
| ④API 或 UI | `POST /orgs/hdot123-org/dependabot_alerts/enable_all` + `PATCH /orgs/hdot123-org` |
| ⑤前置条件 | PB-07（dependency graph）应先执行 |
| ⑥爆炸半径 | 同 PB-07（Dependabot alerts 是独立检测，不影响 CI/引擎流程） |
| ⑦回滚命令 | `gh api -X POST /orgs/hdot123-org/dependabot_alerts/disable_all` + `gh api -X PATCH /orgs/hdot123-org -f dependabot_alerts_enabled_for_new_repositories=false` |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.dependabot_alerts_enabled_for_new_repositories'`（应输出 `true`） |

### PB-09：dependabot_security_updates enable_all + 新仓默认开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-09 |
| ②现状→目标 | 新仓默认=false + org 级 enable_all=未执行 → 新仓默认=true + 执行 enable_all |
| ③免费可用性 | 可用 |
| ④API 或 UI | `POST /orgs/hdot123-org/dependabot_security_updates/enable_all` + `PATCH /orgs/hdot123-org` |
| ⑤前置条件 | PB-07（dependency graph）应先执行 |
| ⑥爆炸半径 | 同 PB-07（Dependabot security updates 是自动修复 PR，不影响 CI/引擎流程） |
| ⑦回滚命令 | `gh api -X POST /orgs/hdot123-org/dependabot_security_updates/disable_all` + `gh api -X PATCH /orgs/hdot123-org -f dependabot_security_updates_enabled_for_new_repositories=false` |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.dependabot_security_updates_enabled_for_new_repositories'`（应输出 `true`） |

---

## Batch D：成员特权（org 级）

### PB-10：default_repository_permission 收紧

| 要素 | 值 |
|---|---|
| ①编号 | PB-10 |
| ②现状→目标 | `default_repository_permission: "read"` → `default_repository_permission: "none"` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PATCH /orgs/hdot123-org`（`default_repository_permission: "none"`） |
| ⑤前置条件 | 单人 org 影响小，但未来加成员前须先设好 |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：无影响；**对引擎管线**：无影响（仅影响未来新增成员的默认权限） |
| ⑦回滚命令 | `gh api -X PATCH /orgs/hdot123-org -f default_repository_permission=read` |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.default_repository_permission'`（应输出 `none`） |

### PB-11：members_can_create_public_repositories 关闭

| 要素 | 值 |
|---|---|
| ①编号 | PB-11 |
| ②现状→目标 | `members_can_create_public_repositories: true` → `members_can_create_public_repositories: false` |
| ③免费可用性 | 可用 |
| ④API 或 UI | `PATCH /orgs/hdot123-org`（`members_can_create_public_repositories: false`） |
| ⑤前置条件 | 无 |
| ⑥爆炸半径 | **对进行中 PR/CI/引擎管线**：无影响（仅影响未来成员新建公库的能力） |
| ⑦回滚命令 | `gh api -X PATCH /orgs/hdot123-org -F members_can_create_public_repositories=true` |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.members_can_create_public_repositories'`（应输出 `false`） |

---

## Batch E：runner 治理（org 级）

### PB-12：runner-groups 收编

| 要素 | 值 |
|---|---|
| ①编号 | PB-12 |
| ②现状→目标 | 2 组（Default=all, memory-runnerz=selected）→ 1 个核心组（core-runners），限定 3 主仓 |
| ③免费可用性 | 可用（self-hosted runners 无分钟费） |
| ④API 或 UI | `POST /orgs/hdot123-org/actions/runner-groups`（建组）+ `PUT .../runner-groups/{id}/repositories`（绑定仓库）+ `PUT .../runner-groups/{id}/runners/{runner_id}`（迁移 runner） |
| ⑤前置条件 | 盘点 5 台 runner 当前分布（哪台在哪个组），确认迁移不影响运行中 workflow |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：若迁移期间 runner 不可用，workflow 会等待；**对引擎管线**：需确保 3 主仓仍在 runner 组授权列表 |
| ⑦回滚命令 | `gh api -X DELETE /orgs/hdot123-org/actions/runner-groups/{NEW_GROUP_ID}`（删新组，runner 自动回 Default 组） |
| ⑧验证命令 | `gh api /orgs/hdot123-org/actions/runner-groups --jq '.runner_groups[] | {name, visibility, selected_repositories}'` |

---

## Batch F：Layer 2 残余面（仅 3 主仓）

### PB-13：memory / mencbo 分支保护 classic → rulesets 迁移

| 要素 | 值 |
|---|---|
| ①编号 | PB-13 |
| ②现状→目标 | memory / mencbo 用 classic branch protection → 迁移到 repo 级 rulesets（同构复制 infra-core 的 `main-branch-protection`） |
| ③免费可用性 | 可用（repo 级 rulesets 所有 plan 可用） |
| ④API 或 UI | `POST /repos/hdot123-org/memory/rulesets` + `POST /repos/hdot123-org/mencbo/rulesets`（JSON 模板见 as-code 模板） |
| ⑤前置条件 | ① 确认 memory / mencbo 的必需 status check 名（与 infra-core 不同）② 经典保护退役顺序（先建 ruleset active → 验证 → 删 classic） |
| ⑥爆炸半径 | **对进行中 PR**：无影响（ruleset 与 classic protection 语义一致）；**对运行中 CI**：无影响；**对引擎管线**：无影响 |
| ⑦回滚命令 | `gh api -X DELETE /repos/hdot123-org/memory/rulesets/{ID}` + `gh api -X DELETE /repos/hdot123-org/mencbo/rulesets/{ID}`（删 ruleset，classic protection 需手动重建） |
| ⑧验证命令 | `gh api /repos/hdot123-org/memory/rulesets --jq '.[].name'` + `gh api /repos/hdot123-org/mencbo/rulesets --jq '.[].name'` |

**org 覆盖不到论证**：org 级 rulesets 需 Team+（产物 A §8.1：`GET /orgs/hdot123-org/rulesets` → 403），Free plan 只能 repo 级 rulesets。

### PB-14：CODEOWNERS 缺失（infra-core / mencbo）

| 要素 | 值 |
|---|---|
| ①编号 | PB-14 |
| ②现状→目标 | 仅 memory 有 `.github/CODEOWNERS` → infra-core / mencbo 各创建 `.github/CODEOWNERS`（至少 `* @hdot123`） |
| ③免费可用性 | 可用（仓库内容文件，无 plan 限制） |
| ④API 或 UI | 仓库内容文件（git commit + push） |
| ⑤前置条件 | 确定各仓 owner 列表（单人 org 均为 @hdot123） |
| ⑥爆炸半径 | **对进行中 PR**：无影响（CODEOWNERS 仅影响未来 PR 的 review 请求）；**对运行中 CI/引擎管线**：无影响 |
| ⑦回滚命令 | `git rm .github/CODEOWNERS` + commit + push |
| ⑧验证命令 | `gh api /repos/hdot123-org/infra-core/contents/.github/CODEOWNERS` + `gh api /repos/hdot123-org/mencbo/contents/.github/CODEOWNERS`（应返回文件内容） |

**org 覆盖不到论证**：CODEOWNERS 是仓库级内容文件，无 org 级 API 或规则可统一配置（产物 A 附节「仅 repo 级载体证明行」行 1 CODEOWNERS：普查 §7.1/§7.2 十组命令面与 UI 清单均无 org 级 CODEOWNERS 项）。

### PB-15：POSTHOG_INGESTION_KEY 从 mencbo Actions variables 迁移 secrets

| 要素 | 值 |
|---|---|
| ①编号 | PB-15 |
| ②现状→目标 | `POSTHOG_INGESTION_KEY` 明文存于 mencbo Actions variables → 迁移到 mencbo Actions secrets（或 org 级 secrets 按仓库访问控制限定 mencbo） |
| ③免费可用性 | 可用 |
| ④API 或 UI | repo 级 secrets/variables API（`PUT /repos/{owner}/{repo}/actions/secrets/{secret_name}`）；具体四步并行期设计见下方，模板参考 `templates/`，修正方案见 `correction-plan.md` |
| ⑤前置条件 | ① 获取 POSTHOG_INGESTION_KEY 当前值（从 variables 读取）② 改 workflow 引用 |
| ⑥爆炸半径 | **对进行中 PR**：无影响；**对运行中 CI**：若 workflow 仍在读 variables 会失败（需并行期）；**对引擎管线**：无影响（mencbo 无引擎管线） |
| ⑦回滚命令 | 并行期内：改回读 variables；并行期结束后：`DELETE /repos/hdot123-org/mencbo/actions/secrets/POSTHOG_INGESTION_KEY` + 重新创建 variable |
| ⑧验证命令 | `gh api /repos/hdot123-org/mencbo/actions/secrets --jq '.secrets[] | select(.name=="POSTHOG_INGESTION_KEY")'` + `gh api /repos/hdot123-org/mencbo/actions/variables --jq '.variables[] | select(.name=="POSTHOG_INGESTION_KEY")'`（后者应返回空） |

**org 覆盖不到论证**：repo 级 secrets/variables 无法由 org 级规则自动迁移（产物 A §5.1/5.2：org 级只能集中，不能自动迁移 repo 级存量值）。

**并行期四步设计**：
1. **建 secret**：`PUT /repos/hdot123-org/mencbo/actions/secrets/POSTHOG_INGESTION_KEY`（写入值）
2. **改 workflow 引用**：mencbo 仓内 workflow 文件中 `variables.POSTHOG_INGESTION_KEY` → `secrets.POSTHOG_INGESTION_KEY`
3. **验证**：确认 workflow 读取 secrets 成功（`gh api /repos/hdot123-org/mencbo/actions/secrets` GET 确认存在）
4. **末步删 variable**：`DELETE /repos/hdot123-org/mencbo/actions/variables/POSTHOG_INGESTION_KEY`（单独末步，不与建 secret 同步）

**并行期回滚**：改回读 variables（`variables.POSTHOG_INGESTION_KEY`）。

### PB-16：mencbo 合并策略统一

| 要素 | 值 |
|---|---|
| ①编号 | PB-16 |
| ②现状→目标 | `allow_merge_commit=true, allow_rebase_merge=true, allow_squash_merge=true, delete_branch_on_merge=false` → `allow_squash_merge=true, allow_merge_commit=false, allow_rebase_merge=false, delete_branch_on_merge=true`（squash-only + 自动删分支） |
| ③免费可用性 | 可用（repo 级设置） |
| ④API 或 UI | `PATCH /repos/hdot123-org/mencbo`（`allow_merge_commit: false, allow_rebase_merge: false, delete_branch_on_merge: true`） |
| ⑤前置条件 | ① 盘点 mencbo 当前 open PR（`gh pr list -R hdot123-org/mencbo --state open`），确认待合并 PR 的合并方式 ② 配合 PB-13 的 ruleset 迁移一并设置 squash-only 约束 |
| ⑥爆炸半径 | **对进行中 PR**：合并方式选项变化（仅剩 squash），待合并 PR 需确认合并按钮行为；**对运行中 CI**：无影响；**对引擎管线**：无影响（mencbo 无引擎管线） |
| ⑦回滚命令 | `gh api -X PATCH /repos/hdot123-org/mencbo -F allow_merge_commit=true -F allow_rebase_merge=true -F delete_branch_on_merge=false` |
| ⑧验证命令 | `gh api /repos/hdot123-org/mencbo --jq '{allow_merge_commit, allow_rebase_merge, allow_squash_merge, delete_branch_on_merge}'` |

**org 覆盖不到论证**：合并策略为 repo 级设置（`PATCH /repos/{owner}/{repo}`），org 级无统一端点（org 级 rulesets 可覆盖但需 Team——产物 A §8.1）。

**open PR 盘点命令**：`gh pr list -R hdot123-org/mencbo --state open --json number,title,mergeable`

### PB-17：dependabot.yml 缺失（infra-core / mencbo）

| 要素 | 值 |
|---|---|
| ①编号 | PB-17 |
| ②现状→目标 | 仅 memory 有 `.github/dependabot.yml` → infra-core / mencbo 各创建 `.github/dependabot.yml`（至少 `version: 2` + `package-ecosystem: github-actions`） |
| ③免费可用性 | 可用（仓库内容文件，无 plan 限制） |
| ④API 或 UI | 仓库内容文件（git commit + push） |
| ⑤前置条件 | 确定各仓依赖生态（infra-core: github-actions + pip; mencbo: github-actions + npm 等） |
| ⑥爆炸半径 | **对进行中 PR**：无影响（Dependabot 是独立 bot）；**对运行中 CI/引擎管线**：无影响 |
| ⑦回滚命令 | `git rm .github/dependabot.yml` + commit + push |
| ⑧验证命令 | `gh api /repos/hdot123-org/infra-core/contents/.github/dependabot.yml` + `gh api /repos/hdot123-org/mencbo/contents/.github/dependabot.yml`（应返回文件内容） |

**org 覆盖不到论证**：dependabot.yml 是仓库级内容文件；org 级 Dependabot version updates 集中 API 未确认（产物 A 附节「仅 repo 级载体证明行」行 2 Dependabot version updates：实测 `GET /orgs/{org}/dependabot/version-updates` → 404，语义=未启用或不存在；普查 §8 #6 保持未确认）。

---

## Batch G：Layer 3 仅 UI 层（人工操作）

### PB-18：2FA 强制开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-18 |
| ②现状→目标 | `two_factor_requirement_enabled: false` → `two_factor_requirement_enabled: true` |
| ③免费可用性 | 可用 |
| ④API 或 UI | **仅 UI**——Settings > Authentication security > Two-factor authentication > Require 2FA for everyone in the organization |
| ⑤前置条件 | 唯一成员（hdot123）已开启个人 2FA |
| ⑥爆炸半径 | **对进行中 PR/CI/引擎管线**：无影响；**实际效果**：单人 org 唯一成员已启 2FA 时无成员被移除，收紧面为未来新增成员与外部协作者 |
| ⑦回滚命令 | UI 关闭路径：Settings > Authentication security > 取消勾选 Require 2FA |
| ⑧验证命令 | `gh api /orgs/hdot123-org --jq '.two_factor_requirement_enabled'`（应输出 `true`） |

### PB-19：OAuth App 访问限制开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-19 |
| ②现状→目标 | 未开启 → 开启（拦截未批准 OAuth App 访问 org 资源） |
| ③免费可用性 | 可用 |
| ④API 或 UI | **仅 UI**——Settings > Integrations > OAuth applications > Approve or disallow third-party applications |
| ⑤前置条件 | 盘点当前已授权 OAuth App（已装 4 个 GitHub App 不受影响——OAuth App ≠ GitHub App） |
| ⑥爆炸半径 | **对进行中 PR/CI/引擎管线**：无影响；**对成员**：未来成员无法随手授权第三方 App 读 org 资源 |
| ⑦回滚命令 | UI 关闭路径：Settings > Integrations > OAuth applications > 取消限制 |
| ⑧验证命令 | 无 REST 端点（仅 UI 可读） |

### PB-20：fine-grained PAT 审批制开启

| 要素 | 值 |
|---|---|
| ①编号 | PB-20 |
| ②现状→目标 | 未开启审批制 → 开启审批制（成员用 fgPAT 访问 org 前需 owner 审批） |
| ③免费可用性 | 可用 |
| ④API 或 UI | **仅 UI**——Settings > Integrations > Personal access tokens > Require approval for all members |
| ⑤前置条件 | 盘点当前在用 fgPAT（`GET /orgs/hdot123-org/personal-access-tokens`） |
| ⑥爆炸半径 | **对进行中 PR/CI/引擎管线**：无影响；**对成员**：未来成员用 fgPAT 访问 org 需 owner 审批 |
| ⑦回滚命令 | UI 关闭路径：Settings > Integrations > Personal access tokens > 取消审批制 |
| ⑧验证命令 | `gh api /orgs/hdot123-org/personal-access-tokens --jq '.tokens | length'`（盘点存量，策略开关无 REST 端点） |

---

## 升级 Team 评估（不可执行项）

> 普查 §7.3 不可用能力——需升级 plan 或购买产品。本章节**不含可执行变更项**，仅逐项给出升级依据与解锁收益。

### secret_scanning / secret_scanning_push_protection 的 org 级 enable_all

**原可执行主体位置**：Batch C（安全默认 enable_all 族，原 PB-10/PB-11）。

**移出原因**：`POST /orgs/{org}/secret_scanning/enable_all` 与 `POST /orgs/{org}/secret_scanning_push_protection/enable_all` 不在普查 §7.1 十组白名单内（census §7.3 标记为 Free 不可用/需 Team），禁止留在可执行主体中。"如 Free 支持"类对冲表述不得留在可执行项。

**升级依据**：
- secret_scanning：2025-04-01 起 Team plan 可单独购买 Secret Protection（公库免费自动，3 主仓已自动享有）
- secret_scanning_push_protection：同上（公库免费自动，3 主仓已自动享有）
- 私库侧：需 Team + Secret Protection 解锁

**解锁收益**：
- 私库（5 辅助仓）自动扫描/拦截泄露密钥（公库免费自动，3 主仓已享有）
- org 级统一配置新仓默认（私库侧目前无统一开关）

**repo 级公库替代路径**：3 主仓（public）已自动享有 secret scanning + push protection（公库免费特性），无需 org 级 enable_all 解锁。新仓若为公库，需手动在仓库 Settings 开启或由 org 新仓默认配置（`secret_scanning_enabled_for_new_repositories` 为 PATCH /orgs 级字段，与 enable_all 端点分离）。

**参考**：治理规范 `org-governance-spec.md` §5「升级 Team 评估」章节。

### 其余升级 Team 评估项

参见治理规范 `org-governance-spec.md` §5（逐项给出升级依据与解锁收益，含 org 级 rulesets / merge queue 私库 / environments 私库 / code scanning 私库 / required workflows / SAML / Codespaces 策略 / Copilot 策略 / 私库 Pages）。

---

## 1. 执行顺序总结

| 批次 | 变更项 | 性质 | 依赖 |
|---|---|---|---|
| Batch A | PB-00, PB-00.5 | 预备（SHA 化 + 盘点） | 无 |
| Batch B | PB-01 ~ PB-06.5 | Actions 策略收紧 | PB-00, PB-00.5 |
| Batch C | PB-07 ~ PB-09 | 安全默认 enable_all（dependency_graph/dependabot_alerts/dependabot_security_updates） | 无 |
| Batch D | PB-10 ~ PB-11 | 成员特权收紧 | 无 |
| Batch E | PB-12 | runner 治理 | 无 |
| Batch F | PB-13 ~ PB-17 | Layer 2 残余面 | PB-13 先于 PB-16（ruleset 迁移配合合并策略） |
| Batch G | PB-18 ~ PB-20 | Layer 3 仅 UI | 无 |

**顺序安全不变式**：
- PB-00（SHA 化）< PB-03（sha_pinning_required 开启）✓
- PB-00.5（盘点）< PB-01/PB-02（allowlist 收紧）✓

---

## 2. 权限类变更影响总结

| 变更项 | 对进行中 PR 影响 | 对运行中 CI 影响 | 对引擎管线影响 |
|---|---|---|---|
| PB-02/PB-01（allowlist） | 无 | 新 PR 若引用未在 allowlist 的 action 会失败 | auto-merge/droid-review/release-please 需确认 action 在 allowlist |
| PB-03（SHA pinning） | 无 | 新 PR 若 action 引用非 SHA 形式会失败 | infra-core 已完成，memory/mencbo 需先 PB-00 |
| PB-04（default permissions read） | 无 | 需显式 `permissions: write` 的 job 会失败 | auto-merge/branch-cleanup/release-please 需显式声明 |
| PB-05（can_approve=false） | 无 | workflow 无法自动批准 PR | droid-review 提交 review 但不批准，无影响 |
| PB-06（fork PR 审批） | 无 | fork PR workflow 需 maintainer 批准 | 无影响（当前无 fork PR） |
| PB-10（default permission none） | 无 | 无 | 无（仅影响未来新增成员） |
| PB-12（runner 组） | 无 | 迁移期间 runner 不可用会等待 | 需确保 3 主仓在 runner 组授权列表 |
| PB-13（rulesets 迁移） | 无 | 无 | 无 |
| PB-15（POSTHOG 迁移） | 无 | 并行期内若 workflow 仍读 variables 会失败 | 无影响（mencbo 无引擎管线） |
| PB-16（合并策略） | 合并方式选项变化 | 无 | 无 |

---

## 3. 回滚与验证总结

**回滚原则**：
- 每个变更项的回滚为同端点反向命令，参数回现状值
- Layer 1 回滚：org 级 API 反向命令
- Layer 2 回滚：repo 级 API 反向命令或 git revert
- Layer 3 回滚：UI 关闭路径

**验证原则**：
- 全部验证命令只读（`gh api` GET、`grep`、文件检查）
- 不执行任何写命令

---

## 4. 公开仓铁律

本文档落入公开仓 infra-core，必须满足：
- **无本地绝对路径**
- **无 secret 值**（POSTHOG_INGESTION_KEY 等只允许出现键名）
- **secret 写入命令只允许占位符**（`<VALUE>` 或 env 引用）

---

## 5. 参考索引

- 治理规范：`org-governance-spec.md`
- 差距矩阵：`memory/artifacts/2026-09-09-gap-matrix-org-first.md`（产物 C，相对路径，`memory/` 整目录被 .gitignore，仅本地工作区可达，公开读者不可访问）
- 能力普查：`memory/artifacts/2026-09-09-org-capability-census.md`（相对路径）
- 现状审计：`memory/artifacts/2026-09-09-org-state-audit.md`（相对路径）

**注**：`memory/` 目录在 .gitignore 中（memory-hook 产物，公开仓禁止提交），但上述路径为相对路径，便于内部引用。公开读者如需查阅，请参考 docs/governance/ 下的治理规范与 playbook。

---

**Playbook 完**
