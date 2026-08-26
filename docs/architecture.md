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

- workflow `Evolution Governance` 在 PR 触碰受保护路径时要求 owner 身份
- 受保护路径（默认）：`.evolution/**`、`.github/workflows/**`、`src/infra_core/engine/**`、`webhook-scripts/**`
- 判定核心在 `src/infra_core/governance.py`（fail-closed：作者未知即拒绝；路径匹配用 fnmatch，目录模式覆盖目录条目本身）
- 本地 dry-run：`python -m infra_core.governance --author <login> --files <path>...`（退出码 0 放行 / 1 拒绝 / 2 输入错误）
- composite action `actions/governance-check` 参数化 owner-login / protected-patterns，供消费仓复用

## 4. CLI（infra-cli）

`infra-cli` 是统一命令行入口。M1 为骨架态：子命令 `scan` / `audit` / `version-sweep` 框架就位，`--help` 安全零副作用，未实现子命令优雅失败（非零退出 + 人类可读诊断，无 traceback）。

## 5. 门禁矩阵（M1）

| 门禁 | workflow | 说明 |
|------|----------|------|
| pytest | `CI` | 单元测试 |
| ruff | `CI` | lint + format 检查 |
| actionlint | `CI` | workflow 语法检查 |
| ci-ok | `CI` | 聚合（branch protection required check） |
| governance | `Evolution Governance` | 受保护路径 owner 门禁（pull_request_target） |

## 6. 演进路线

- M2：引擎移植（copy-not-move）——`src/infra_core/engine/` 落地 scanner 家族 + argparse（`--repo-root` / `--report-only`）
- M3：memory 规则包迁入 `packs/memory/`；version_sync 整体迁入 + resign 注入钩子
- M4：workflow 抽取为 reusable workflows + composite actions，消费仓切 thin caller
- M5：webhook 脚本同步源迁入
