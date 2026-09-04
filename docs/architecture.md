# infra-core 架构

infra-core 是组织级演进引擎的宿主仓库：自进化（scanner）、审计（audit packs）、门禁（governance / droid-review）体系的共享基础设施。消费仓（第一个是 memory-core）通过 pip 依赖 + thin caller 工作流接入，依赖方向单一：`消费仓 → infra-core`。

## 1. 分层

```
infra-core（public 引擎仓库）
├── src/infra_core/
│   ├── engine/               # 自进化引擎（scanner/utils/adapters/heartbeat/anchor_gate）
│   ├── packs/                # 规则包（memory 等，经 infra_core.packs entry points 发现）
│   ├── governance.py         # 治理自检（受保护路径修改权限判定，fail-closed）
│   └── cli.py                # infra-cli 统一入口
├── actions/                  # composite actions（governance-check 等）
├── .github/workflows/        # CI + governance 门禁（后续：reusable workflows）
└── tests/
```

## 2. 命名契约（字节级，最高优先级）

以下字符串构成隐式契约网络，任何一处静默改动会杀死 auto-merge / watchdog：

| 契约 | 值 | 消费方 |
|------|-----|--------|
| workflow 名 | `CI` | auto-merge workflow_run |
| workflow 名 | `Evolution Governance` | auto-merge workflow_run |
| workflow 名 | `Droid Auto Review` / `QA` | auto-merge、watchdog、ci-ok 零红扫描 |
| check 名（job key） | `qa-ok` | QA workflow 聚合门禁（ci-ok 零红扫描 + auto-merge rollup 消费，见 §5.1） |
| check 名（job key） | `ci-ok` | branch protection required check |
| check 显示名（job name） | `Block non-owner governance modifications` | branch protection required check |
| artifact 前缀（未来） | `droid-review-debug-` | watchdog quota-sweep |
| workflow 文件名（未来） | `evolution-scan.yml` | heartbeat `gh run list --workflow` |

契约测试：`tests/test_naming_contract.py` 对 shipped 模板断言字节级一致。改任何契约值必须同时改测试并在 PR 中说明。

## 3. 治理自检（governance self-bootstrap）

infra-core 用自己的 governance 门禁保护自身（self-bootstrap）：

- workflow `Evolution Governance` 在 PR 触碰受保护路径时要求 owner 身份（`pull_request_target`，workflow 与 action 均从 base 分支解析执行，PR 无法改写自己的门禁）
- 受保护路径（默认）：`.evolution/**`、`.github/workflows/**`、`src/infra_core/engine/**`、`webhook-scripts/**`
- 判定核心在 `src/infra_core/governance.py`（fail-closed：作者未知即拒绝；路径匹配用 fnmatch，目录模式覆盖目录条目本身）
- 本地 dry-run：`python -m infra_core.governance --author <login> --files <path>...`（退出码 0 放行 / 1 拒绝 / 2 输入错误）
- composite action `actions/governance-check` 参数化 owner-login / protected-patterns / github-token，供消费仓复用；action 内嵌自包含判定脚本 `governance_check.py`（与包内模块判定等价，等价性由测试锁定——消费仓使用 action 时不假设 infra-core 已安装）

## 4. CLI（infra-cli）

`infra-cli` 是统一命令行入口。M1 为骨架态：子命令 `scan` / `audit` / `version-sweep` 框架就位，`--help` 安全零副作用，未实现子命令优雅失败（非零退出 + 人类可读诊断，无 traceback）。

## 5. 门禁矩阵

`CI` workflow 共 10 个 job（2026-08-29 容量收敛：19 → 10 bundle 化，降低 pve 双机排队）：pytest 锚点 + lint-bundle（ruff/shellcheck/actionlint/repo-consistency 四合一）+ type-bundle（mypy×2）+ advisory-bundle（advisory×3）+ test-groups（schema/security/business_policy 三段顺序）+ guards + integration-tests + e2e-tests + health-check + ci-ok 聚合。结构契约由 `tests/test_ci_structure_contract.py` 锁定（job 集合快照只对齐当前 main，后续 ci.yml 变更由对应 feature 同步该测试）。

