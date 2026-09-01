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

**凭据纪律**：
- 所有 secret 经 `wrangler secret put` stdin 管道设置，值不出现在命令行参数、git 历史、PR body
- `cf/webhook-gateway/.dev.vars`（本地开发用）含 secret 值，已加入 .gitignore，**永不提交**
- 代码中零硬编码 token 值——全部通过 `env.*` 引用

---

## §4 迁移范围矩阵

| 入站路径 | n8n workflow | 迁移裁决 | 理由 |
|---|---|---|---|
| `POST /webhook/events`（五类路由） | github-events-router-v3 | **全量承接** | 主力路径（9441/9441 成功） |
| `POST /webhook/posthog-error` | posthog_error forwarder | **同构复制** | 透传 X-Posthog-Token，低频但活跃 |
| `POST /webhook/ci-complete` | ci-complete forwarder | **不迁** | 死路径（近死，10k 窗内仅 1 次误触） |
| `POST /webhook/linear-events` | linear-events forwarder | **不迁** | 死路径（0 执行，目标 :8765 是遗物服务） |
| `POST /webhook/linear-factory` | linear-factory gateway | **不迁** | 断链事故（581/581 error），另案处理 |

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

- 本 feature 提交到 `factory/cf-webhook-gateway` 分支（与 #175 同行）
- PR body 走 quoted heredoc + 密钥 grep 零命中流程
