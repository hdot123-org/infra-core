# webhook-scripts/cross-dir — 锚点依赖链生产部署副本

本目录是 **生产部署血统** 的逐字节快照（2026-08-30 M5 迁移时点自
memory-core `scripts/` 复制），由 `webhook-scripts/MANIFEST.sh` 的
`CROSS_DIR_MAPPINGS` 声明、`sync-webhook-scripts.sh` 同步到生产目录
（`~/.factory/webhook/scripts/`）。

## 与 src/infra_core/engine/ 的关系

| 文件 | 本目录（部署血统） | engine/（引擎演化线） |
|---|---|---|
| extract_anchor.py | 生产同步源，sha256 = 生产副本 | 包内模块，含 ruff 格式化差异 |
| evolution_utils.py | 同上 | 含 INFRA-601 `gh_repo_args()` 等引擎侧增强 |
| evolution_adapters.py | 同上 | 当前逐字节一致 |
| anchor_gate.py | 同上 | 含 ruff 格式化差异 |

**不要用 engine/ 版本替换本目录**：替换会破坏与生产部署文件的 sha256
一致性（`--check` 漂移误报），且属行为变更，须走独立行为等价评审 PR。
背景：INFRA-357（锚点依赖链必须与调用方一同受管部署）。