| 门禁 | workflow | 说明 |
|------|----------|------|
| pytest | `CI` | 单元测试 + 覆盖率地板（`--cov-fail-under`，ramp-up 计划见 pyproject.toml） |
| lint-bundle | `CI` | lint 四合一：ruff（check+format 两半）/ shellcheck / actionlint（宿主优先）/ repo 交付一致性检查（`scripts/repo_health_check.sh --ci`） |
| type-bundle | `CI` | mypy×2：分域 `mypy --strict` 各跑一次（src/infra_core 与 scripts/，Run mypy 重复步骤已去重） |
| guards | `CI` | 4 个守卫脚本：边界污染 / 文档分类 / fix-has-test / PR 引用一致性（后两个 PR-only，依赖 GH_TOKEN） |
| test-groups | `CI` | 专项测试组 bundle：schema/security/business_policy 三段顺序跑（`-m <marker> -n 4 --no-cov`） |
| advisory-bundle | `CI` | advisory 三合一（pip-audit / deptry / 遥测覆盖率审计 `scripts/audit_telemetry_coverage.sh`），INFRA-595 零红：无 `continue-on-error`，失败即红 check-run，ci-ok 按 `.result` 阻断（曾有 `continue-on-error` 时 `.result` 恒为 success，判定空转，run 33129232081 实证） |
| integration-tests / e2e-tests | `CI` | 独立专项组（`-m <marker> -n 4 --no-cov`）；e2e 附 CLI 冒烟 |
| health-check | `CI` | CI 健康自检（`scripts/ci_health_check.sh`） |
| ci-ok | `CI` | 聚合（branch protection required check），逐项显式阻断全部 9 个前置 job（含 advisory-bundle，按 `.result`；INFRA-595），另有 GitHub API 全 check-runs 零红扫描双保险 |
| qa-ok | `QA` | QA 聚合门禁：PR 子集（cli-e2e / security / schema / boundary）+ 夜间全量（coverage-audit / full-regression），job 家族映射见 §5.1；非 required check，由 ci-ok 零红扫描（`scripts/check_zero_red.sh`，全 check-runs success/skipped/neutral）与 auto-merge rollup 全绿判定纳入合并门禁 |
| governance | `Evolution Governance` | 受保护路径 owner 门禁（pull_request_target，执行 shipped governance-check action） |
| evolution 自扫 | `Evolution Scan Reusable` / `Evolution Heartbeat Reusable` | 非门禁：引擎仓自扫管道。reusable 被消费仓 `uses:` 引用，同时自带本仓 `schedule`（scan `17,47 * * * *`、heartbeat `53 */2 * * *`，INFRA-717）——本仓作为自扫消费仓无法建 thin caller（文件名被消费仓路径引用 + heartbeat 按文件名探活双契约钉死），schedule 仅宿主仓生效不影响消费仓 |
| release | `Release Please` | 非门禁：发版管道（schedule/push(paths)/dispatch，DISPATCH_TOKEN，详见第 6 节） |

## 5.1 QA 门禁（`QA` workflow）

`QA` workflow 与 memory-core qa.yml 同构（三触发：pull_request + schedule + workflow_dispatch），job 家族按 infra-core 语义适配：

| memory-core job | infra-core job | 说明 |
|-----------------|----------------|------|
| cli-e2e | cli-e2e | CLI 冒烟测试（`scripts/cli_smoke_test.sh` 接线） |
| coverage-audit | coverage-audit | 分支级覆盖率审计（schedule/dispatch only，PR 时 skip） |
| **hook-lifecycle** | **N/A** | **infra-core 无 hook/gateway/memory 协议栈**（消费仓 memory-core 专属），不适用 |
| business-policy | security-tests | 安全与策略测试（`-m security`，143 用例） |
| schema-migration | schema-tests | Schema 与迁移测试（`-m schema`，262 用例） |
| boundary-security | boundary-security | 边界守卫（`check_boundary.py` + `-m security -k boundary`） |
| full-regression | full-regression | 夜间全量 pytest（schedule/dispatch only，PR 时 skip） |
| qa-ok | qa-ok | 聚合（full-regression 不在 needs 中——夜间红不阻塞 PR 合并） |

