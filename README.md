# infra-core

组织级演进引擎：自进化/审计/门禁体系的共享基础设施。

## 定位

infra-core 是从 memory-core 抽离的组织级共享引擎，提供：

- **引擎层**：scanner、utils、adapters、heartbeat、self-audit、version-sync、锚点助手、droid-review 分片/发布（单源 `src/infra_core/engine/`）
- **规则包**：memory pack（含 daily-audit、layout-audit、hygiene、error-patterns 等规则模块）
- **webhook 脚本**：manifest + trigger 家族（生产同步源）
- **CI/CD**：reusable workflows + composite actions
- **CLI**：infra-cli 统一入口
- **发版公告链路**：引擎发版时自动广播升级公告，消费仓自动接单开 pin-bump PR（详见[发版公告与下游自动接单](#发版公告与下游自动接单)）

## 安装

要求 Python 3.12（`requires-python = "==3.12.*"` 锁定）。

```bash
# 从源码安装（开发模式）
pip install -e .

# 从 GitHub 安装（公开仓库，免认证）
pip install git+https://github.com/hdot123-org/infra-core.git@<tag>

# 安装开发依赖
pip install -e ".[dev]"
```

## 使用

### CLI 命令

```bash
# 查看帮助
infra-cli --help

# 扫描仓库（只读模式，不创建 issue）
infra-cli scan --report-only --repo-root /path/to/repo

# 审计
infra-cli audit --target /path/to/project

# 版本同步
infra-cli version-sweep --target /path/to/project

# venv 环境工具组（创建独立 venv 并安装依赖）
infra-cli venv create --path .venv --extras dev
```

独立审计入口（随包安装提供）：`infra-self-audit`、`infra-daily-audit`、`infra-layout-audit`、`infra-hygiene-audit`、`infra-error-patterns`。

### 规则包

消费仓通过 `.evolution/config.yml` 声明使用的规则包：

```yaml
rule_packs:
  - pack: memory

audit_tools:
  - name: consistency_check
    command: "memory-consistency-check --json"
    output_format: json
```

### 消费仓接入

新仓库接入引擎只需三件事：复制 thin-caller workflow 模板、声明 `.evolution/config.yml`、配置 secrets，消费仓零 pip 安装、零脚本副本。详见[消费仓接入指南](docs/onboarding/consumer-onboarding.md)，thin-caller 模板位于 `docs/onboarding/templates/`。


## 发版公告与下游自动接单

infra-core 发版时，通过两条触发面（推送 + 轮询）自动广播升级公告，消费仓（`engineConsumer: true`）自动接单开 pin-bump PR，CI → auto-merge 闭环。

**链路要素**：
- **推送触发面**：`release-announce.yml` workflow（on: release published）POST 到 Mac 侧 webhook → `trigger-release.sh` 派发 droid session
- **轮询触发面**（默认）：`poll-releases.sh` + launchd 定时轮询 GitHub Releases API，发现新 release 后调用 `trigger-release.sh`
- **接单 skill**：`release-gateway` skill 指导 droid 升级消费仓 infra-core pin（pyproject git+、workflow @tag、测试断言、文档等）
- **幂等保证**：per-tag 锁文件，重复触发零副作用
- **双触发面共存**：推送 + 轮询经幂等锁天然共存，推送面可休眠（secret 缺失时优雅跳过）

**消费仓接入**：在 `~/.factory/config/repositories.yml` 中添加 `engineConsumer: true` 标记即可自动接收升级公告。

详细架构：[`docs/architecture.md` §7 发版公告链路](docs/architecture.md) § C9 轮询触发面；消费仓接入指南：[`docs/onboarding/consumer-onboarding.md`](docs/onboarding/consumer-onboarding.md)。

## 架构

```
infra-core/
├── src/infra_core/
│   ├── engine/          # 自进化引擎单源（scanner/utils/adapters/heartbeat/self-audit/version-sync/锚点助手）
│   ├── packs/           # 规则包（memory 等，经 entry points 发现）
│   ├── shell/           # shell 辅助层（auto-merge/branch-cleanup 家族源码）
│   ├── governance.py    # 治理自检（受保护路径修改判定，fail-closed）
│   └── cli.py           # infra-cli 统一入口
├── actions/             # composite actions（auto-merge / branch-cleanup / droid-review-aggregate / governance-check）
├── .github/workflows/   # reusable workflows + CI/QA 门禁
├── webhook-scripts/     # webhook 脚本（生产同步源）
└── tests/               # 测试套件
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check .
ruff format --check .

# GitHub Actions 检查
actionlint
```

## 治理自检 dry-run

governance 门禁（workflow `Evolution Governance` + composite action `actions/governance-check`）的判定核心可本地模拟验证（fail-closed、路径感知）：

```bash
# 非 owner 修改受保护路径 → 退出码 1（拒绝）
python -m infra_core.governance --author someone-else --files .evolution/config.yml

# 非 owner 修改普通文件 → 退出码 0（放行）
python -m infra_core.governance --author someone-else --files README.md

# owner 修改受保护路径 → 退出码 0（放行）
python -m infra_core.governance --author hdot123 --files .evolution/config.yml
```

## 命名契约

以下字符串构成隐式契约网络，任何一处改动会静默杀死 auto-merge/watchdog：

- workflow 名：`Droid Auto Review`、`Evolution Governance`、`CI`、`QA`
- check 名：`droid-review`（job key）、`Block non-owner governance modifications`（governance job 显示名）
- artifact 前缀：`droid-review-debug-`
- workflow 文件名：`evolution-scan.yml`

详见 [architecture.md](docs/architecture.md)。

## License

MIT
