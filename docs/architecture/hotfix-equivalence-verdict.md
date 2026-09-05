# 热修复等价性裁决：09-02 comment-UUID 热修复

**裁决结论：等价无需恢复**
**日期**：2026-09-06
**裁决人**：mission worker (hotfix-equivalence-verdict)

## 问题

2026-09-02 的 comment-UUID 热修复（`resolve_issue_ref()` 增加 `comment(id:)` 反查父 issue 逻辑）在一次未经回填的 sync 中被覆盖丢失。需要裁决：该热修复的丢失是否造成真实功能丢失。

## 三方证据

### 证据 1：备份热修复逻辑

**文件**：`~/.factory/webhook/scripts/trigger-droid.sh.bak-comment-uuid-20260902` L205-232（热修复前备份，含 comment(id:) 反查逻辑）
**代码源**：`~/.factory/webhook/scripts/.sync-backups/trigger-droid.sh.bak.20260905-012303` L205-239（覆盖前快照，与 bak-comment-uuid 文件 diff 仅 3 处 extract_anchor.py 路径差异，热修复逻辑完全一致）

`resolve_issue_ref()` 函数内嵌 Python：

```python
uuid = '$issue_uuid'
# Comment webhook 事件携带的是评论 UUID：先按 comment 反查所属 issue，
# 查不到（说明本来就是 issue UUID）再回落 issue 直查（2026-09-02 修复）
def gql(q):
    # ... Linear GraphQL request ...
try:
    issue = None
    try:
        d = gql('{ comment(id: \"%s\") { issue { identifier team { key } title } } }' % uuid)
        issue = d.get('data', {}).get('comment', {}).get('issue') or {}
    except Exception:
        pass
    if not issue.get('identifier'):
        d = gql('{ issue(id: \"%s\") { identifier team { key } title } }' % uuid)
        issue = d.get('data', {}).get('issue', {}) or {}
    # ... print identifier|team_key|title ...
```

**热修复行为**：收到 UUID → 先按 comment 查父 issue → 查不到再按 issue 直查。

### 证据 2：现行 trigger-droid.sh 直查路径

**生产文件**：`~/.factory/webhook/scripts/trigger-droid.sh` L205-224
**仓库文件**：`webhook-scripts/trigger-droid.sh` L205-224（sha256 一致）

```python
query = '{ issue(id: "%s") { identifier team { key } title } }' % "$issue_uuid"
# ... 直接 issue(id:) 查询，无 comment(id:) 前置尝试 ...
```

**现行行为**：收到 UUID → 直接按 issue 查 → Comment UUID 不是 Issue UUID → GraphQL 返回空 → 解析失败。

### 证据 3：CF 网关 Linear comment 载荷处理

**文件**：`<cf-repo>/webhook/worker.js`

**路由逻辑**（L26-35）：
```javascript
if (linearDetect.resourceType === "Issue" || linearDetect.resourceType === "Comment") {
    return {
        action: "forward",
        route: "linear-to-droid",
        event: `linear-${linearDetect.resourceType.toLowerCase()}`,
        path: "/hooks/linear-to-droid",
        tokenSecret: "<LINEAR_WEBHOOK_TOKEN>"
    };
}
```

**载荷重建**（L342-351）：
```javascript
if (linearDetect.isLinear && (linearDetect.resourceType === "Issue" || linearDetect.resourceType === "Comment")) {
    const reconstructed = {
        action: payload.action,
        type: payload.type,
        data: payload.data
    };
    forwardBody = JSON.stringify(reconstructed);
}
```

**结论**：网关对 Comment 和 Issue 事件一视同仁地转发，**不做任何 UUID 翻译**。Comment 事件的 `data.id` = 评论 UUID，`data.identifier` = null，原样传递到 Mac 侧 trigger-droid.sh。

## 执行路径分析

### hooks.json 参数映射

`~/.factory/webhook/hooks.json` L3-26（linear-to-droid hook）：
- `$3` (ISSUE_REF) ← `payload.data.identifier` → Comment 事件为 **null**
- `$4` (ISSUE_UUID) ← `payload.data.id` → Comment 事件为 **评论 UUID**

### 路径对比

#### 路径 A（当前，无热修复）— Comment.create 事件

| 步骤 | 行号 | 行为 | 结果 |
|------|------|------|------|
| 1 | L680 | `ISSUE_REF="" && ISSUE_UUID=""`？ | 否（UUID 有值） |
| 2 | L686 | `ISSUE_REF="" && ISSUE_UUID≠""`？ | **是**，进入 resolve_issue_ref() |
| 3 | L199-224 | `issue(id: <comment_uuid>)` | GraphQL 失败（comment UUID 不是 issue UUID）|
| 4 | L688 | RESOLVED="" | ISSUE_REF 仍空 |
| 5 | L710 | `if [ -z "$ISSUE_REF" ]` → ERROR | **exit 0**，附 error log + PostHog `ref_resolution_failed` |

