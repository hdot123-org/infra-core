# Changelog

## [0.11.0](https://github.com/hdot123-org/infra-core/compare/v0.10.0...v0.11.0) (2026-09-02)


### Features

* **cf-worker:** 四通道入站认证 + /webhook/posthog-error fail-closed 收紧（无路由行为变更） ([#190](https://github.com/hdot123-org/infra-core/issues/190)) ([df56b5b](https://github.com/hdot123-org/infra-core/commit/df56b5bd3cafa33b0358d17204284a2805e14cde))


### Bug Fixes

* **cf-worker:** M4 scrutiny 轮 1 移交修复（无路由行为变更） ([#186](https://github.com/hdot123-org/infra-core/issues/186)) ([8ab4f1f](https://github.com/hdot123-org/infra-core/commit/8ab4f1fdd515e9b055e9ca4b3127ff3159fb5fe8))
* **cf-worker:** 通道3改读 Linear-Signature 头名并锁定生产路由形状 ([#191](https://github.com/hdot123-org/infra-core/issues/191)) ([4f5c73e](https://github.com/hdot123-org/infra-core/commit/4f5c73e157fcff799c20037ca469937f115c901a))

## [0.10.0](https://github.com/hdot123-org/infra-core/compare/v0.9.0...v0.10.0) (2026-09-02)


### Features

* **cf-worker:** gh-proxy 私有仓 PAT 注入 + 三层门禁版本化 ([#180](https://github.com/hdot123-org/infra-core/issues/180)) ([c0ea2c7](https://github.com/hdot123-org/infra-core/commit/c0ea2c7e4c6af0d61a2b874f48ab5805764da5f8))
* **cf-worker:** unified parity round 3 ([#184](https://github.com/hdot123-org/infra-core/issues/184)) ([712a267](https://github.com/hdot123-org/infra-core/commit/712a267fd5b7af8802cfdebab3e2a774e46034b2))


### Bug Fixes

* **release:** relock 步骤分支探测改用 gh 查询修复永久空跳过 ([#177](https://github.com/hdot123-org/infra-core/issues/177)) ([536ec26](https://github.com/hdot123-org/infra-core/commit/536ec26ba0d8ba1fd1c0551350bccdffe44fda86))

## [0.9.0](https://github.com/hdot123-org/infra-core/compare/v0.8.0...v0.9.0) (2026-09-01)


### Features

* **ci:** add set -euo pipefail to notify job run blocks ([#151](https://github.com/hdot123-org/infra-core/issues/151)) ([3c0073b](https://github.com/hdot123-org/infra-core/commit/3c0073b4282ca67b7d5424411e5e13d9bbe88a7e))
* **platform:** F7 repo 级 Actions 平台策略锁定 (VAL-M3-001~012) ([#164](https://github.com/hdot123-org/infra-core/issues/164)) ([e59d127](https://github.com/hdot123-org/infra-core/commit/e59d12750debc1f0e4951bc036ef5a144739d69a))
* **platform:** F8 Rulesets 迁移与合并设置闭环 (VAL-M3-013~023) ([#166](https://github.com/hdot123-org/infra-core/issues/166)) ([b1fb69f](https://github.com/hdot123-org/infra-core/commit/b1fb69fb7802159f43c7e276b862e74a4b165254))


### Bug Fixes

* **infra:** uv.lock 根包版本对齐至 0.8.0 ([#163](https://github.com/hdot123-org/infra-core/issues/163)) ([1e28fc4](https://github.com/hdot123-org/infra-core/commit/1e28fc403342765508e0578df5bbdb31700c8b6f))
* **release:** uv.lock 根包版本守护与 Release PR 自动 relock (INFRA-712) ([#165](https://github.com/hdot123-org/infra-core/issues/165)) ([e997363](https://github.com/hdot123-org/infra-core/commit/e997363033979f25ede50a170c32b52abba31dd0))
* **workflow:** 恢复引擎仓自扫 evolution 定时触发面 (INFRA-717) ([#173](https://github.com/hdot123-org/infra-core/issues/173)) ([d2db025](https://github.com/hdot123-org/infra-core/commit/d2db0254b8130975d018d12bfc93a88b611bb93b))

## [0.8.0](https://github.com/hdot123-org/infra-core/compare/v0.7.2...v0.8.0) (2026-08-31)


### Features

* **ci:** notify-ci-complete payload 补 run_url 字段 (INFRA-690) ([#139](https://github.com/hdot123-org/infra-core/issues/139)) ([cde4139](https://github.com/hdot123-org/infra-core/commit/cde41395ee00c2eadfddf00bc7cbcd2df4e39ae6))
* **workflow:** F5 bash 容错统一 + PRT 安全面审计 (VAL-M2-201~210) ([#138](https://github.com/hdot123-org/infra-core/issues/138)) ([4d9bb3a](https://github.com/hdot123-org/infra-core/commit/4d9bb3a92e780cd72a4ea1c630d418b30cfd134b))
* **workflow:** SHA 锁定所有外部 action 引用 (F3) ([#125](https://github.com/hdot123-org/infra-core/issues/125)) ([9569b19](https://github.com/hdot123-org/infra-core/commit/9569b191e15b7be4a7d8cf1b3276049a69f181bd))


### Bug Fixes

* add notify-ci-complete job to notify n8n after CI completion ([#137](https://github.com/hdot123-org/infra-core/issues/137)) ([4103a09](https://github.com/hdot123-org/infra-core/commit/4103a09961d81666000b564830d16a456c2b7b9f))
* **evolution:** 抑制 actions 自包含分发副本的固有重复块误报 (INFRA-691) ([#142](https://github.com/hdot123-org/infra-core/issues/142)) ([7741b4b](https://github.com/hdot123-org/infra-core/commit/7741b4b90f0d92c42e95528530ed462d3dec9dfa))
* **tests:** 修复 test_sha_references_have_version_comment 静默吞异常（INFRA-686） ([#133](https://github.com/hdot123-org/infra-core/issues/133)) ([821501d](https://github.com/hdot123-org/infra-core/commit/821501d5f85ca394a2d732d182146738585e18a1))
* **workflow:** F4 显式最小权限声明 — ci/qa 顶层基线 + review 系 job 级 + id-token 移除 (VAL-M2-101/102/103/104/105/106/107) ([#134](https://github.com/hdot123-org/infra-core/issues/134)) ([b52961d](https://github.com/hdot123-org/infra-core/commit/b52961dc5655554ab6c7723812466163ea9f75bf))
* **workflow:** 补全 4 个 workflow 顶层最小权限基线（INFRA-688） ([#135](https://github.com/hdot123-org/infra-core/issues/135)) ([ae622a1](https://github.com/hdot123-org/infra-core/commit/ae622a12a2225fd7580287268ad3f26c2f69d98b))


### Documentation

* F6 文档收尾 — §7 演进路线补 M6、config.yml 注释修正、skip 理由补记 ([#145](https://github.com/hdot123-org/infra-core/issues/145)) ([1f5dc02](https://github.com/hdot123-org/infra-core/commit/1f5dc023910452555dce25e9b4555150fc12cbf0))

## [0.7.2](https://github.com/hdot123-org/infra-core/compare/v0.7.1...v0.7.2) (2026-08-31)


### Bug Fixes

* **evolution:** self-audit 心跳阈值 2h→8h 消除结构性 tick 间隔误报 (INFRA-651) ([#114](https://github.com/hdot123-org/infra-core/issues/114)) ([5636d68](https://github.com/hdot123-org/infra-core/commit/5636d6826379a2550ae7c4ca65930a96471f966e))

## [0.7.1](https://github.com/hdot123-org/infra-core/compare/v0.7.0...v0.7.1) (2026-08-30)


### Bug Fixes

* **evolution:** check_config_yml 计入 rule_packs 展开生效工具数 ([#104](https://github.com/hdot123-org/infra-core/issues/104)) ([64a4b55](https://github.com/hdot123-org/infra-core/commit/64a4b55369d0f9776b175973cfb0249a08980c25))
* **evolution:** 修复引擎仓自扫配置并抑制固有布局误报 (INFRA-659) ([#102](https://github.com/hdot123-org/infra-core/issues/102)) ([87b43b2](https://github.com/hdot123-org/infra-core/commit/87b43b242dc13b0a2541550856718a6789be2bca))

## [0.7.0](https://github.com/hdot123-org/infra-core/compare/v0.6.1...v0.7.0) (2026-08-30)


### Features

* **actions:** auto-merge 动作收编入本仓，退役 shared-workflows pin（VAL-HARD-104） ([#98](https://github.com/hdot123-org/infra-core/issues/98)) ([cda47d7](https://github.com/hdot123-org/infra-core/commit/cda47d7012b2a5a04d01ecec0261516581b02625))
* **engine:** auto_close_resolved 与 rule_id 域恒定落日志——VAL-CROSS-006/007 证据面 ([#99](https://github.com/hdot123-org/infra-core/issues/99)) ([3954109](https://github.com/hdot123-org/infra-core/commit/395410992eca5bf117919095bca3ed4b79b82629))


### Bug Fixes

* **evolution:** 探针失败不再冒充 severe outage，未知 staleness 用 None 表示 (INFRA-639) ([#87](https://github.com/hdot123-org/infra-core/issues/87)) ([c23eab9](https://github.com/hdot123-org/infra-core/commit/c23eab98d4647887aab18aaac4931845a518c834))


### Documentation

* **onboarding:** config 示例补齐引擎必填键，新增指南契约测试防回归（VAL-CROSS-008） ([#100](https://github.com/hdot123-org/infra-core/issues/100)) ([3bf890b](https://github.com/hdot123-org/infra-core/commit/3bf890bc86d4100b8849603d6a0cff6b6d7be283))
* QA 家族上线后同步命名契约与门禁矩阵（INFRA-596） ([#41](https://github.com/hdot123-org/infra-core/issues/41)) ([77d5f0e](https://github.com/hdot123-org/infra-core/commit/77d5f0e6a0600797c8255ea8726c86bb6d4bd4b9))
* **roadmap:** 中央调度路线图（VAL-HARD-106） ([#97](https://github.com/hdot123-org/infra-core/issues/97)) ([698dff8](https://github.com/hdot123-org/infra-core/commit/698dff834db2dfeb802ca87ebcb657ebb6dd1af5))

## [0.6.1](https://github.com/hdot123-org/infra-core/compare/v0.6.0...v0.6.1) (2026-08-30)


### Bug Fixes

* **engine:** 修复 audit_layout adapter schema 漂移——消费真实 findings 输出并补 rule_id 全工具契约测试 ([#91](https://github.com/hdot123-org/infra-core/issues/91)) ([8bf173c](https://github.com/hdot123-org/infra-core/commit/8bf173cae5f8ec6ee0030e3763d95b0b1573a380))

## [0.6.0](https://github.com/hdot123-org/infra-core/compare/v0.5.1...v0.6.0) (2026-08-30)


### Features

* **M5:** webhook-scripts 生产同步真源迁入本仓 + 消费仓接入指南 ([#81](https://github.com/hdot123-org/infra-core/issues/81)) ([e067af5](https://github.com/hdot123-org/infra-core/commit/e067af54038d1840ea56a7b20b431cdce1b94271))


### Bug Fixes

* **ci:** type-bundle 去重 mypy src 域——删除 Run mypy 重复步骤 ([#75](https://github.com/hdot123-org/infra-core/issues/75)) ([b0cdbc2](https://github.com/hdot123-org/infra-core/commit/b0cdbc211a2f1886851d422e870f1b3327122d98))
* **linear:** create path 回填新建 tracker URL——同步不再恒走 no-tracker skip ([#79](https://github.com/hdot123-org/infra-core/issues/79)) ([480fee5](https://github.com/hdot123-org/infra-core/commit/480fee534209384a07a07a19a2f338faaef8dea8))
* **linear:** 项目同步改用现行 issueUpdate mutation——VAL-GATE-118 真红根因修复 ([#76](https://github.com/hdot123-org/infra-core/issues/76)) ([5485b40](https://github.com/hdot123-org/infra-core/commit/5485b40af51dc8e3c9d2c09c07d72fa54641aa38))
* **M5:** reusable workflow_call 双形态键声明恢复——解锁消费仓门禁死锁 ([#86](https://github.com/hdot123-org/infra-core/issues/86)) ([4f22a15](https://github.com/hdot123-org/infra-core/commit/4f22a15bea759f5659352951f462dfdb5f410591))
* **pack:** 修复 pack↔engine 接缝三缺陷——error_patterns jsonl 声明/工具名统一 engine 键/daily audit 零宿主写 ([#80](https://github.com/hdot123-org/infra-core/issues/80)) ([3efcc82](https://github.com/hdot123-org/infra-core/commit/3efcc82765723df5351c5c0a396362474442b505))
* **workflows:** droid-review-shards reusable 移除顶层 concurrency——INFRA-626 系统性收尾 ([#73](https://github.com/hdot123-org/infra-core/issues/73)) ([7f02477](https://github.com/hdot123-org/infra-core/commit/7f024771b3d478302b4127814fd6622ed91bdff7))
* **workflows:** reusable 移除顶层 concurrency——caller 同名组自死锁 ([#72](https://github.com/hdot123-org/infra-core/issues/72)) ([4592006](https://github.com/hdot123-org/infra-core/commit/4592006198e8c6bc5737c7c6ea2002867c6de445))

## [0.5.1](https://github.com/hdot123-org/infra-core/compare/v0.5.0...v0.5.1) (2026-08-29)


### Bug Fixes

* **engine:** __init__ 改 PEP 562 lazy export——消除与消费仓同名裸名模块的 import 碰撞 ([#70](https://github.com/hdot123-org/infra-core/issues/70)) ([becff80](https://github.com/hdot123-org/infra-core/commit/becff809d9e63d7251c6f0e918584cc99ddc36f8))

## [0.5.0](https://github.com/hdot123-org/infra-core/compare/v0.4.0...v0.5.0) (2026-08-29)


### Features

* **auto-merge:** 抽离 auto-merge-pipeline reusable workflow——resolve+triage+merge 执行体（M4 门禁切换基建） ([#65](https://github.com/hdot123-org/infra-core/issues/65)) ([05ca61c](https://github.com/hdot123-org/infra-core/commit/05ca61c6dd13724fada13214efd91379279c17b6))
* **engine:** 移植 INFRA-578/588/597 自愈套件到 evolution 引擎——双向 workflow_dispatch 拉起 + 告警抑制 ([#67](https://github.com/hdot123-org/infra-core/issues/67)) ([2872f94](https://github.com/hdot123-org/infra-core/commit/2872f940ccd20f8690cee25e81d4cc37cf2d63a9))
* **runner:** 重构 Layer 1+2 宿主工具链锁定与共享缓存（取代 PR [#37](https://github.com/hdot123-org/infra-core/issues/37)，INFRA-590） ([#56](https://github.com/hdot123-org/infra-core/issues/56)) ([b146a58](https://github.com/hdot123-org/infra-core/commit/b146a5850aefe80da02f8e762ad180addf4116b7))
* **watchdog:** 抽离 droid-review-watchdog-handlers reusable workflow（M4 门禁切换基建） ([#64](https://github.com/hdot123-org/infra-core/issues/64)) ([0270da1](https://github.com/hdot123-org/infra-core/commit/0270da1434b3307582545798f2b6de204e43e4f0))


### Bug Fixes

* **ci:** droid CLI fallback 下载加 --max-time 300 兜底（Fixes INFRA-613） ([#63](https://github.com/hdot123-org/infra-core/issues/63)) ([80a4461](https://github.com/hdot123-org/infra-core/commit/80a44610a97f8ae97c22093ab718c1838af5057b))

## [0.4.0](https://github.com/hdot123-org/infra-core/compare/v0.3.0...v0.4.0) (2026-08-29)


### Features

* ci-ok 轮询等待 droid-review 完成后再放行（INFRA-598） ([#44](https://github.com/hdot123-org/infra-core/issues/44)) ([3e04580](https://github.com/hdot123-org/infra-core/commit/3e04580bb7096d98487e301b2c2c851b0c635444))
* **droid-review:** Factory CLI 安装宿主优先化——PATH 探测 + 版本下限 gate，缺失才 fallback 下载 ([#62](https://github.com/hdot123-org/infra-core/issues/62)) ([d9489f4](https://github.com/hdot123-org/infra-core/commit/d9489f4c8b4dedd75778bc877e16ee1b658e067b))
* **droid-review:** 抽离 droid-review-shards reusable workflow + aggregate composite（M4 门禁切换基建） ([#59](https://github.com/hdot123-org/infra-core/issues/59)) ([6dfb73a](https://github.com/hdot123-org/infra-core/commit/6dfb73aa998182a4a05b3b244407f0178c1a0c1a))
* enforce zero-red merge policy (ci-ok blocks any red check) ([#38](https://github.com/hdot123-org/infra-core/issues/38)) ([708b995](https://github.com/hdot123-org/infra-core/commit/708b9954e848a8731fcefc6c12d72051ef87f125))
* **gate:** 新增 QA workflow 家族 (gate-infra-qa-workflow) ([#39](https://github.com/hdot123-org/infra-core/issues/39)) ([1e6ae15](https://github.com/hdot123-org/infra-core/commit/1e6ae15058a8ccf36a4d2d3dce9af850866dbf07))
* **runner:** setup-venv fast-fail 加固 + infra-cli venv create 便利入口 ([#45](https://github.com/hdot123-org/infra-core/issues/45)) ([8396748](https://github.com/hdot123-org/infra-core/commit/83967484adfa5535b80fd466f3d5bee102c73287))
* 启用 droid-review 门禁（PR-A：workflow 启用） ([#43](https://github.com/hdot123-org/infra-core/issues/43)) ([0702c9e](https://github.com/hdot123-org/infra-core/commit/0702c9ed981234837e8b58dcfb383a14aff64a13))
* 恢复自仓 auto-merge 触发器（memory-core 同构 + triage 路径修复） ([#48](https://github.com/hdot123-org/infra-core/issues/48)) ([da4ff28](https://github.com/hdot123-org/infra-core/commit/da4ff28970750ccb3bc4ad69cd8f1076f6db2441))


### Bug Fixes

* branch-cleanup 状态隔离重做，基于新 main 重构 PR [#35](https://github.com/hdot123-org/infra-core/issues/35)（INFRA-589） ([#57](https://github.com/hdot123-org/infra-core/issues/57)) ([6cedfe7](https://github.com/hdot123-org/infra-core/commit/6cedfe736d9d7745a21a64d07c3b5f8b7bf5f9a4))
* **ci:** actionlint 步骤宿主优先，免疫 node-00 raw 直连黑洞 ([#53](https://github.com/hdot123-org/infra-core/issues/53)) ([aac6a5a](https://github.com/hdot123-org/infra-core/commit/aac6a5ae8b305ba920cba21bf7586f3cc993882d))
* **ci:** auto-merge 去 checkout 内联 triage 至 RUNNER_TEMP，根除共享工作区 sparse-checkout 污染 ([#50](https://github.com/hdot123-org/infra-core/issues/50)) ([6f615fa](https://github.com/hdot123-org/infra-core/commit/6f615faa7db75a76eeb08447610c49233f760720))
* **ci:** branch-cleanup thin caller 转发仓级 LINEAR_PROJECT_INFRA_CORE_ID（INFRA-606） ([#54](https://github.com/hdot123-org/infra-core/issues/54)) ([f65270b](https://github.com/hdot123-org/infra-core/commit/f65270bab2bc4b122a35dc020deae486f1506e78))
* **ci:** check_droid_review.sh 双副本网络韧性加固 + 副本字节一致防护 ([#58](https://github.com/hdot123-org/infra-core/issues/58)) ([60a3acc](https://github.com/hdot123-org/infra-core/commit/60a3acc97facda17db5107b1363f3995d57be8c8))
* **ci:** gh 调用仓库上下文守卫全量覆盖 engine 与工作流（INFRA-601） ([#51](https://github.com/hdot123-org/infra-core/issues/51)) ([2742171](https://github.com/hdot123-org/infra-core/commit/2742171ba807557a63cacad207786a506b54fc73))
* **ci:** 守卫与 shell 脚本 gh 调用显式仓库上下文，免疫 runner insteadOf 镜像重写 ([#49](https://github.com/hdot123-org/infra-core/issues/49)) ([4ef996a](https://github.com/hdot123-org/infra-core/commit/4ef996a106374e245dd173c819b3578c9651d6de))
* **droid-review:** exit 137 完成期竞态韧性——单次重试 + session jsonl 兜底恢复 ([#55](https://github.com/hdot123-org/infra-core/issues/55)) ([135a1b5](https://github.com/hdot123-org/infra-core/commit/135a1b57d34448743c88cc33e59da55e62b2cb14))
* Linear project 同步按仓库归约 tracking issue（INFRA-586） ([#36](https://github.com/hdot123-org/infra-core/issues/36)) ([ffcc1b1](https://github.com/hdot123-org/infra-core/commit/ffcc1b16b1978839704972fc1c89f9c1e17c4712))
* 零红铁律落地——移除 advisory job 的 continue-on-error（INFRA-595） ([#40](https://github.com/hdot123-org/infra-core/issues/40)) ([833e6b8](https://github.com/hdot123-org/infra-core/commit/833e6b84d5dd579040ead0af3900f672e1bdc615))


### Performance Improvements

* **droid-review:** BYOM 改走 ts 内网直达 Kong，解开公网绕行 ([#47](https://github.com/hdot123-org/infra-core/issues/47)) ([89ef28a](https://github.com/hdot123-org/infra-core/commit/89ef28a85db5a96290a600d680d815701d06bc48))

## [0.3.0](https://github.com/hdot123-org/infra-core/compare/v0.2.0...v0.3.0) (2026-08-27)


### Features

* **ci:** 基础层第二步 - 结构化门禁接线 ([#21](https://github.com/hdot123-org/infra-core/issues/21)) ([38b6289](https://github.com/hdot123-org/infra-core/commit/38b628910f842be31030e08b3add031b4ff7d6e4))
* **ci:** 补齐基础层五道门禁（shellcheck/health-check/repo-consistency/telemetry-audit/business-policy-tests） ([#25](https://github.com/hdot123-org/infra-core/issues/25)) ([9d525d8](https://github.com/hdot123-org/infra-core/commit/9d525d872eb56b93d005b2a5ee6f5ea51cb6daab))
* **guard:** 落地门禁守卫资产与 pytest markers 基础设施 ([#20](https://github.com/hdot123-org/infra-core/issues/20)) ([ad8c756](https://github.com/hdot123-org/infra-core/commit/ad8c756fa888c69d21d172a74e8efc3333d54de6))
* INFRA-583 M4 收尾——branch-cleanup 自仓切 thin caller 并加双副本漂移防护 ([#27](https://github.com/hdot123-org/infra-core/issues/27)) ([e500f37](https://github.com/hdot123-org/infra-core/commit/e500f376ceb38a12f014de6e211474f006815920))
* M4 branch-cleanup composite action（定时+即时双模式） ([#26](https://github.com/hdot123-org/infra-core/issues/26)) ([6cf8bc9](https://github.com/hdot123-org/infra-core/commit/6cf8bc95ddaabbb15b5fc18a23f1c37f63c4c0f3))
* **M4:** 添加 setup-labels reusable workflow 与契约测试 ([#30](https://github.com/hdot123-org/infra-core/issues/30)) ([afe6570](https://github.com/hdot123-org/infra-core/commit/afe65707cdf0695bb1c91b8fbb553d38d9e5e47c))


### Bug Fixes

* 修复 rule_packs 懒加载并更新契约测试 ([#23](https://github.com/hdot123-org/infra-core/issues/23)) ([6164aa3](https://github.com/hdot123-org/infra-core/commit/6164aa3e867e69fe5dd791b0f91652b61f335cb0))

## [0.2.0](https://github.com/hdot123-org/infra-core/compare/v0.1.0...v0.2.0) (2026-08-26)


### Features

* **M3:** version_sync 迁移 ([#18](https://github.com/hdot123-org/infra-core/issues/18)) ([ccf09c3](https://github.com/hdot123-org/infra-core/commit/ccf09c3ade9cba75e48e293271fdb75c05a25c98))

## 0.1.0 (2026-08-26)


### Features

* M1 scaffold - infra-core 组织级演进引擎自举 ([25d438b](https://github.com/hdot123-org/infra-core/commit/25d438b6d66d3a0a236ca1eb7f2ec746cbdd055f))
* M1 scaffold - infra-core 组织级演进引擎自举 ([25be345](https://github.com/hdot123-org/infra-core/commit/25be34504db0db261b5a2e53862354a91c829878))
* memory 规则包迁入 infra-core packs/memory/ ([#12](https://github.com/hdot123-org/infra-core/issues/12)) ([889099d](https://github.com/hdot123-org/infra-core/commit/889099d21868d20b318727364502ad10a517eefe))
* 全量切换自建 runner + per-run venv 隔离（重提，绕开卡死 run） ([#10](https://github.com/hdot123-org/infra-core/issues/10)) ([0764fb2](https://github.com/hdot123-org/infra-core/commit/0764fb225f7e6850a4d1fd8608ef8d3c4085e064))
* 引擎移植（M2）- 自 memory-core 移植演进引擎至 infra-core ([#7](https://github.com/hdot123-org/infra-core/issues/7)) ([ac9e3a1](https://github.com/hdot123-org/infra-core/commit/ac9e3a14341bef2b0dc738833f74d289d08f00f9))
* 配置 release-please 自动发版基建 ([#14](https://github.com/hdot123-org/infra-core/issues/14)) ([49673d3](https://github.com/hdot123-org/infra-core/commit/49673d357060e934d4d8ac63589cd25f1790b02f))


### Bug Fixes

* .gitignore 补全 memory-hook 产物屏蔽（AGENTS.md、tools/） ([#6](https://github.com/hdot123-org/infra-core/issues/6)) ([c98892e](https://github.com/hdot123-org/infra-core/commit/c98892e3d4912c0cb3dd65e53829781222198f8d))
* governance action 脚本路径修复 + 契约测试加固 + .gitignore 防护 ([#5](https://github.com/hdot123-org/infra-core/issues/5)) ([6e9b268](https://github.com/hdot123-org/infra-core/commit/6e9b26809cbdb27d8857e346b8f05925f98d49ca))
* M2 热修——六 workflow 触发器禁用为 dispatch-only 桩 + .evolution 运行态出库 + rule_packs/report-only/pack_tool 单测 ([#8](https://github.com/hdot123-org/infra-core/issues/8)) ([1c664cf](https://github.com/hdot123-org/infra-core/commit/1c664cfd0a5b4f385d02a3e31530e3cda92d0563))
* release-please workflow 使用 DISPATCH_TOKEN 替代 GITHUB_TOKEN ([#15](https://github.com/hdot123-org/infra-core/issues/15)) ([6a1a208](https://github.com/hdot123-org/infra-core/commit/6a1a2086f256cd57d7efed4ca3507987b235556c))
* 修复 ruff 格式问题（空白行、未使用导入） ([29bf650](https://github.com/hdot123-org/infra-core/commit/29bf65065cae5bd13ee21e083362cfc3f9d0ebcc))
* 补齐 cli.py 函数类型注解，满足 mypy --strict 门禁 ([#4](https://github.com/hdot123-org/infra-core/issues/4)) ([dc0a1b8](https://github.com/hdot123-org/infra-core/commit/dc0a1b8b623ff42a0e8d6de4babe756e3c699405))
