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
| workflow 名（未来） | `Droid Auto Review` / `QA` | auto-merge、watchdog |
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

`CI` workflow 共 19 个 job：既有 4 个（命名契约）+ guards + 4 个专项测试组 + 2 个分域 mypy + 3 个 advisory + 基础层补齐 4 个 + ci-ok 聚合。结构契约由 `tests/test_ci_structure_contract.py` 锁定（job 集合快照只对齐当前 main，后续 ci.yml 变更由对应 feature 同步该测试）。

| 门禁 | workflow | 说明 |
|------|----------|------|
| pytest | `CI` | 单元测试 + 覆盖率地板（`--cov-fail-under`，ramp-up 计划见 pyproject.toml） |
| ruff | `CI` | lint + format 检查 |
| actionlint | `CI` | workflow 语法检查 |
| mypy | `CI` | mypy（历史 check 名保留） |
| guards | `CI` | 4 个守卫脚本：边界污染 / 文档分类 / fix-has-test / PR 引用一致性（后两个 PR-only，依赖 GH_TOKEN） |
| security-tests / schema-tests / integration-tests / e2e-tests | `CI` | 专项测试组，按 pytest marker 分组（`-m <marker> -n 4 --no-cov`）；e2e 附 CLI 冒烟 |
| mypy-src-strict / mypy-scripts-strict | `CI` | 分域 `mypy --strict`（src/infra_core 与 scripts/） |
| advisory-dependency-security-scan / advisory-deptry | `CI` | advisory 扫描（pip-audit / deptry），INFRA-595 零红：无 `continue-on-error`，失败即红 check-run，ci-ok 按 `.result` 阻断（曾有 `continue-on-error` 时 `.result` 恒为 success，判定空转，run 33129232081 实证） |
| advisory-telemetry-audit | `CI` | advisory：遥测覆盖率审计（`scripts/audit_telemetry_coverage.sh`），INFRA-595 零红：无 `continue-on-error`，失败即红，ci-ok 按 `.result` 阻断（同上） |
| shellcheck | `CI` | shell 脚本静态检查 |
| health-check | `CI` | CI 健康自检（`scripts/ci_health_check.sh`） |
| repo-consistency | `CI` | 仓库交付一致性检查（`scripts/repo_health_check.sh --ci`） |
| business-policy-tests | `CI` | 业务策略测试组（`-m business_policy -n 4 --no-cov`） |
| ci-ok | `CI` | 聚合（branch protection required check），逐项显式阻断全部 18 个前置 job（含 advisory，按 `.result`；INFRA-595），另有 GitHub API 全 check-runs 零红扫描双保险 |
| governance | `Evolution Governance` | 受保护路径 owner 门禁（pull_request_target，执行 shipped governance-check action） |
| release | `Release Please` | 非门禁：发版管道（schedule/push(paths)/dispatch，DISPATCH_TOKEN，详见第 6 节） |

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
| `GitHub Actions is not permitted to create or approve pull requests` | token 用了 GITHUB_TOKEN，或仓库 Actions 权限被回退为 read 且禁止建 PR，检查 token 与仓库 Actions 设置 |
| Release PR 合并后没出 tag | 合并凭证不是真实用户/PAT（GITHUB_TOKEN 合并被递归防护吞掉 push 事件），用 DISPATCH_TOKEN 或本人凭证重新合并/手动 dispatch 补救 |

## 7. 演进路线

- M2：引擎移植（copy-not-move）——`src/infra_core/engine/` 落地 scanner 家族 + argparse（`--repo-root` / `--report-only`）
- M3：memory 规则包迁入 `packs/memory/`；version_sync 整体迁入 + resign 注入钩子
- M4：workflow 抽取为 reusable workflows + composite actions，消费仓切 thin caller
- M5：webhook 脚本同步源迁入