### N/A 家族裁剪理由（不允许静默跳过）

**hook-lifecycle（N/A）**：infra-core 是引擎库，不含 hook gateway / session lifecycle / PreToolUse guard / telemetry / integrity-manifest 等消费仓协议栈。这些模块全部在 memory-core `memory_core/` 下（`_gateway_handlers.py` / `_init_finalize.py` / `memory_hook_integrity_*`），infra-core 永不 import memory_core（依赖方向单一：消费仓 → infra-core）。QA 侧无对应测试对象。

**boundary-security（复用而非 N/A）**：infra-core 自有 `scripts/check_boundary.py`（public 仓边界守卫：无 secrets 泄露、无本地绝对路径），已在 CI `guards` job 执行；QA 侧额外跑 `-m security -k boundary` 测试组，形成双重覆盖。

## 6. 发版管道（release-please）

workflow：`Release Please`（`.github/workflows/release-please.yml`），配置 `release-please-config.json`（python release-type），版本权威源 `.release-please-manifest.json`。

### 触发策略

| 触发 | 说明 |
|------|------|
| schedule（每日 2 次） | 北京时间 12:00 / 20:00，批量打包积攒的 conventional commits |
| push(paths) | main 上 `.release-please-manifest.json` 变更（即 Release PR 合并）→ 自动 tag + 发 Release |
| workflow_dispatch | 手动即时发版 |

代码 PR 实时合入 main 不变，发版与合入解耦（批处理模式）。

### Token 铁律：DISPATCH_TOKEN，禁止 GITHUB_TOKEN

release-please 的 `token` 输入必须用 `secrets.DISPATCH_TOKEN`（hdot123 PAT），不能用 `GITHUB_TOKEN`：

1. 仓库默认 workflow 权限为 read 且未开启「允许 GITHUB_TOKEN 创建 PR」——GITHUB_TOKEN 连 Release PR 都开不出来（2026-08-26 run 33007886603 事故）。
2. GitHub 递归防护会抑制 GITHUB_TOKEN 操作产生的 push 事件——Release PR 合并后的 `push(paths: .release-please-manifest.json)` 二次触发失效，tag/Release 永远出不来（memory-core 2026-08-15 v0.29.0/v0.30.0 两次事故，auto-merge 同源教训）。

### 发版链路（v0.1.0 已端到端验证）

```
schedule/dispatch → release-please 扫描 conventional commits
→ 开 Release PR（autorelease: pending，改 manifest + CHANGELOG.md）
→ CI 全绿 → 合并 Release PR
→ push(paths) 二次触发 → 打 tag（vX.Y.Z）+ 创建 GitHub Release
```

- manifest 初始 0.0.0，首个 Release PR 产出 v0.1.0（tag 格式无组件前缀）
- commit message 必须 conventional 格式（feat/fix/perf/chore/docs/refactor/ci/test）；`[INFRA-xxx] 描述` 前缀格式无法被解析、不进 CHANGELOG
- 架构铁律：禁止手动 tag、禁止手改 manifest 版本号，一切版本变更经 Release PR

### 排障

