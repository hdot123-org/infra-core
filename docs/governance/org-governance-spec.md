# GitHub Org 治理规范 — hdot123-org

**对象**：github.com/hdot123-org（Free plan，9 仓库，1 成员，5 台 self-hosted Linux runners）
**性质**：治理规范文档（org 级规则最大化基线 + 残余面最小集）
**日期**：2026-09-09
**上游产物**：
- 能力普查 `2026-09-09-org-capability-census.md`
- 现状审计 `2026-09-09-org-state-audit.md`
- org 规则覆盖面矩阵 `2026-09-09-org-rule-coverage-matrix.md`（产物 A）
- 公私覆盖语义修正矩阵 `2026-09-09-org-rule-public-private-correction-matrix.md`（产物 B）
- 差距矩阵 `2026-09-09-gap-matrix-org-first.md`（产物 C）
- 引擎重复造轮子对照表 `2026-09-09-engine-duplication-map.md`（产物 D）

---

## 1. 治理分层原则

### 1.1 用户裁定（2026-09-09）

**org 级规则是唯一治理层**。所有仓库自动继承 org 级规则，**最大化使用 GitHub org 规则**。

仓库级只处理 org 规则在 Free plan 上覆盖不到的**最小残余面**（仅 3 个主仓：infra-core / memory / mencbo）。

辅助仓（demo-repository、reimagined-engine-demo-repository、go-github、mitce-cloudflare、excalidraw-fork、shared-workflows[archived]）不逐仓审计/整改——org 规则生效后自动继承。

### 1.2 分层治理架构

| 层 | 覆盖范围 | 内容 | 条目数 |
|---|---|---|---|
| **Layer 1：org 级最大化** | 全部 9 仓库（含 6 辅助仓）自动继承 | 普查 §7.1 第 1–9 组命令对应的 org 级 API 变更 | 16 项 |
| **Layer 2：残余面最小集** | 仅 3 主仓（infra-core/memory/mencbo） | org 规则在 Free plan 覆盖不到的仓库级变更 | ~5 项 |
| **Layer 3：仅 UI 层** | 全部 9 仓库自动继承 | 普查 §7.2 仅 UI 可配项（2FA/OAuth/fgPAT） | 3 项 |
| **升级 Team 评估** | 需升级 plan 的能力 | 普查 §7.3 不可用能力逐项给升级依据与解锁收益 | 独立章节 |

### 1.3 关键事实基础

**可见性**（覆盖语义推导前提）：

| 仓库 | visibility | archived | 角色 |
|---|---|---|---|
| infra-core | public | false | 主仓（引擎宿主） |
| memory | public | false | 主仓 |
| mencbo | public | false | 主仓 |
| demo-repository / reimagined-engine-demo-repository / go-github / mitce-cloudflare / excalidraw-fork | private | false | 辅助仓（org 规则自动继承） |
| shared-workflows | public | true | 归档仓（org 规则形式覆盖，Actions 不再执行） |

**公库免费安全特性**（3 主仓已自动享有，不依赖 org 开关）：
- secret scanning + push protection
- code scanning（default setup / CodeQL）
- merge queue
- environments（含 protection rules）
- Pages
- 2026-07-28 恶意 workflow 自动 hold

**org 规则叠加关系**：
- 对公库：org enable_all 类规则 = 配置统一（非解锁）
- 对私库：org enable_all = 解锁路径（部分需 Team+）
- 2026-07-28 恶意 workflow 自动 hold = 仅公库生效（平台行为）

---

## 2. Layer 1：org 级规则最大化基线

> org 级规则自动覆盖 org 全部仓库（含 6 辅助仓），无需逐仓动作。

### 2.1 Actions 策略全家桶

| 规则 | 当前值 | 目标值 | Free 可用性 | API 端点 |
|---|---|---|---|---|
| enabled_repositories | all | all（维持） | 可用 | `PUT /orgs/{org}/actions/permissions` |
| allowed_actions | **all**（全放开） | **selected**（allowlist） | 可用（2026-02-05 Free 解锁） | `PUT /orgs/{org}/actions/permissions` |
| selected-actions | 未配置（409 语义） | github_owned + verified + patterns | 可用 | `PUT .../selected-actions` |
| sha_pinning_required | false | **true** | 可用（2025-08-15） | `PUT /orgs/{org}/actions/permissions` |
| default_workflow_permissions | write | **read** | 可用 | `PUT .../permissions/workflow` |
| can_approve_pull_request_reviews | true | **false** | 可用 | `PUT .../permissions/workflow` |
| fork-pr-contributor-approval | first_time_contributors | **all_external_contributors** | 可用 | `PUT .../fork-pr-contributor-approval` |
| fork-pr-workflows-private-repos require_approval | false | **true** | 可用 | `PUT .../fork-pr-workflows-private-repos` |
| artifact-and-log-retention | 90 天 | 90 天（维持） | 可用 | `PUT .../artifact-and-log-retention` |

**覆盖语义**：全部 9 仓库自动继承，无需逐仓动作。

