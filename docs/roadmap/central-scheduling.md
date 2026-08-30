# 中央调度路线图（Central Scheduling Roadmap）

> 状态：路线图（未排期）。本文件只描述方向与约束，不引入任何行为变更。
> 依据：自进化层抽离 mission 架构 §1——「中央调度不在本期范围，仅 M6 出路线图文档」。
> 当前演进扫描的调度形态是 **per-repo 定时 thin caller**（各消费仓自带 `schedule:` 触发，
> 执行体委托本仓 reusable workflow）。中央调度的目标是把「何时 tick」从消费仓收拢到
> 组织级单一入口，「如何 tick」仍留在本仓引擎。

## 1. 现状盘点（per-repo thin-caller schedule inventory）

以下为 2026-08-30（M6 加固时点）两仓注册的全部 `schedule:` 触发，是中央化的迁移对象：

### 消费仓（hdot123-org/memory，thin caller 形态）

| workflow 文件 | workflow 名 | cron（UTC） | 用途 |
|---|---|---|---|
| `evolution-scan.yml` | Evolution Scan | `13,43 * * * *` | 演进扫描 tick（每 30 分钟双窗） |
| `evolution-heartbeat.yml` | Evolution Heartbeat | `47 */2 * * *` | 扫描自愈心跳（错峰 INFRA-578） |
| `auto-merge.yml` | Auto Merge | `*/10 * * * *` | 合并兜底扫描（另有 workflow_run 快路径） |
| `droid-review-watchdog.yml` | Droid Review Watchdog | `*/30 * * * *` | droid-review 卡死自愈 |
| `branch-cleanup.yml` | Branch Cleanup | `0 * * * *` | 孤立分支清扫（另有 PR closed 即时模式） |
| `qa.yml` | QA | `0 2 * * *` | 夜间全量回归 + coverage 门禁 |
| `release-please.yml` | Release Please | `0 4 * * *`、`0 12 * * *` | 发版 PR 维护 |

### 引擎仓（hdot123-org/infra-core，本仓自用）

| workflow 文件 | workflow 名 | cron（UTC） | 用途 |
|---|---|---|---|
| `auto-merge.yml` | Auto Merge | `*/30 * * * *` | 本仓合并兜底（workflow_run 快路径为主） |
| `branch-cleanup.yml` | Branch Cleanup | `0 * * * *` | 本仓分支卫生 |
| `qa.yml` | QA | `0 2 * * *` | 夜间全量回归 |
| `release-please.yml` | Release Please | `0 4 * * *`、`0 12 * * *` | 发版 PR 维护 |

### 现状痛点（中央化动机）

1. **cron 分散在各消费仓**：新增消费仓 = 复制 thin caller + 自带 cron，调度策略（错峰、
   限流、窗口避开平台投递抑制）无法组织级统一调整。
2. **平台 schedule 投递抑制无单点观测**（2026-08-30 org 级 schedule 抑制事件实证）：
   各仓各自静默丢 tick，需要跨仓对照才能判别平台面 vs 仓库面。
3. **tick 预算分散**：scanner 的 tick-budget/tick-tracker 是仓内状态，org 视角无全局限流。

## 2. 目标架构（target）

```
┌────────────────────────────────────────────────────────────┐
│ central-scheduler（org 级单一入口，形态待定，候选：          │
│   infra-core 内专用 workflow + 仓库注册表 Actions variable）│
│   输入：repo × workflow × 窗口 的调度矩阵（注册表驱动）      │
│   行为：到点 → gh workflow dispatch <consumer-repo>         │
│         <thin-caller.yml>（复用现有 dispatch input 面）      │
│   观测：单一 run 流水可查询全 org 的 tick 交付/丢弃         │
└────────────────────────────────────────────────────────────┘
              │ workflow_dispatch（事件面不变）
              ▼
┌────────────────────────────────────────────────────────────┐
│ 消费仓 thin caller（保留）：workflow 名/契约字节级不动，      │
│ 仅把 `schedule:` 触发降级为可一键重启的备用面                │
└────────────────────────────────────────────────────────────┘
```

关键决策点（进入实施 mission 前需裁决）：

- **调度矩阵存放**：Actions variables（org context）vs 仓内 `central-schedule.yml` 声明文件。
  铁律约束：仓库注册表等组织信息不落本仓文件（走 Actions variables）。
- **dispatch 面复用**：thin caller 已声明的 `workflow_dispatch` inputs 是现成入口，
  中央调度器只负责「何时」不改变「怎么调」。
