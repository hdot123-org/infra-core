# 新仓接入模板（残余面最小链路）

本目录包含 org 级规则覆盖不到的残余面模板，用于新仓接入时的最小配置。

**前置说明**：org 级规则（Layer 1）生效即自动覆盖 org 全部仓库（含新仓），无需逐仓动作。参见 `org-governance-spec.md` 与 `change-playbook.md` Layer 1。

---

## 残余面最小四步链路

### 步骤 1：确认 org 规则自动继承

org 级 Actions 策略（`allowed_actions`、`sha_pinning_required`、默认 workflow 权限等）与安全默认（`dependabot_alerts`、`dependency_graph` 等 enable_all 族）自动覆盖新仓，无需逐仓配置。

**验证**：
```bash
gh api /orgs/hdot123-org/actions/permissions --jq '{allowed_actions, sha_pinning_required}'
gh api /orgs/hdot123-org --jq '.dependabot_alerts_enabled_for_new_repositories'
```

### 步骤 2：应用 ruleset（repo 级分支保护）

org 级 rulesets 需 Team+（Free plan 不可用），只能使用 repo 级 rulesets。复制 `ruleset.json` 模板并适配：

```bash
# 复制模板并修改 required_status_checks（不同仓库的 CI check 名不同）
cp docs/governance/templates/ruleset.json <repo>-ruleset.json

# 创建 ruleset
gh api -X POST /repos/hdot123-org/<repo>/rulesets \
  --input <repo>-ruleset.json

# 清理临时文件
rm <repo>-ruleset.json
```

**适配要点**：
- `rules[0].parameters.required_status_checks[].context`：替换为该仓库的实际 CI check 名（如 `ci-ok`、`qa-ok`、`Test (Node 22/24)` 等）
- 删除 `integration_id` 字段（按仓自适应，GitHub 会自动填充）
- `bypass_actors`：按需配置（默认空 = 无人可绕过）

**验证**：
```bash
gh api /repos/hdot123-org/<repo>/rulesets --jq '.[].name'
```

### 步骤 3：放置 CODEOWNERS 与 dependabot.yml

**CODEOWNERS**：
```bash
cp docs/governance/templates/CODEOWNERS .github/CODEOWNERS
# 或自定义：* @owner1 @owner2
git add .github/CODEOWNERS
git commit -m "chore: add CODEOWNERS"
git push
```

**dependabot.yml**：
```bash
cp docs/governance/templates/dependabot.yml .github/dependabot.yml
# 按需调整 package-ecosystem（github-actions 必选；pip/npm 按仓库技术栈）
git add .github/dependabot.yml
git commit -m "chore: add dependabot.yml"
git push
```

**验证**：
```bash
gh api /repos/hdot123-org/<repo>/contents/.github/CODEOWNERS
gh api /repos/hdot123-org/<repo>/contents/.github/dependabot.yml
```

### 步骤 4：生效验证

1. **ruleset active**：
   ```bash
   gh api /repos/hdot123-org/<repo>/rulesets --jq '.[] | {name, enforcement}'
   # 应输出 enforcement: "active"
   ```

2. **Dependabot 认到 config**：
   - 等待 Dependabot 创建首个 version update PR（或手动触发：Settings > Code security > Dependabot > Enable）
   - 或检查：`gh api /repos/hdot123-org/<repo>/vulnerability-alerts`（204=enabled）

3. **CODEOWNERS 生效**：
   - 创建测试 PR，确认 code owner 被自动请求 review
   - 或：`gh api /repos/hdot123-org/<repo>/codeowners/errors`（应为空）

---

## 可选附录：thin-caller workflow 集

若需接入引擎层（auto-merge、branch-cleanup、droid-review 等），参考 infra-core 的 thin-caller 模式（见 `.github/workflows/` 下的 `auto-merge.yml`、`branch-cleanup.yml` 等）。

**thin-caller 纪律**：
- 全部 action 引用必须 SHA pin（40 位 hex），禁止浮动 tag（如 v1、main 等非 SHA 形式）
- 显式声明 `permissions:`（最小权限原则）
- `runs-on:` 指定 runner 组（如 `[self-hosted, pve-linux]`）

---

## 模板文件索引

| 文件 | 用途 | 落点 |
|---|---|---|
| `ruleset.json` | repo 级分支保护 ruleset 模板 | `<repo>` root（通过 `gh api POST` 创建） |
| `CODEOWNERS` | code owner 配置模板 | `.github/CODEOWNERS` |
| `dependabot.yml` | Dependabot 版本更新配置模板 | `.github/dependabot.yml` |

---

## 参考

- 治理规范：`org-governance-spec.md`
- 分层变更 playbook：`change-playbook.md`（Layer 1 org 级最大化 / Layer 2 残余面×3 主仓 / Layer 3 仅 UI）
- 差距矩阵：`memory/artifacts/2026-09-09-gap-matrix-org-first.md`（产物 C）
- 能力普查：`memory/artifacts/2026-09-09-org-capability-census.md`
