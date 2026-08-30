"""evolution config 契约：error_patterns 走 pack 模板原生 jsonl 路径。

INFRA-647（对齐 memory-core tests/test_evolution_config_contract.py 同款
迁移）：infra v0.5.1 引擎 run_audit_tool 不支持 output_format=jsonl stdout
时，本仓 dogfood 配置用 registry_jsonl inline override 保住 error_patterns
扫描连续性；引擎补 jsonl 逐行解析分支（infra-core #80，v0.6.1 原生内置）
后移除 override，回归 memory pack 模板原生路径。本测试锁定：

1. config 声明 rule_packs: [{pack: memory}]；
2. error_patterns 不再有 inline override（registry_jsonl 文件模式退场）；
3. resolve_rule_packs 展开后 error_patterns 来自 pack 模板且声明 jsonl
   （pack 定义即本仓 src/infra_core/packs/memory/pack.py 的
   ToolSpec.output_format 契约，不涉及外部 pin）；
4. legacy memory-* inline 条目（daily_kb_audit / audit_layout /
   code_hygiene_audit / evolution_self_audit 的 memory-core 协议栈形态）
   保留原样——同键名 inline 条目覆盖 pack 定义，行为与迁移前一致。
"""

from pathlib import Path

import yaml

from infra_core.engine.evolution_scanner import resolve_rule_packs

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".evolution" / "config.yml"


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_rule_packs_declares_memory_pack() -> None:
    config = _load_config()
    assert config.get("rule_packs") == [{"pack": "memory"}]


def test_error_patterns_inline_override_removed() -> None:
    config = _load_config()
    inline_names = {t.get("name") for t in config.get("audit_tools", [])}
    assert "error_patterns" not in inline_names, (
        "error_patterns registry_jsonl inline override 应已移除（pack 模板原生 jsonl 路径）"
    )


def test_legacy_inline_tools_retained() -> None:
    """memory-core 协议栈 inline 条目保留，同键名覆盖 pack 定义（行为不变）。"""
    config = _load_config()
    inline = {t["name"]: t for t in config.get("audit_tools", [])}
    assert inline["daily_kb_audit"]["command"] == "memory-audit-daily --json --no-infra"
    assert inline["consistency_check"]["command"] == "memory-consistency-check --json"
    assert inline["audit_layout"]["command"] == "memory-audit-layout --target . --json"
    assert inline["validate_project"]["command"] == "memory-validate --target . --json"
    assert inline["evolution_self_audit"]["command"] == "memory-evolution-audit --json"
    assert inline["code_hygiene_audit"]["command"] == "memory-code-hygiene-audit --target . --json"


def test_error_patterns_resolves_to_pack_jsonl_template() -> None:
    config = _load_config()
    # 未知 pack 会 sys.exit(1)——rule_packs: [memory] 必须可解析展开
    resolve_rule_packs(config)
    tool = next(t for t in config["audit_tools"] if t["name"] == "error_patterns")
    assert tool["output_format"] == "jsonl", (
        "error_patterns 必须来自 pack 模板且声明 jsonl（#80 jsonl stdout 分支）"
    )
    assert "infra-error-patterns" in tool["command"]
    assert "{repo_root}" in tool["command"], "pack 模板命令必须带 {repo_root} 占位符"
