"""check_config_yml 的 rule_packs 展开计数契约。

M5 收缩后消费仓 config.yml 以 rule_packs 引用 pack 工具（memory 仓实测：
2 个裸 audit_tools + memory pack 5 工具 = 生效 7）。check_config_yml 若只数
裸 audit_tools 列表，pack 化配置每 tick 恒报 EVOLUTION_CONFIG_INSUFFICIENT
（findings 恒 1 → 消费仓 issue 永久 open → heartbeat 持续
"found issue without PR" 告警）。

契约：
- 计数与 scanner 实际生效工具集一致（resolve_rule_packs 展开后的 enabled
  工具数），仅声明 rule_packs 的配置必须 PASS；
- enabled:false 的条目不计入（与 scanner 语义一致）；
- 畸形 rule_packs 转为 finding，不中止整个 self-audit run；
- resolve 的提示行不得污染 stdout（main() 输出必须保持纯 JSON）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# Engine modules (transplanted from memory-core scripts/) live in src/infra_core/engine
_engine_dir = Path(__file__).resolve().parent.parent / "src" / "infra_core" / "engine"
sys.path.insert(0, str(_engine_dir))

from evolution_self_audit import check_config_yml


def _write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / ".evolution" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content)
    return config_path


def _rule_ids(findings: list[dict]) -> list[str]:
    return [f["rule_id"] for f in findings]


def _insufficient(findings: list[dict]) -> dict | None:
    for finding in findings:
        if finding["rule_id"] == "EVOLUTION_CONFIG_INSUFFICIENT":
            return finding
    return None


def test_rule_packs_only_config_passes(tmp_path, monkeypatch):
    """仅以 rule_packs 声明工具（满编 memory pack = 5 生效工具）的配置应 PASS。"""
    config_path = _write_config(tmp_path, "rule_packs:\n  - pack: memory\n")
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    findings = check_config_yml()
    assert "EVOLUTION_CONFIG_INSUFFICIENT" not in _rule_ids(findings)


def test_inline_plus_rule_packs_passes(tmp_path, monkeypatch):
    """memory 仓实测形态：2 个裸工具 + pack 5 工具 = 7 生效工具，应 PASS。"""
    config_path = _write_config(
        tmp_path,
        "rule_packs:\n"
        "  - pack: memory\n"
        "audit_tools:\n"
        "  - name: consistency_check\n"
        '    command: "memory-consistency-check --json"\n'
        "    output_format: json\n"
        "  - name: validate_project\n"
        '    command: "memory-validate --target . --json"\n'
        "    output_format: json\n",
    )
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    findings = check_config_yml()
    assert "EVOLUTION_CONFIG_INSUFFICIENT" not in _rule_ids(findings)


def test_insufficient_config_still_flagged(tmp_path, monkeypatch):
    """无 rule_packs 且裸工具数低于阈值的配置仍报 INSUFFICIENT——护栏不丢。"""
    config_path = _write_config(
        tmp_path,
        "audit_tools:\n"
        "  - name: only_one\n"
        '    command: "some-tool --json"\n'
        "    output_format: json\n",
    )
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    findings = check_config_yml()
    insufficient = _insufficient(findings)
    assert insufficient is not None
    assert "count=1" in insufficient["evidence"]


def test_disabled_tools_excluded_from_count(tmp_path, monkeypatch):
    """enabled:false 条目不计入生效工具数——与 scanner 实际运行集一致。

    构造：pack 5 工具 - audit_layout（inline enabled:false 覆盖禁用）= 4 < 阈值
    → 应报 INSUFFICIENT 且 evidence count=4（若误数禁用条目则为 5/1，不命中）。
    """
    config_path = _write_config(
        tmp_path,
        "rule_packs:\n"
        "  - pack: memory\n"
        "audit_tools:\n"
        "  - name: audit_layout\n"
        "    pack_tool: audit_layout\n"
        "    enabled: false\n",
    )
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    findings = check_config_yml()
    insufficient = _insufficient(findings)
    assert insufficient is not None
    assert "count=4" in insufficient["evidence"]


def test_unknown_pack_reports_finding_not_crash(tmp_path, monkeypatch):
    """rule_packs 指向未知 pack：resolve 的 sys.exit 转为 finding，不中止 run。"""
    config_path = _write_config(tmp_path, "rule_packs:\n  - pack: no_such_pack\n")
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    findings = check_config_yml()  # 不得抛 SystemExit
    assert "EVOLUTION_CONFIG_INVALID" in _rule_ids(findings)


def test_resolution_logs_do_not_pollute_stdout(tmp_path, monkeypatch, capsys):
    """resolve 的提示行（Disabled audit tools 等）不得进入 stdout——main() 纯 JSON。"""
    config_path = _write_config(
        tmp_path,
        "rule_packs:\n"
        "  - pack: memory\n"
        "audit_tools:\n"
        "  - name: audit_layout\n"
        "    pack_tool: audit_layout\n"
        "    enabled: false\n",
    )
    monkeypatch.setattr("evolution_self_audit.EVOLUTION_CONFIG", config_path)
    check_config_yml()
    captured = capsys.readouterr()
    assert "[evolution]" not in captured.out
