# Changelog

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
