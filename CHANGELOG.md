# Changelog

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
