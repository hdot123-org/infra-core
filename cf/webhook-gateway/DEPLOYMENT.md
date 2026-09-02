# DEPLOYMENT.md — webhook-gateway CF Worker

> M4 基础层：CF Worker 承接 n8n CI webhook 能力。
> 本里程碑只做代码+测试+文档（F1），不执行部署（F2）或域名切换。

---

## §1 部署步骤

### 前置条件

1. Node ≥18 + npx 可用
2. 1password-connect MCP 可读 vault `sever` 条目 `Cloudflare-xun201811@gmail.com-Workers-11`
3. Workers-11 API token 具备 workers 写权限（部署+secrets）

### 部署流程

```bash
# 1. 从 1P 读取 API token（经 MCP，不进命令行）
export CLOUDFLARE_API_TOKEN=<1P 读取值>

# 2. 部署 Worker
cd cf/webhook-gateway
npx wrangler deploy

# 3. 设置 secrets（stdin 管道，值不进命令行）
echo -n "<value>" | npx wrangler secret put GITHUB_WEBHOOK_SECRET
echo -n "<value>" | npx wrangler secret put CI_TOKEN
echo -n "<value>" | npx wrangler secret put WIKI_TOKEN
echo -n "<value>" | npx wrangler secret put DISPATCH_TOKEN
echo -n "<value>" | npx wrangler secret put POSTHOG_TOKEN

# 4. （可选）绑定 KV namespace 实现 cron 幂等
# npx wrangler kv:namespace create "IDEMPOTENCY_KV"
# → 将返回的 id 填入 wrangler.toml 的 [[kv_namespaces]] 块
# npx wrangler deploy
```

### 部署后验证

```bash
# Worker URL 可达（workers.dev 子域）
curl -s -o /dev/null -w "%{http_code}" https://<worker-name>.<subdomain>.workers.dev/health
# 预期：200

# GET on webhook endpoint → 405
curl -s -o /dev/null -w "%{http_code}" https://<worker-url>/webhook/events
# 预期：405
```

---

## §2 回滚步骤

### Worker 回滚

```bash
# 方式 A：删除 Worker（完全下线）
npx wrangler delete

# 方式 B：回滚到上一版本（wrangler 自动保留版本历史）
npx wrangler deployments list
npx wrangler rollback --deployment-id=<id>
```

### 域名/流量回滚

本里程碑 **不执行域名切换**，无需回滚域名。未来切换后的回滚：

```
memory 仓 GitHub hook (id=632882064) URL 改回：
  https://webhook.exa.edu.kg/webhook/events（n8n 原地址）
```

---

## §3 Secrets 来源映射表

| Worker Secret 名 | 用途 | 值来源 | 备注 |
|---|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC-SHA256 验签 | **新生成**（本地 `openssl rand -hex 32`） | 1P 收编待办 |
| `CI_TOKEN` | X-CI-Token 出站头 | 1P vault `sever` → `n8n/node-22/Webhook Provider/Secrets` 或 Mac hooks.json 明文 | 现有值 |
| `WIKI_TOKEN` | X-Wiki-Token 出站头 | Mac hooks.json 明文 | 现有值 |
| `DISPATCH_TOKEN` | repository_dispatch Authorization | 排查序：1P → infra-core repo secrets → 本机配置 | 可能待补 |
| `POSTHOG_TOKEN` | X-Posthog-Token 透传 | PostHog webhook 配置 / 1P | 低频路径 |
| `LINEAR_WEBHOOK_TOKEN` | X-Webhook-Token 出站头（Linear Issue/Comment 转发） | node-22 `/opt/n8n-webhook/workflows/linear-factory-gateway.json` 中的 token 值（43 位，经 stdin 管道上传） | Linear 类统一路径用 |

**凭据纪律**：
- 所有 secret 经 `wrangler secret put` stdin 管道设置，值不出现在命令行参数、git 历史、PR body
- `cf/webhook-gateway/.dev.vars`（本地开发用）含 secret 值，已加入 .gitignore，**永不提交**
- 代码中零硬编码 token 值——全部通过 `env.*` 引用

---

## §4 迁移范围：统一路由分类矩阵（九类，2026-09-02 统一路径裁定后更新）

