# 消费仓接入指南（Consumer Onboarding）

把组织级演进引擎（scanner / 审计 / 门禁）接入一个新仓库，只需要三件事：
复制 thin-caller workflow 模板、声明 `.evolution/config.yml`、配置 secrets。
执行体全部由 `hdot123-org/infra-core` 的 reusable workflows / composite actions
承载，消费仓**零 pip 安装、零脚本副本**（引擎版本由消费仓 `pip install -e .`
连带安装的 `infra-core` 依赖决定，见 §5）。

模板目录：[`docs/onboarding/templates/`](./templates/)（可整目录复制）。

---

## 1. 前置条件

- GitHub 仓（org 内私有仓亦可引用本公开引擎）；
- runner 标签 `[self-hosted, pve-linux]` 可用（org 共享池 `memory-runnerz`）；
- 仓owner能配置 Actions secrets / variables。

## 2. Thin-caller workflow 模板

| 模板文件 | workflow 名（字节级契约） | 触发 |
|---|---|---|
| `templates/evolution-scan.thin-caller.yml` | `Evolution Scan` | schedule `13,43 * * * *` + dispatch |
| `templates/evolution-heartbeat.thin-caller.yml` | `Evolution Heartbeat` | schedule `47 */2 * * *` + dispatch |
| `templates/branch-cleanup.thin-caller.yml` | `Branch Cleanup` | schedule `0 * * * *` + `pull_request [closed]` + dispatch |
| `templates/evolution-governance.thin-caller.yml` | `Evolution Governance` | `pull_request_target [main]` |

**命名契约（NEVER break）**：workflow `name:` 与 job 显示名是 auto-merge /
branch protection / watchdog 的隐式契约网，复制模板后**不要改名**。
governance 模板的 job `name: Block non-owner governance modifications`
是 branch protection required check 的精确名。

安装：

```bash
cp docs/onboarding/templates/*.thin-caller.yml <你的仓>/.github/workflows/
cp docs/onboarding/templates/actionlint.yaml <你的仓>/.github/
# 去掉 .thin-caller 后缀
cd <你的仓>/.github/workflows
for f in *.thin-caller.yml; do mv "$f" "${f%.thin-caller.yml}.yml"; done
```

> `.github/actionlint.yaml` 声明自建 runner label（`pve-linux`），缺了它
> `actionlint` 会对模板的 `runs-on` 报 unknown-label。本地验证需在 git 仓内
> 执行（actionlint 以 repo root 定位该配置）。

## 3. `.evolution/config.yml`

消费仓根目录声明规则包（governance 保护该文件，非 owner 改动会被
`Evolution Governance` 门禁拒绝）：

```yaml
# Human-maintained governance config. Scanner reads only, never writes.
max_issues_per_tick: 1
max_self_audit_issues_per_tick: 1
max_code_hygiene_issues_per_tick: 1
severity_order: [critical, warning, info]
dedup_label: evolution-found
isolation_threshold: 3
failure_label: evolution-isolated

# 规则包：展开 infra_core.packs.memory 的 ToolSpec 清单
# （daily_kb_audit / audit_layout / code_hygiene_audit / error_patterns /
#   evolution_self_audit，命令均为 infra-* 入口，--repo-root 指向扫描目标）
rule_packs:
  - pack: memory

# 协议自有工具以 inline audit_tools 声明（memory-* 命令属于消费仓自身协议栈）
audit_tools:
  - name: consistency_check
    command: "memory-consistency-check --json"
    output_format: json

snapshot_limit: 100
```

要点：

- `rule_packs` 同名 inline 条目**按名覆盖** pack 定义（override-by-name）；
  `enabled: false` 显式禁用单个工具（私用项目差异化场景）。
- registry 模式的 error_patterns（`output_format: registry_jsonl` +
  `source_file`）是 memory-core dogfood 特有覆盖；一般消费仓直接用 pack
  默认（stdout jsonl）即可。

## 4. Secrets 清单

| Secret | 用途 | 哪些模板需要 |
|---|---|---|
| `DISPATCH_TOKEN` | PAT（owner 身份）：Issue/label 写入、auto-merge、self-heal | scan / heartbeat / branch-cleanup / auto-merge |
| `FACTORY_API_KEY` | droid-review BYOM 调用 | droid-review 系 |
| `NVIDIA_KONG_PROXY_KEY` | droid-review BYOM 内网代理 | droid-review 系 |
| `LINEAR_API_KEY` | Linear 状态核验（auto_close_resolved fail-closed） | scan / branch-cleanup |
| `N8N_CI_WEBHOOK_URL` | CI 完成后 n8n webhook 路由 | 仅宿主 webhook 子系统 |
| `N8N_CI_TOKEN` | n8n webhook 认证 | 仅宿主 webhook 子系统 |

> 前四个是消费仓接入演进引擎所需；后两个仅宿主 webhook 子系统使用。
> Values 不落仓库、不落日志；`gh secret set <NAME>` 写入。

Repo **variables**（`gh api repos/<org>/<repo>/actions/variables`）按需配置：
`BRANCH_AGE_MERGED_HOURS` / `BRANCH_AGE_CLOSED_HOURS` /
`BRANCH_AGE_ORPHAN_HOURS`（branch-cleanup 阈值）、`LINEAR_PROJECT_<REPO>_ID`
（Linear 项目同步）、droid-review 预算组（`SHARD_MAX_FILES` 等，缺省回退内置默认值）。