| 症状 | 根因与处置 |
|------|-----------|
| `Input required and not supplied: token` | 仓库 DISPATCH_TOKEN secret 缺失或值为空（2026-08-26 run 33008369603），按 1Password 权威值 `gh secret set` 重设 |
| heartbeat 告警 `self-heal dispatch failed` 且 run 日志 `HTTP 403: Resource not accessible by personal access token` | DISPATCH_TOKEN（fine-grained PAT）缺 **Actions: Read and write** 权限——workflow dispatch（INFRA-578/588 自愈）必需，2026-09-02 INFRA-722：03:02 换新 PAT 时规格遗漏该权限，自愈 dispatch 全部 403，03:45 补权限后恢复（PAT 编辑权限值不变，无需重设 secret）。处置：核对 1Password 条目权限规格（Contents+PullRequests+Issues+**Actions**），编辑 PAT 补权限即可；若值也变则按权威值 `gh secret set` 重设两仓并手动 `gh workflow run` 拉起扫描器；告警 issue 由下个 heartbeat tick 自愈关闭 |
| `GitHub Actions is not permitted to create or approve pull requests` | token 用了 GITHUB_TOKEN，或仓库 Actions 权限被回退为 read 且禁止建 PR，检查 token 与仓库 Actions 设置 |
| Release PR 合并后没出 tag | 合并凭证不是真实用户/PAT（GITHUB_TOKEN 合并被递归防护吞掉 push 事件），用 DISPATCH_TOKEN 或本人凭证重新合并/手动 dispatch 补救 |

## 7. 发版公告链路

infra-core 每次 release 发布（含 patch）时自动广播升级公告到 Mac 侧 webhook，
由 `trigger-release.sh` 按消费方清单逐仓派发 droid 会话自动接单开 pin-bump PR。

### 链路要素

| 要素 | 值 |
|------|-----|
| 公告 URL | `https://ci-webhook.exa.edu.kg/hooks/release-broadcast`（repo secret `RELEASE_BROADCAST_URL`） |
| Hook ID | `release-broadcast`（`~/.factory/webhook/hooks.json` 条目） |
| 脚本 | `trigger-release.sh`（仓内源码 `webhook-scripts/trigger-release.sh`，经 `sync-webhook-scripts.sh` 同步部署到 `~/.factory/webhook/scripts/`） |
| 路由键 | `engineConsumer: true`（`~/.factory/config/repositories.yml` 仓条目） |
| 接单 skill | `release-gateway`（`~/.factory/skills/release-gateway/SKILL.md`） |
| 认证头 | `X-Release-Token: $RELEASE_BROADCAST_TOKEN`（repo secret，高熵随机值） |

### 核心语义

- **触发**：`on: release: types: [published]`，每次 release 全量含 patch
- **送达语义**：fire-and-forget——2xx 视为已送达路由层，非 2xx 终态（404 / 5xx / 网络失败）走告警路径（`::warning::` + best-effort PostHog 事件），**job 永不 fail**，发版流程永不因公告阻塞
- **per-tag 幂等**：锁文件 `~/.factory/webhook/locks/release-announce-{tag}.json`，锁已存在时跳过派发
- **逐仓错误隔离**：单仓失败（工作树脏 / pull 失败 / droid exec 异常）不影响其他仓，跳过原因记入日志
- **零权限 job**：`permissions: {}`，不 checkout 仓库，纯网络送达

### 已知限制

- **HTTP 200 ≠ 接单成功**：adnanh/webhook 对 trigger-rule 不满足的请求也返回 200，
  200 只证明公告已送达路由层，不证明规则命中或脚本执行
- **Mac 离线期间公告丢失**：靠下次发版或手动 reconcile 补齐
- **release 事件平台行为**：GitHub Actions 的 `on: release` 按 tag commit 解析
  workflow 文件——对 tag commit 早于 `release-announce.yml` 落地 main 的旧 release
  做 draft→publish 重发**不会触发公告**（2026-09-04 实证）。补救 = 手动 reconcile。
  该限制属 GitHub 平台行为而非实现缺陷，生产语义不受影响（release-please 自当前
  main 切新 tag，未来自然发版正常触发）

## 8. 演进路线

- M2：引擎移植（copy-not-move）——`src/infra_core/engine/` 落地 scanner 家族 + argparse（`--repo-root` / `--report-only`）
- M3：memory 规则包迁入 `packs/memory/`；version_sync 整体迁入 + resign 注入钩子
- M4：workflow 抽取为 reusable workflows + composite actions，消费仓切 thin caller
- M5：webhook 脚本同步源迁入
- M6：引擎仓自扫配置修复（INFRA-659）+ shared-workflows 退役（VAL-HARD-104）+ check_config_yml rule_packs 展开计数（v0.7.1/#104）
