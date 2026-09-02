# gh-proxy 部署文档

## 概述

gh-proxy 是一个 Cloudflare Worker，用于代理 GitHub 请求，解决中国大陆访问 GitHub 不稳定的问题。

**关键特性**：支持 hdot123-org 私有仓库访问（通过 PAT 注入）

## 部署信息

- **Worker 名称**: `gh-proxy`
- **自定义域名**: `gh.qqbaidu.de5.net`
- **Workers.dev 子域**: 已禁用（墙内不可达）
- **Smart Placement**: `aws:ap-east-1`（通过 CF dashboard 配置）
- **Account ID**: `97d8129421b7b8e445718ff9891be1d9`

## 认证机制（三层门禁，全部在代码中）

1. **源 IP 白名单**: CF-Connecting-IP 必须在 `["47.111.21.195"]` 内（ce-01 runner IP），否则 404
2. **PROXY_KEY 校验**: 请求头 `x-proxy-key` 必须匹配环境变量，否则 404
3. **Host 白名单**: 目标域名必须在 ALLOWED_HOSTS 内，否则 403
4. **PAT 注入**: 仅对 `hdot123-org` 私有仓库路径注入 Basic 形式 PAT（`Authorization: Basic <base64(x-access-token:PAT)>`）
   - github.com git smart-http 端点拒绝 Bearer/token 形式（返回 401）
   - 只接受 Basic 形式，编排器已实测确认

## 环境变量（Secrets）

| 名称 | 来源 | 说明 |
|------|------|------|
| `PROXY_KEY` | 1Password | 代理认证密钥（ce-01 .gitconfig 的 X-Proxy-Key，48 字符，971a 开头） |
| `GH_PRIVATE_PAT` | 1Password | hdot123-org 私有仓库 fine-grained PAT（Contents: Read-only，条目 GitHub-PAT-ghproxy-mirror-readonly） |

**注意**：Secrets 通过 `wrangler secret put` 管理，不存储在代码中。

## 部署步骤

### 1. 获取 Cloudflare API Token

从 1Password 读取 CF API Token：

```bash
# 使用 1password-connect MCP 或 CLI
export CLOUDFLARE_API_TOKEN=$(op item get "Cloudflare-xun201811@gmail.com-Workers-11" --vault sever --fields "API 令牌")
```

### 2. 部署 Worker

```bash
cd /Users/busiji/infra-core/cf/gh-proxy
npx wrangler deploy
```

### 3. 设置 Secrets

```bash
# PROXY_KEY
printf 'value-from-1password' | npx wrangler secret put PROXY_KEY

# GH_PRIVATE_PAT
printf 'ghp_xxxx' | npx wrangler secret put GH_PRIVATE_PAT
```

### 4. 验证部署

```bash
# 测试公开仓库
curl -H "x-proxy-key: $PROXY_KEY" "https://gh.qqbaidu.de5.net/https://github.com/actions/checkout"

# 测试私有仓库
curl -H "x-proxy-key: $PROXY_KEY" "https://gh.qqbaidu.de5.net/https://github.com/hdot123-org/infra-core"
```

## ce-01 Runner 配置

ce-01 runner 通过 gitconfig 的 `insteadOf` 规则将 GitHub 请求重写到 gh-proxy：

```ini
[url "https://gh.qqbaidu.de5.net/https://github.com/"]
    insteadOf = https://github.com/
```

**认证方式**：git 请求时自动携带 `x-proxy-key` 头（通过 extraheader 配置）

## 路由规则

| 路径 | 行为 |
|------|------|
| `/https://github.com/hdot123-org/*` | 注入 PAT，转发到 GitHub |
| `/https://github.com/other-org/*` | 无 PAT 注入，转发到 GitHub |
| `/https://raw.githubusercontent.com/*` | 转发到 GitHub |
| `/https://codeload.github.com/*` | 转发到 GitHub |
| 其他域名 | 拒绝（403） |

## 故障排查

### PAT 未注入

检查：
1. `GH_PRIVATE_PAT` secret 是否已设置：`npx wrangler secret list`
2. 请求路径是否匹配 `hdot123-org` 前缀
3. Worker 日志：`npx wrangler tail`

### 404 错误

- PROXY_KEY 未设置或不匹配
- 请求源 IP 不在 `ALLOWED_IPS` 白名单内（worker 代码 `CF-Connecting-IP` 校验，非 CF WAF）

### 403 错误