**前置条件**：
- SHA pinning 开启前：全量 workflow SHA 化（3 主仓全部 workflow 第三方 action pin 到 full-length SHA）
- allowlist 收紧前：在用第三方 action 盘点（产出 allowlist 候选清单）

### 2.2 安全默认 / enable_all 族

| 规则 | 当前值 | 目标值 | Free 可用性 | API 端点 |
|---|---|---|---|---|
| dependency_graph enable_all | 新仓默认=false | 新仓默认=true + enable_all | 可用（公私皆生效） | `POST /orgs/{org}/dependency_graph/enable_all` |
| dependabot_alerts enable_all | 新仓默认=false | 新仓默认=true + enable_all | 可用（公私皆生效） | `POST /orgs/{org}/dependabot_alerts/enable_all` |
| dependabot_security_updates enable_all | 新仓默认=false | 新仓默认=true + enable_all | 可用 | `POST /orgs/{org}/dependabot_security_updates/enable_all` |

**覆盖语义**：
- 对 3 主仓（public）：enable_all = 配置统一（公库免费自动）
- 对 5 辅助仓（private）：dependency_graph / dependabot_alerts / dependabot_security_updates 免费可用

**注**：secret_scanning / secret_scanning_push_protection 的 org 级 enable_all 端点不在普查 §7.1 十组白名单内（census §7.3 标记为 Free 不可用/需 Team），不在 Layer 1 可执行范围内。3 主仓（public）已自动享有 secret scanning + push protection（公库免费特性），私库侧进「升级 Team 评估」（§5）。

### 2.3 成员特权收紧

| 规则 | 当前值 | 目标值 | Free 可用性 | API 端点 |
|---|---|---|---|---|
| default_repository_permission | read | **none** | 可用 | `PATCH /orgs/{org}` |
| members_can_create_public_repositories | true | **false** | 可用 | `PATCH /orgs/{org}` |
| members_can_fork_private_repositories | false | false（维持） | 可用 | — |
| deploy_keys_enabled_for_repositories | false | false（维持） | 可用 | — |
| web_commit_signoff_required | false | false（维持） | 可用 | — |

**覆盖语义**：全部 9 仓库自动继承。

### 2.4 runner 组治理

| 规则 | 当前值 | 目标值 | Free 可用性 | API 端点 |
|---|---|---|---|---|
| runner-groups | 2 组（Default=all, memory-runnerz=selected） | 1 个核心组（core-runners），限定 3 主仓 | 可用 | `POST /orgs/{org}/actions/runner-groups` |

**覆盖语义**：全部 9 仓库自动继承（runner 组按 visibility/selected_repositories 授权）。

### 2.5 org secrets/variables 集中

| 规则 | 当前值 | 目标值 | Free 可用性 | API 端点 |
|---|---|---|---|---|
| org Actions secrets | 2 个（BAILIAN_API_KEY、FACTORY_API_KEY） | POSTHOG_INGESTION_KEY 迁移后集中 | 可用 | `PUT /orgs/{org}/actions/secrets/{name}` |
| org Actions variables | 0 个 | 可考虑将通用变量集中 | 可用 | `PUT /orgs/{org}/actions/variables/{name}` |

**覆盖语义**：全部 9 仓库自动继承（按仓库访问控制）。

---

## 3. Layer 2：残余面最小集（仅 3 主仓）

> 仅含 org 规则在 Free plan 上覆盖不到的仓库级变更。每项附「org 覆盖不到」论证。

### 3.1 分支保护 rulesets 化

**目标**：memory / mencbo 从 classic branch protection 迁移到 repo 级 rulesets（同构复制 infra-core 的 `main-branch-protection`）。

**org 覆盖不到论证**：org 级 rulesets 需 Team+（产物 A §8.1：`GET /orgs/hdot123-org/rulesets` → 403 "Upgrade to GitHub Team"），Free plan 只能 repo 级 rulesets。

**覆盖范围**：仅 infra-core / memory / mencbo（3 主仓）。

### 3.2 CODEOWNERS 缺失

**目标**：infra-core / mencbo 各创建 `.github/CODEOWNERS`。

**org 覆盖不到论证**：CODEOWNERS 是仓库内容文件，无 org 级 API 或规则可统一配置（产物 A 无对应 org 级规则行）。

### 3.3 POSTHOG_INGESTION_KEY 迁移

**目标**：从 mencbo Actions variables（明文）迁移到 Actions secrets（或 org 级 secrets）。

**org 覆盖不到论证**：repo 级 secrets/variables 无法由 org 级规则自动迁移（产物 A §5.1/5.2：org 级只能集中，不能自动迁移 repo 级存量值）。

### 3.4 mencbo 合并策略统一

**目标**：mencbo 从三种合并方式全开 + delete_branch_on_merge=false 统一为 squash-only + delete_branch_on_merge=true。

**org 覆盖不到论证**：合并策略为 repo 级设置（`PATCH /repos/{owner}/{repo}`），org 级无统一端点（org 级 rulesets 可覆盖但需 Team——产物 A §8.1）。

### 3.5 dependabot.yml 缺失