> 统一路径裁定：所有外部 webhook 只使用唯一路径 `https://webhook.exa.edu.kg/webhook/events`。
> n8n router 已升级为 Unified Events Multiplexer，Worker 分类决策与生产多路复用器逐类一致（VAL-WPARITY-001）。
> 
> **迁移范围说明**：本节定义 Worker 承接的九类 webhook 路由决策矩阵，覆盖从 n8n 统一路由器迁移的全部事件类型。

| # | 入站指纹 | 路由决策 | 出站目标 | 出站头 |
|---|---|---|---|---|
| 1 | `x-posthog-token` 头存在（PostHog 告警） | `posthog-error` forward | `/hooks/posthog-error` | X-Posthog-Token 透传 |
| 2a | Linear payload（webhookId + Issue） | `linear-to-droid` forward | `/hooks/linear-to-droid` | X-Webhook-Token（LINEAR_WEBHOOK_TOKEN） |
| 2b | Linear payload（webhookId + Comment） | `linear-to-droid` forward | `/hooks/linear-to-droid` | X-Webhook-Token（LINEAR_WEBHOOK_TOKEN） |
| 3 | Linear payload（其他资源类型） | `none`（不转发） | — | — |
| 4 | 无 `x-github-event` + body.repo & body.pr_number（ci-notify） | `ci-complete` forward | `/hooks/ci-complete` | X-CI-Token（CI_TOKEN） |
| 5 | `x-github-event: ping` | `none`（握手响应） | — | — |
| 6 | `x-github-event: push` | `wiki-refresh` forward | `/hooks/wiki-refresh` | X-Wiki-Token + **X-GitHub-Event: push**（双头） |
| 7 | `x-github-event: check_run` + conclusion ∉ {success,skipped,neutral} | `none`（仅记录，黑名单语义） | — | — |
| 8 | `x-github-event: check_run` + conclusion ∈ {success,skipped,neutral} | `none`（ci-complete 通道已覆盖） | — | — |
| 9 | 其余一切 | `none`（不转发） | — | — |

**旧路径裁决（不迁，保持观察期）**：

| 旧入站路径 | n8n workflow | 裁决 | 理由 |
|---|---|---|---|
| `POST /webhook/ci-complete` | ci-complete forwarder | **不迁** | 死路径（真实 CI 通知走 ci-notify 类） |
| `POST /webhook/linear-events` | linear-events forwarder | **不迁** | 死路径（0 执行） |
| `POST /webhook/linear-factory` | linear-factory gateway | **不迁** | 断链事故，另案处理 |

**认证**：双通道 fail-closed——X-Hub-Signature-256 HMAC 或 X-CI-Token token 头匹配任一放行；双缺失/错误 401。

---

## §5 生产切换预案

> ⚠️ 本里程碑（M4-F1/F2）**不执行切换**——仅文档化步骤，供后续里程碑执行。

### 切换步骤

1. **补设 GitHub webhook secret**
   ```bash
   # 从环境变量读取密钥值并设置 webhook secret
   gh api repos/hdot123-org/memory-core/hooks/632882064 -X PATCH \
     --field "content_type=json" \
     --input <(jq -n --arg s "$GITHUB_WEBHOOK_SECRET" '{secret: $s}')
   ```
   > 注意：设置 secret 后 GitHub 会用 HMAC 签名所有后续 payload；n8n 不验签会照收，但 Worker 端必须已配好 `GITHUB_WEBHOOK_SECRET`

2. **改指 hook URL**
   ```bash
   gh api repos/hdot123-org/memory-core/hooks/632882064 -X PATCH \
     -f url="https://<worker-url>/webhook/events"
   ```

3. **验证**
   - 推送测试 commit → 检查 Worker 日志（`npx wrangler tail`）→ 确认 HMAC 通过 + ci-complete 转发成功
   - 检查 Mac 侧 `~/.factory/webhook/logs/ci-complete-*` 出现对应日志

4. **确认 n8n 五 workflow active 态不变**（不主动停 n8n，让流量自然迁移）

### 回滚步骤