## 5. 引擎版本（pip 依赖）

消费仓若安装 memory-core 协议栈，`pyproject.toml` 以 **tag 锁定** 引擎版本：

```toml
dependencies = [
    "infra-core @ git+https://github.com/hdot123-org/infra-core.git@v0.6.0",
]
```

公开仓免认证拉取（实测 ~40s）。升级 = bump tag 字符串。workflow_call
inputs/secrets 一律 **snake_case**（如 `dispatch_token`、`shard_max_files`）。

## 6. 升级分发（公告规则）

infra-core 每次 release 发布（含 patch）后自动广播升级公告，已声明的消费仓由
Mac 侧派发 droid 会话自动接单开 pin-bump PR，走 CI → auto-merge 闭环。

### 接入方式

在宿主 `repositories.yml` 的仓条目中声明 `engineConsumer: true` 即接入自动升级，
除此之外**零预埋**——消费仓不需要安装任何 workflow、脚本或 secret。

### 七项语义

① **声明即接入**：`engineConsumer: true` 是唯一路由依据，声明后下一次 release
公告即向该仓派发接单会话。

② **接单形态**：下游 droid 会话按 `release-gateway` skill 配方全仓搜索
infra-core pin 面、bump 到新 tag、本地自测后开 PR。消费仓**零预埋**——不需要
提前安装任何 workflow、脚本或配置。

③ **公告粒度**：每次 release 全量含 patch，无任何过滤（无论 release 由
release-please 还是人工发布、无论 minor 还是 patch）。

④ **同 tag 幂等**：同一 tag 重复公告不产生重复接单——per-tag 幂等锁拦截，
锁已存在时跳过派发、零副作用。

⑤ **Mac 离线兜底**：Mac 离线期间公告会丢失，补齐方式有二：
- 下次发版时自动补齐（新 tag 公告正常触发）
- 手动 reconcile：以相同 payload 形状对 webhook 端点重发 curl 即可
- **重试窗口**：仅有 run 内 15-30s 有限 curl 重试（--retry 3），窗口级离线不重试不补发

⑥ **已知限制**：
- **HTTP 200 ≠ 接单成功**：webhook 对 trigger-rule 不满足的请求也返回 200
  （adnanh/webhook 实证），200 只证明公告已送达路由层，不证明规则命中或脚本执行
- **离线窗口公告会丢**：Mac 侧 webhook 服务不可达期间（离线/崩溃）的公告
  不会重试或补发，靠 §6 兜底路径补齐
- **公网公告 Cloudflare Access 302（临时，Service Token 生效前兜底=手动 reconcile）**：
  公网公告当前经 Cloudflare Access 网关拦截返回 302 跳转登录页（Bypass 缺 GitHub Actions
  段）。仓内侧已适配可选 CF-Access-Client-Id/Secret 头（引用 secrets CF_ACCESS_CLIENT_ID /
  CF_ACCESS_CLIENT_SECRET，secrets 未配置时优雅跳过），Service Token 与 gate 策略由用户侧
  落地。生效前兜底 = 手动 reconcile（对 Mac 本机 webhook 端点直接 curl，绕过公网）
- **release 事件平台行为**：GitHub Actions 的 `on: release` 按 tag commit
  解析 workflow 文件——对 tag commit 早于 `release-announce.yml` 落地 main 的
  旧 release 做 draft→publish 重发**不会触发公告**（2026-09-04 实证：
  published ReleaseEvent 已发、workflow state=active、历史零 run）。补救 =
  手动 reconcile（见 §6 兜底路径）。该限制属 GitHub 平台行为而非实现缺陷，
  生产语义不受影响（release-please 自当前 main 切新 tag，未来自然发版正常触发）

⑦ **与 §5 手动 bump 指引的边界划分**：
- **已声明 `engineConsumer: true` 的仓**：升级由公告自动接单，无需按 §5 手动
  bump tag 字符串——接单会话自动完成全仓搜索 + bump + 测试 + PR
- **未声明的仓**：沿用 §5 手动 bump 指引，自行跟踪 infra-core release 并手动
  更新 pin tag
- 两处不矛盾：自动接单是 §5 手动操作的自动化替代，适用于已声明的消费仓

### 送达语义

- **2xx 终态**：视为公告已送达路由层，无告警
- **非 2xx 终态**（404 / 5xx / 网络失败）：走告警路径（`::warning::` + best-effort
  PostHog 事件），发版流程**不 fail**——公告永不阻塞发版

### 逐仓错误隔离

派发层逐仓执行，单仓失败（工作树脏 / pull 失败 / droid exec 异常）不影响其他仓，
跳过原因记入日志。

**工作树脏检测范围**：仅覆盖 tracked 改动（git status --porcelain 检测已跟踪文件的修改/删除），
untracked 文件不拦截派发（会话层保护兜底，session 8c635f22 实证无害）。

## 7. 验证接入

```bash
# 模板静态检查
actionlint .github/workflows/*.yml
# 本地报告模式试扫（不写 GitHub）
pip install -e '.[dev]'
infra-cli scan --report-only --repo-root . --output /tmp/scan.json
```

首次 PR 触发 `Evolution Governance`（若接入该门禁）与 scan 定时器后，
在 Actions 页确认 workflow 注册名与本表一致。