**目标**：infra-core / mencbo 各创建 `.github/dependabot.yml`。

**org 覆盖不到论证**：dependabot.yml 是仓库级内容文件；org 级 Dependabot version updates 集中 API 未确认（普查 §8 #6 保持未确认）。

---

## 4. Layer 3：仅 UI 层

> 普查 §7.2 清单——无 REST 写端点，需人工在 GitHub UI 操作。

| 项 | 操作路径 | 当前状态 | 目标状态 |
|---|---|---|---|
| **2FA 强制** | Settings > Authentication security | false | **true**（单人 org 实效：唯一成员已启 2FA 时无成员被移除，收紧面为未来新增成员与外部协作者） |
| **OAuth App 访问限制** | Settings > Integrations > OAuth applications | 未开启 | **开启**（拦截未批准 OAuth App 访问 org 资源） |
| **fine-grained PAT 审批制** | Settings > Integrations > Personal access tokens | 未开启 | **开启审批制**（成员用 fgPAT 访问 org 前需 owner 审批） |

**覆盖语义**：全部 9 仓库自动继承（org 级策略）。

---

## 5. 升级 Team 评估

> 普查 §7.3 不可用能力——需升级 plan 或购买产品。逐项给升级依据与解锁收益。

| 能力 | 当前可用性 | 升级依据 | 解锁收益 |
|---|---|---|---|
| **org 级 rulesets** | 不可用（需 Team+） | 2025-06-16 起 Team plan 可用；可整体替代 Layer 2 的 3 主仓逐仓 ruleset 复制 | 一套规则护多仓，Layer 2 残余面可上移到本层 |
| **merge queue（私库）** | 不可用（私库需 GHEC） | docs 原文"private repositories owned by organizations using GitHub Enterprise Cloud" | 排队合并防主干损坏（公库免费可用，3 主仓已享有） |
| **environments（私库）** | 不可用（私库需 Team+） | 公库免费可用（3 主仓已享有）；私库需 Team+ | 私库部署门禁 + env secrets（公库已可用） |
| **secret scanning（私库）** | 不可用（私库需 Team+ Secret Protection） | 2025-04-01 起 Team plan 可单独购买 Secret Protection | 私库自动扫描/拦截泄露密钥（公库免费自动，3 主仓已享有） |
| **code scanning（私库）** | 不可用（私库需 Team+ Code Security） | 2025-04-01 起 Team plan 可单独购买 Code Security | 私库 SAST（公库免费，3 主仓已享有） |
| **required workflows** | 不可用（需 GHEC） | docs 原文 GHEC/GHES 专属 | org 强制必过 workflow（当前用 repo 级 rulesets 的 required_status_checks 替代） |
| **SAML SSO** | 不可用（需 GHEC） | 企业统一认证，单人 org 无需 | — |
| **org Codespaces 策略** | 不可用（需 Team+） | docs 原文 Team/Enterprise 才能为成员付费 | 当前已有 5 台 self-hosted + 本地开发，不依赖 |
| **org Copilot 策略** | 不可用（需 Copilot Business/Enterprise） | 2026-09-03 changelog 证实为付费产品 | 当前成员各自用个人 Copilot，org 层无策略需求 |
| **私库 Pages** | 不可用（私库需 Pro/Team+） | 公库免费可用（3 主仓已享有）；私库需 Team+ | 当前未用 Pages（文档站走 Cloudflare/Vercel） |

**升级优先级建议**：org 级 rulesets > secret scanning（私库）> 其他（当前无迫切需求）。

---

## 6. 执行顺序与分批策略

详见 `change-playbook.md`——逐项变更 playbook 含：
- 每个变更项八要素（编号/现状→目标/免费可用性/API或UI/前置条件/爆炸半径/回滚命令/验证命令）
- 顺序安全：SHA 化预备项先于 sha_pinning_required 开启、action 盘点项先于 allowlist 收紧
- 分批策略（批次单调、无前向依赖、每项可独立批准-执行-验证-回滚）
- 权限类项标注对进行中 PR/CI/引擎管线影响
- 回滚为同端点反向命令且参数回现状值
- 验证命令全只读

---

## 7. 公开仓铁律

本文档落入公开仓 infra-core，必须满足：
- **无本地绝对路径**：用户主目录、临时目录等本地绝对路径一律禁止
- **无 secret 值**：POSTHOG_INGESTION_KEY 等只允许出现键名，不允许字面量值
- **secret 写入命令只允许占位符**：`<VALUE>` 或 env 引用

---

## 8. 参考索引

- REST API：https://docs.github.com/en/rest/orgs/orgs ；https://docs.github.com/en/rest/actions/permissions
- Changelog：https://github.blog/changelog/2026-02-05-github-actions-early-february-2026-updates/ （Free 解锁 allowlist）
- Changelog：https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/ （SHA pinning）
- Changelog：https://github.blog/changelog/2025-06-16-organization-rulesets-now-available-for-github-team-plans/ （org rulesets 需 Team+）
- Plan 可用性：https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning （公库免费，私库需 Team+）

---

**文档完**
