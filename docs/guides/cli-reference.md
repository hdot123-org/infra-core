# infra-* CLI 参考（memory 规则包）

INFRA-571 迁入的 memory 规则包工具以独立 `infra-*` 命令分发，同时由
`src/infra_core/packs/memory/pack.py` 注册进 `rule_packs`，供
`infra-cli scan` 调度（entry point 组 `infra_core.packs`）。

入口点契约由 `tests/test_memory_pack_entrypoints.py` 锁定：console scripts
声明、pack 命令模板与脚本名一致性、entry point 发现 API。

## 命令一览

| 命令 | 模块 | 用途 | 默认超时 |
|------|------|------|----------|
| `infra-daily-audit` | `infra_core.packs.memory.daily_audit` | 每日 KB 审计（完整性/新鲜度） | 120s |
| `infra-layout-audit` | `infra_core.packs.memory.layout_audit` | 项目布局审计（结构/遗留残留） | 60s |
| `infra-hygiene-audit` | `infra_core.packs.memory.hygiene` | 代码卫生（静默吞异常/TODO/重复块） | 300s |
| `infra-error-patterns` | `infra_core.packs.memory.error_patterns` | 错误模式检测（`*-errors.jsonl`） | 120s |
| `infra-self-audit` | `infra_core.engine.evolution_self_audit` | 演进系统自审计（10 项检查） | 60s |

## 通用旗标（M2 兼容约定）

- `--repo-root <path>` / `--target <path>`：目标路径。迁移时已去除
  memory-core 时代的硬编码宿主路径；`infra-layout-audit` 两者互为别名
  （`--repo-root` 为 `--target` 别名）。
- `--json`：机器可读输出（scanner 适配器按 JSON 消费）。
- `--report-only`：只读模式（`infra-daily-audit` 在该模式下不写默认
  审计目录，仅 `--output` 显式给定时落盘）。

## 用法示例

```bash
infra-daily-audit --repo-root /path/to/repo --json
infra-layout-audit --target /path/to/project --json
infra-hygiene-audit --repo-root /path/to/repo --json
infra-error-patterns --repo-root /path/to/repo --json
infra-self-audit --repo-root /path/to/repo --json
```

## 消费方式（scanner 配置）

消费仓通过 `.evolution/config.yml` 引用规则包：

```yaml
rule_packs:
  - pack: memory
```

pack 内工具自动并入 `audit_tools`；同名 inline 条目可覆盖 pack 定义，
`enabled: false` 可禁用单个工具（详见 engine `resolve_rule_packs`）。
