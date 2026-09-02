# gh-proxy

GitHub 代理 Cloudflare Worker，支持 hdot123-org 私有仓库访问。

## 特性

- ✅ 代理 GitHub 公开仓库
- ✅ 支持 hdot123-org 私有仓库（通过 PAT 注入）
- ✅ IP 白名单 + PROXY_KEY 双重认证
- ✅ 自动剥离客户端 Authorization 头
- ✅ CORS 支持

## 支持的域名

- `github.com`
- `raw.githubusercontent.com`
- `codeload.github.com`
- `objects.githubusercontent.com`
- `assets.githubusercontent.com`
- `gist.github.com`
- `api.github.com`

## 使用示例

```bash
# 公开仓库
curl -H "x-proxy-key: YOUR_KEY" \
  "https://gh.qqbaidu.de5.net/https://github.com/actions/checkout"

# 私有仓库（自动注入 PAT）
curl -H "x-proxy-key: YOUR_KEY" \
  "https://gh.qqbaidu.de5.net/https://github.com/hdot123-org/infra-core"
```

## 测试

```bash
cd test
node --test
```

## 部署

参见 [DEPLOYMENT.md](./DEPLOYMENT.md)

## 目录结构

```
cf/gh-proxy/
├── src/
│   └── worker.js       # Worker 主逻辑
├── test/
│   ├── worker.test.js  # 测试文件
│   └── package.json    # 测试配置
├── wrangler.toml       # Cloudflare 配置
├── DEPLOYMENT.md       # 部署文档
└── README.md           # 本文件
```

## 许可证

与 infra-core 主项目保持一致。