- 请求的域名不在 ALLOWED_HOSTS 白名单内

## 回滚

```bash
# 回滚到上一个版本
npx wrangler deploy --legacy-env=false

# 或从 CF dashboard 回滚
```

## 监控

```bash
# 实时日志
npx wrangler tail

# 查看 Worker 指标
# CF dashboard → Workers & Pages → gh-proxy → Metrics
```

## 安全注意事项

1. PAT 仅存储在 Cloudflare Workers Secrets 中，不进入代码、日志、PR
2. PROXY_KEY 通过环境变量注入，不硬编码
3. IP 白名单在 worker 代码中（`ALLOWED_IPS` + `CF-Connecting-IP` 校验），提供额外保护层
4. 仅对 `hdot123-org` 私有仓库注入 PAT，公开仓库不受影响

## 维护

- **更新 PAT**: `printf 'new-pat' | npx wrangler secret put GH_PRIVATE_PAT`
- **更新 PROXY_KEY**: `printf 'new-key' | npx wrangler secret put PROXY_KEY`
- **修改代码**: 编辑 `src/worker.js`，运行测试后重新部署
- **测试**: `cd test && node --test`

---

## 版本历史

### v1.1 — 12666fdd-8640-4f76-a7e3-71e993e40c4b (2026-09-02)

**变更**：
- **源 IP 门禁恢复**：原版 worker 硬编码 `CF-Connecting-IP` 白名单 `["47.111.21.195"]`（ce-01 runner IP），非白名单一律 404。round-1 改造时误删此门禁，round-3 设计修正后恢复
- **PAT 注入改 Basic 形式**：`Authorization: Basic <base64("x-access-token:PAT")>`。编排器实测确认 github.com git smart-http 端点（info/refs?service=git-upload-pack）拒绝 Bearer/token 形式（返回 401），只接受 Basic 形式；api.github.com 两者皆收
- **PROXY_KEY 恢复溯源**：原始值取自 ce-01 /home/runner/.gitconfig（1799 行 X-Proxy-Key，48 字符，971a 开头），四份文件（当前+三备份）md5 一致后经管道上传 `wrangler secret put PROXY_KEY` 成功
- **GH_PRIVATE_PAT 恢复溯源**：1P sever vault 条目 `GitHub-PAT-ghproxy-mirror-readonly`（id wflx3mtpqojpyohxcixdfhacby），fine-grained PAT（Contents: Read-only, All repositories）。编排器用 `op item get --fields credential --reveal | tr -d '\n' | wrangler secret put` 管道灌入（round-2 曾因漏加 `--reveal` 把提示字符串当值，round-3 修复）
- **Secret 验证**：`wrangler secret list` 确认 PROXY_KEY + GH_PRIVATE_PAT 双双在位

**验证结果**（编排器在 ce-01 以 runner 用户执行，2026-09-02）：
- 私有仓经镜像 ×3：`git ls-remote https://gh.qqbaidu.de5.net/https://github.com/hdot123-org/infra-core.git HEAD` → 全部返回 `a88518cfa7d5211b66384c1052f1491e90a940bb`
- 公共仓回归：`git ls-remote https://gh.qqbaidu.de5.net/https://github.com/actions/checkout.git HEAD` → `f548e57e`
- Mac 负向探测：`curl -s -o /dev/null -w '%{http_code}' https://gh.qqbaidu.de5.net/https://github.com/actions/checkout` → 404（IP 门禁生效证明）

**ce-01 旁路退役**（2026-09-02）：
- 备份：`/home/runner/.gitconfig.bak-pre-withdraw-20260902`
- 精确删除恒等改写块（`[url "https://github.com/hdot123-org/infra-core"]` + insteadOf + 上方两行中文注释），镜像通用改写 + extraheader 原样保留
- plain URL `https://github.com/hdot123-org/infra-core.git` 现经镜像返回 a88518c（通用 insteadOf 接管）

### v1.0 — (2026-09-01)

初始收编版本：从 `~/cf/xun201811/gh-proxy/worker.js`（Cloudflare API 快照 2026-09-01）收编到 infra-core `cf/gh-proxy/`，添加 PAT 注入逻辑。round-1 误删 IP 门禁，round-2 部署失败（PAT 值灌入错误），round-3 修复后全绿。

---

**文档版本**: v1.1 (2026-09-02)
**Worker 版本**: 12666fdd-8640-4f76-a7e3-71e993e40c4b
**最后更新**: 2026-09-02