```bash
# hook URL 改回 n8n
gh api repos/hdot123-org/memory-core/hooks/632882064 -X PATCH \
  -f url="https://webhook.exa.edu.kg/webhook/events"

# 移除 webhook secret（恢复无验签状态）
gh api repos/hdot123-org/memory-core/hooks/632882064 -X PATCH \
  -f secret=''
```

---

## §6 部署证据（M4-F2，2026-09-01 完成）

### 6.1 部署状态

- **Worker URL**: https://webhook-gateway.xun201811.workers.dev
- **部署时间**: 2026-09-01 15:18 UTC
- **部署方式**: `npx wrangler deploy`（从 factory/cf-webhook-gateway 分支，commit df8ee65）
- **健康检查**: GET /health → 200 ✓
- **路由约束**: GET /webhook/events → 405 ✓

### 6.2 Secrets 配置

已上传（经 stdin 管道，值未入转录）：
- `CI_TOKEN` ✓
- `WIKI_TOKEN` ✓
- `POSTHOG_TOKEN` ✓
- `GITHUB_WEBHOOK_SECRET` ✓（已重生成，round 1 泄漏值已作废）
- `DISPATCH_TOKEN`: **缺口**（三路排查不可得，cron dispatch 留待切换前补）

本地 `.dev.vars` 已写入 GITHUB_WEBHOOK_SECRET 新值（git 永不提交，已在 .gitignore）。

### 6.3 影子回环验证

**全链路已打通**（2026-09-01 17:00Z 实测）：

1. 构造 Actions-notify payload（`repo="shadow-test"`, `pr_number=-1`）+ 本地 HMAC 签名
2. POST https://webhook-gateway.xun201811.workers.dev/webhook/events → 200 ✓
3. Worker → ci-webhook.exa.edu.kg → Mac:5555 全链路到达 ✓
4. Mac 侧日志样本出现：`~/.factory/webhook/logs/ci-complete-prunknown-20260901-192157.log` ✓
5. 样本已清理 ✓

### 6.4 Cron 配置 + 实测证据

**配置级证明**：
- CF API schedules endpoint 确认 `*/10 * * * *` schedule active（created_on: 2026-09-01T15:18:00Z）
- GraphQL workersInvocationsAdaptive 显示 5 次调用（15:18:35/36/37, 15:46:54, 15:47:08）

**运行时证据缺口**：
- wrangler tail（Mac 本地）：15 分钟空输出（Mac→CF 通道墙内抖动）
- wrangler tail（node-22）：已后台运行 16h+，捕获 0 行（同网络通道问题）
- GraphQL 无法区分 triggerType（scheduled vs HTTP），5 次调用可能含影子测试的 HTTP 请求

**结论**：配置级证明已拿到（schedule active + invocation telemetry 存在），但实际 ≥2 次 scheduled 触发的运行时间隔证据因 wrangler tail 网络通道问题暂未取得。此为本里程碑已知缺口，不阻塞部署完成。

### 6.5 生产零扰动三查

1. **memory 仓 hook 632882064 URL 未变** ✓
   - `gh api repos/hdot123-org/memory-core/hooks/632882064` 确认 config.url 仍为 `https://webhook.exa.edu.kg/webhook/events`
   - 无新增 hook ✓

2. **n8n 五 workflow active 态不变** ✓
   - ssh node-22 sqlite3 -readonly 查询确认五 workflow 全 active=1

3. **webhook.exa.edu.kg 流量路径未动** ✓
   - 仍路由 n8n（404 语义维持，无新流量引入）

### 6.6 PR 计划

- 本 feature 提交到 `factory/cf-worker-unified-parity` 分支
- PR body 走 quoted heredoc + 密钥 grep 零命中流程

### 6.7 全类 parity 补齐状态（2026-09-02，VAL-WPARITY 系列）

**已完成的 6 项差距补齐**：

1. **①双通道认证**（VAL-WPARITY-002）：worker.js 实现 HMAC 或 token 头任一放行，双缺失/错误 401 fail-closed。测试覆盖 7 例（HMAC 正确/错误/token 正确/错误/双错/双缺/env 未配置）。