**实际效果**：Comment.create 被跳过，不触发 droid exec。但产生一条错误日志和一个 PostHog 告警事件。

#### 路径 B（备份，有热修复）— Comment.create 事件

| 步骤 | 行号 | 行为 | 结果 |
|------|------|------|------|
| 1 | L680 | `ISSUE_REF="" && ISSUE_UUID=""`？ | 否 |
| 2 | L686 | `ISSUE_REF="" && ISSUE_UUID≠""`？ | **是**，进入 resolve_issue_ref() |
| 3 | 备份 L218-224 | `comment(id: <comment_uuid>)` → 成功获取父 issue | RESOLVED="INFRA-XXX\|INFRA\|title" |
| 4 | L688 | RESOLVED 有值 | ISSUE_REF="INFRA-XXX", TEAM_KEY="INFRA" |
| 5 | L713 | Team whitelist pass | TEAM_KEY=INFRA → 通过 |
| 6 | L729 | `TYPE=Comment && ACTION=create` | **GAP-D 过滤** → **exit 0** |

**实际效果**：Comment.create 被 GAP-D 干净地跳过，不触发 droid exec。无错误日志，无 PostHog 告警。

#### 两条路径的终态对比

| 维度 | 路径 A（无热修复） | 路径 B（有热修复） |
|------|------|------|
| droid exec 是否触发 | 否 | 否 |
| 退出码 | 0 | 0 |
| 错误日志 | 有（"Failed to resolve ISSUE_REF from UUID"） | 无 |
| PostHog 告警 | 有（`ref_resolution_failed`） | 无 |
| 到达的过滤点 | L710（UUID 解析失败退出） | L729（GAP-D 正常过滤） |

**结论**：两条路径的功能结果完全一致——Comment.create 不触发 droid exec。热修复仅消除了 UUID 解析失败的噪音（错误日志 + PostHog 告警），不影响任何实际行为。

### Comment.update 事件（补充分析）

Comment 除 create 外还有 update/remove 动作。GAP-D 仅过滤 `Comment.create`。

- **无热修复**：resolve 失败 → exit 0 at L710（不触发 droid exec）
- **有热修复**：resolve 成功 → 通过 GAP-D → 进入 droid exec 路径 → 但 `ISSUE_UUID` 仍为评论 UUID（热修复只解析了 ISSUE_REF），`route_repo("$TEAM_KEY", "$ISSUE_UUID")` 使用评论 UUID 查路由 → 大概率路由失败

**结论**：Comment.update 在有热修复时可能走得更远，但不会完成有意义的操作（route_repo 使用评论 UUID 无法正确路由）。设计意图是"只在 Issue.create 和 resume 时触发 droid"，Comment.update 走 droid exec 不是预期功能。

## 网关层面的补充

CF 网关（worker.js）**不做 comment UUID → issue UUID 翻译**。如果网关在上游做了翻译，Mac 侧的 comment(id:) 反查就完全冗余。但网关没有做翻译，comment UUID 原样到达 trigger-droid.sh。

这不影响裁决：即使 UUID 原样到达，下游的 GAP-D 过滤器（L729）在 Comment.create 场景下已经提供了正确的行为（跳过），只是热修复让 UUID 解析过程更干净。

## 裁决

**等价无需恢复。**

被覆盖的 09-02 comment-UUID 热修复的唯一功能是消除 Comment.create 事件在 UUID 解析阶段的错误日志和 PostHog 告警噪音。其实际行为结果（Comment.create 不触发 droid exec）由后续 GAP-D 过滤器（L724-732）保证，与热修复是否存在无关。

热修复丢失不造成任何真实功能丢失，无需恢复。

## 证据索引

| 编号 | 文件 | 行号 | 内容 |
|------|------|------|------|
| E1 | `~/.factory/webhook/scripts/.sync-backups/trigger-droid.sh.bak.20260905-012303` | L205-239 | 热修复 `comment(id:)` 反查逻辑（覆盖前快照，热修复代码源） |
| E2 | `~/.factory/webhook/scripts/.sync-backups/trigger-droid.sh.bak.20260905-012303` | L205-239 | 覆盖前快照（与 E1 热修复逻辑一致） |
| E3 | `~/.factory/webhook/scripts/trigger-droid.sh`（生产） | L205-224 | 现行 `issue(id:)` 直查（无 comment 反查） |
| E4 | `webhook-scripts/trigger-droid.sh`（仓库） | L205-224 | 仓库版本（与生产一致） |
| E5 | `<cf-repo>/webhook/worker.js` | L26-35, L342-351 | 网关转发逻辑（无 UUID 翻译） |
| E6 | `~/.factory/webhook/hooks.json` | L3-26 | hooks 参数映射（data.id→ISSUE_UUID, data.identifier→ISSUE_REF） |
| E7 | `~/.factory/webhook/scripts/trigger-droid.sh`（生产） | L680-732 | 执行路径（resolve → GAP-D 过滤链） |
