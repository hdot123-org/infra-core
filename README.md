# infra-core

组织级演进引擎：自进化/审计/门禁体系的共享基础设施。

## 定位

infra-core 是从 memory-core 抽离的组织级共享引擎，提供：

- **引擎层**：scanner、utils、adapters、heartbeat、droid-review 分片/发布
- **规则包**：daily-audit、layout-audit、hygiene、self-audit（memory 等）
- **webhook 脚本**：manifest + trigger 家族（生产同步源）
- **CI/CD**：reusable workflows + composite actions
- **CLI**：infra-cli 统一入口

## 安装

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
```

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

## 架构

```
infra-core/
├── src/infra_core/
│   ├── engine/          # 自进化引擎（scanner/utils/adapters/heartbeat）
│   ├── packs/           # 规则包（memory 等）
│   └── cli.py           # infra-cli 统一入口
├── actions/             # composite actions
├── .github/workflows/   # reusable workflows
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