2. **②push 双头注入**（VAL-WPARITY-003）：push 转发同时携带 `X-GitHub-Event: push` 与 `X-Wiki-Token`，满足 Mac trigger-rule 双条件。测试断言双头齐全。

3. **③Linear 类统一路径**：指纹 webhookId+action+type+data；Issue/Comment 重建 `{action,type,data}` + 注入 X-Webhook-Token（LINEAR_WEBHOOK_TOKEN secret）→ ci-webhook.exa.edu.kg → Mac linear-to-droid；其他资源类型 none。测试覆盖 Issue/Comment/其他类型共 6 例。

4. **④PostHog 并入 /webhook/events**：统一裁定不允许第二路径，posthog-error 作为分类器内的路由（x-posthog-token 头存在即识别）；x-posthog-token 头透传。测试断言 posthog token 透传。

5. **⑤check_run 黑名单语义**：替换现白名单为黑名单（conclusion ∉ {success,skipped,neutral} → log only）。测试覆盖 failure/timed_out/cancelled（黑名单命中）+ success/skipped/neutral（白名单放行）共 6 例。

6. **⑥DEPLOYMENT.md §6 切换 runbook**：域名切换绝不执行，worker 只产出 runbook（VAL-WPARITY-004）。五块齐备 + 显式用户批准门。

**测试覆盖**：50 例全绿（九类路由矩阵 + 双通道认证 7 例 + 出站头含 Linear 重建 6 例 + detectLinear + cron + posthog）。

**待完成**：切换 runbook 五块（VAL-WPARITY-004）+ 回归 + PR 交付。

---

## §7 域名切换 runbook（VAL-WPARITY-004）

> **本 runbook 仅供未来切换参考。当前阶段不执行域名切换，worker 仍部署在 workers.dev 子域。**

### 前置条件检查

1. **Worker 部署验证**
   ```bash
   # 确认 worker 已部署且健康
   curl -s https://webhook-gateway.xun201811.workers.dev/health | jq .
   # 预期：{"status":"ok","service":"webhook-gateway"}
   
   # 确认认证逻辑工作
   curl -s -X POST https://webhook-gateway.xun201811.workers.dev/webhook/events \
     -H "Content-Type: application/json" \
     -d '{"test":true}'
   # 预期：401 Authentication failed
   ```

2. **Secrets 完整性**
   ```bash
   # 确认所有必要 secrets 已上传
   npx wrangler secret list
   # 预期包含：GITHUB_WEBHOOK_SECRET, CI_TOKEN, WIKI_TOKEN, LINEAR_WEBHOOK_TOKEN, POSTHOG_TOKEN
   ```

3. **生产零扰动确认**
   ```bash
   # 确认当前生产 hook 仍指向 n8n
   gh api repos/hdot123-org/memory-core/hooks/632882064 | jq .config.url
   # 预期："https://webhook.exa.edu.kg/webhook/events"
   
   # 确认 n8n workflows 仍 active
   ssh node-22 'sqlite3 /opt/n8n-webhook/n8n.sqlite "SELECT id, name, active FROM workflows WHERE name LIKE \"%webhook%\""'
   # 预期：所有 workflow active=1
   ```

### 显式用户批准门（必须）

> ⚠️ **在执行以下任何切换步骤之前，必须获得用户明确批准。**
>
> 批准检查清单：
> 1. Worker 健康检查通过 ✓
> 2. 差分验证全类 match ✓
> 3. 影子回环验证通过 ✓
> 4. 所有 secrets 已上传 ✓
> 5. 回滚步骤已确认 ✓
>
> **未获批准不得执行域名切换。**

### GitHub webhook secret 配置

1. **生成 HMAC secret**（如未配置）
   ```bash
   openssl rand -hex 32
   # 记录输出值，后续步骤使用
   ```

2. **配置 GitHub webhook secret**
   ```bash
   gh api repos/hdot123-org/memory-core/hooks/632882064 \
     -X PATCH \
     -f secret="<generated-secret>"
   ```

3. **上传 secret 到 Worker**
   ```bash
   echo "<generated-secret>" | npx wrangler secret put GITHUB_WEBHOOK_SECRET
   ```

### DNS 切换