- **tick 去重**：中央调度与 per-repo schedule 并存窗口内，scanner tick-tracker 天然
  幂等（同窗口重复 tick 被预算层吸收），但 watchdog/auto-merge 无 tick 预算，
  并存窗只允许**单边活跃**（见 §4）。

## 3. 迁移草图（migration sketch）

按风险升序、每步一个原子 PR，与 M4 门禁切换同纪律：

1. **只读观测窗**：中央调度器上线但只记录（对每个注册 tick 输出「将 dispatch」日志，
   不真发），对照各仓 schedule 实际 run，校准窗口矩阵。
2. **单 workflow 试点**：选 Evolution Heartbeat（最低风险：自愈性质，重复 tick 无害），
   中央 dispatch 接管，消费仓 `schedule:` 保留但错峰挪后 1 小时作为兜底。
3. **逐个推广**：heartbeat → evolution-scan → branch-cleanup → watchdog → auto-merge。
   每步牺牲验证：中央 dispatch 真实触发一次 + 消费仓 run 到达 + 引擎行为正常。
   （evolution-scan 的验证只能在工作时段观察定时行为，禁止人为制造 live tick。）
4. **QA/release-please 不收编**：夜间回归与发版节奏是仓内事务，保留 per-repo schedule。

## 4. 回滚草图（rollback sketch）

中央调度的回滚必须满足「任何时刻门禁完整可用」，与 M4/M6 回滚纪律同构：

1. **单点回退**：中央调度器本身是一个（或一组）infra-core workflow——`gh workflow disable`
   即停（M6 disable/enable 演练已实证该操作路径），消费仓 thin caller 的 `schedule:`
   兜底面仍在（试点起即保留），停用中央器后下一 cron 窗自动恢复 per-repo 供给。
2. **代码回退**：中央化 PR 原子可 revert；revert 顺序约束与 VAL-CROSS-009 同款——
   若中央化 PR 同时改了 thin caller 文件（如 schedule 注释面），revert 中央化 PR
   与 revert 对应消费仓 PR 必须同窗完成，避免悬空引用。
3. **webhook 面不受中央化影响**：webhook 生产同步的回滚走独立 runbook
   （PROD_ROOT 沙箱演练 + infra-core tag N-1 恢复源），与调度层正交。
4. **回滚验收**：disable 中央器 → 观察下一 schedule 窗各仓 run 恢复创建 →
   命名契约测试（两仓 test_ci_config 家族）全绿。

## 5. 中央化必须幸存的命名/契约不变量（naming invariants）

以下字符串构成跨仓契约网（architecture §3），中央化任何一步不得触碰：

| 契约 | 值 | 中央化风险点 |
|---|---|---|
| workflow 名 | `Evolution Scan` / `Evolution Heartbeat` / `Auto Merge` / `Droid Review Watchdog` / `Branch Cleanup` / `CI` / `QA` / `Droid Auto Review` / `Evolution Governance` / `Setup Labels` | 中央 dispatch 以文件名为入口，workflow_run 监听以 workflow 名匹配——名字漂移即静默断链 |
| workflow 文件名 | `evolution-scan.yml` | heartbeat 自愈用 `SCANNER_WORKFLOW` 常量做 `gh run list --workflow` 精确匹配（engine `evolution_heartbeat.py`）；中央化不得要求改名 |
| check 名 | `droid-review`（job key）、`Block non-owner governance modifications`（job 显示名）、`ci-ok` | 与调度正交，但中央化 PR 若顺手动 thin caller job 结构即违约 |
| artifact 前缀 | `droid-review-debug-` | watchdog quota-sweep startswith 过滤 |
| 触发面 | thin caller 的 `workflow_dispatch` inputs 契约 | 中央 dispatch 是该面的第一个程序化消费方；inputs 变更 = 跨仓契约变更，需双写过渡 |
| branch protection | contexts `{ci-ok, droid-review, Block non-owner governance modifications}` | 全程零修改（本 mission 既有铁律） |

## 6. 明确不做（本路线图不覆盖）

- 不在本仓引入外部调度器/第三方 cron 服务（org 内 GitHub Actions 单一执行面）。
- 不做跨 org 多租户。
- 不改 scanner/heartbeat 引擎的 tick 语义（中央化只换触发源，不换执行体）。

## 7. 后续

进入实施前需要：独立 mission 立项、调度矩阵 schema 评审、单 workflow 试点窗口选择
（避开平台 schedule 投递抑制高发时段）。本文件仅记录方向，不构成排期承诺。