> **注意：本里程碑不绑定生产域名。如需切换，需修改 wrangler.toml 并重新部署。**

```toml
# wrangler.toml 添加：
routes = [
  { pattern = "webhook.exa.edu.kg/*", zone_name = "exa.edu.kg" }
]
```

```bash
npx wrangler deploy
```

### 流量切换验证

1. **测试新端点**
   ```bash
   # 推送测试 payload 到生产域名
   curl -X POST https://webhook.exa.edu.kg/webhook/events \
     -H "Content-Type: application/json" \
     -H "X-Hub-Signature-256: sha256=<computed-hmac>" \
     -d '{"event":"push","ref":"refs/heads/test"}'
   
   # 检查 Worker 日志
   npx wrangler tail
   # 预期：路由决策日志
   ```

2. **验证 Mac 端接收**
   ```bash
   # 检查 wiki-refresh 日志
   ls -lt ~/.factory/webhook/logs/wiki-refresh-*.log | head -5
   # 预期：新日志文件
   ```

3. **确认 n8n 仍 active**（双跑验证期）
   ```bash
   ssh node-22 'sqlite3 /opt/n8n-webhook/n8n.sqlite "SELECT id, name, active FROM workflows WHERE name LIKE \"%webhook%\""'
   ```

### 回滚步骤

1. **恢复 DNS 指向 n8n**
   ```bash
   # 移除 wrangler.toml 中的 routes 配置
   # 重新部署
   npx wrangler deploy
   ```

2. **验证流量恢复**
   ```bash
   curl -X POST https://webhook.exa.edu.kg/webhook/events \
     -H "Content-Type: application/json" \
     -d '{"test":true}'
   # 预期：n8n 处理（不再返回 Worker 的 401）
   ```

---

## §8 部署证据（Round 3，2026-09-02）

### 8.1 Worker 重新部署

```bash
$ cd /Users/busiji/infra-core/cf/webhook-gateway
$ npx wrangler deploy

Total Upload: 15.37 KiB / gzip: 3.91 KiB
Uploaded webhook-gateway (3.10 sec)
Deployed webhook-gateway triggers (2.54 sec)
  https://webhook-gateway.xun201811.workers.dev
  schedule: */10 * * * *
Current Version ID: fcbc21d4-dcc9-4424-955e-6665608a4843
```

**部署状态**：
- Worker URL: https://webhook-gateway.xun201811.workers.dev
- Version ID: fcbc21d4-dcc9-4424-955e-6665608a4843
- Cron schedule: */10 * * * *
- 域名绑定: 无（仅 workers.dev 子域）

### 8.2 功能验证

**健康检查**：
```bash
$ curl -s https://webhook-gateway.xun201811.workers.dev/health
{"status":"ok","service":"webhook-gateway"}
```

**认证验证**：
```bash
$ curl -s -X POST https://webhook-gateway.xun201811.workers.dev/webhook/events \
  -H "Content-Type: application/json" \
  -d '{"event":"ping","zen":"Test message"}'
{"error":"Authentication failed"}
```

预期行为：
- 无认证头 → 401 Authentication failed ✓
- 生产零扰动：当前 hook 仍指向 n8n ✓

### 8.3 生产零扰动确认

```bash
$ gh api repos/hdot123-org/memory-core/hooks/632882064 | jq .config.url
"https://webhook.exa.edu.kg/webhook/events"

$ ssh node-22 'sqlite3 -readonly /opt/n8n-webhook/n8n.sqlite "SELECT id, name, active FROM workflows WHERE active=1"'
1|PostHog Error → Mac:5555 Forwarder|1
2|GitHub Events → Mac:5555 Router|1
3|CI Complete → Mac:5555 Forwarder|1
4|Linear → Factory Forwarder|1
5|Linear Factory Gateway|1
```

**确认**：
- GitHub hook 仍指向 n8n（webhook.exa.edu.kg）✓
- 5 个 n8n workflow 仍 active ✓
- Worker 部署在 workers.dev，不影响生产流量 ✓

### 8.4 差分验证矩阵（VAL-WPARITY-001）

Worker router.js 与生产 n8n github-events-router-v3.json 路由决策对比：

| # | 类别 | 入站指纹 | Worker 决策 | 生产决策 | match |
|---|---|---|---|---|---|
| 1 | posthog | x-posthog-token 头存在 | forward → posthog-error | forward → posthog-error | ✓ |
| 2a | linear-Issue | webhookId + type=Issue | forward → linear-to-droid | forward → linear-to-droid | ✓ |
| 2b | linear-Comment | webhookId + type=Comment | forward → linear-to-droid | forward → linear-to-droid | ✓ |
| 3 | linear-other | webhookId + type=Project | none | none | ✓ |
| 4 | ci-notify | repo + pr_number, 无事件头 | forward → ci-complete | forward → ci-complete | ✓ |
| 5 | ping | x-github-event: ping | none | none | ✓ |
| 6 | push | x-github-event: push | forward → wiki-refresh | forward → wiki-refresh | ✓ |
| 7 | check_run-failed | check_run, conclusion=failure | none (blacklist) | none (blacklist) | ✓ |
| 8 | check_run-ok | check_run, conclusion=success | none | none | ✓ |
| 9 | unknown | x-github-event: pull_request | none | none | ✓ |

**差分方法**：
- 合成基线载荷（test_parity_diff.js）：10 类代表性输入覆盖全部分类路径
- 生产 router 代码审计（github-events-router-v3.json Code 节点）：逐类比对 if/else 分支语义
- 11/11 测试全绿，零分歧

**降级说明**：n8n execution_data 使用复杂索引数组引用格式（string→int→array offset），经多次尝试（sqlite3 readonly + Python resolve、wrangler tail、REST API）未能完整解析原始载荷。当前差分基于：
1. 合成载荷保留所有分类相关字段（headers/body 结构）
2. 生产 router 代码逐行审计（Code 节点 jsCode 字段）
3. 语义等价性确认（每个 if/else 分支对齐）

真实载荷提取留作后续里程碑优化项，不阻塞本 PR 合并。

### 8.5 影子回环验证（VAL-WPARITY-002/003）

**时间**：2026-09-02 14:51:38 UTC+8

**请求**：
```bash
curl -X POST https://webhook-gateway.xun201811.workers.dev/webhook/events \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-GitHub-Delivery: shadow-parity-r3-test-1756795898" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d '{
    "ref": "refs/heads/shadow-parity-r3",
    "repository": {
      "full_name": "shadow-parity-r3-test",
      "html_url": "https://github.com/shadow-parity-r3-test"
    },
    "pusher": {"name": "shadow-test", "email": "shadow@test.local"},
    "head_commit": {
      "id": "shadow-commit-id",
      "message": "shadow parity verification",
      "timestamp": "2026-09-02T14:51:38Z"
    }
  }'
```

**Worker 响应**：
```json
{
  "status": "ok",
  "route": "wiki-refresh",
  "event": "push",
  "forwarded": true,
  "reason": "push to wiki-refresh",
  "timestamp": "2026-09-02T06:51:38.234Z"
}
```

**Mac 侧日志**（`wiki-refresh-20260902-145138.log`）：
```
[2026-09-02 14:51:38] Wiki refresh triggered
[2026-09-02 14:51:38] REPO=shadow-parity-r3-test
[2026-09-02 14:51:38] BRANCH=shadow-parity-r3
[2026-09-02 14:51:38] COMMIT=shadow-commit-id
[2026-09-02 14:51:38] Trigger-rule matched (dual headers verified)
[2026-09-02 14:51:38] Skipping: branch=shadow-parity-r3 not in allowed list [main master]
```

**验证结果**：
- ✓ Worker 成功转发到 Mac（HTTP 200，forwarded=true）
- ✓ Mac 收到双头（trigger-rule 匹配，证明 X-GitHub-Event: push + X-Wiki-Token 同时到达）
- ✓ 日志含可辨识标记（BRANCH=shadow-parity-r3，REPO=shadow-parity-r3-test）
- ✓ 正确跳过（branch 不在允许列表——预期行为）

**清理**：
- 影子测试使用 branch `shadow-parity-r3`（无需清理——不在允许列表）
- 日志文件保留作为证据：wiki-refresh-20260902-145138.log
- 未影响真实数据
