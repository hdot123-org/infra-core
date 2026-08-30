"""pack↔engine 接缝三缺陷修复的契约与行为测试（m5 消费接线前置）。

三个已实证缺陷（scrutiny R1）：
1. error_patterns ToolSpec 声明 output_format=json，但工具 --json 实际输出
   JSONL——run_audit_tool 的单次 json.loads 遇 2+ 条模式必炸（Extra data）。
   修复：声明 jsonl + run_audit_tool 增加 jsonl stdout 解析路径。
2. 工具名漂移：pack 定义 layout_audit/code_hygiene vs engine
   ADAPTER_MAP/TOOL_TO_CATEGORIES 键 audit_layout/code_hygiene_audit——
   adapters 静默 no-op。修复：pack 统一为 engine 侧键名（命名契约锚点）。
3. daily_kb_audit 模板丢 --no-infra 与写抑制——消费者扫描会写宿主
   ~/.memory-core/audit/ 并探测宿主 inventory（越界写）。修复：补齐
   --no-infra --report-only。
"""

import json
import sys
from unittest.mock import MagicMock, patch

from infra_core.engine.evolution_adapters import ADAPTER_MAP, TOOL_TO_CATEGORIES
from infra_core.engine.evolution_scanner import run_audit_tool
from infra_core.packs.memory import TOOL_TO_CATEGORIES as PACK_TOOL_TO_CATEGORIES
from infra_core.packs.memory import get_tool_names, get_tool_specs

# engine 侧键名（命名契约锚点）：code_hygiene_audit 输出已是归一化 findings
# 列表（原版行为），无 adapter 属预期；其余四个工具都有 engine adapter。
EXPECTED_PACK_TOOL_NAMES = {
    "daily_kb_audit",
    "audit_layout",
    "code_hygiene_audit",
    "error_patterns",
    "evolution_self_audit",
}
EXPECTED_ADAPTERED_TOOLS = {
    "daily_kb_audit",
    "audit_layout",
    "error_patterns",
    "evolution_self_audit",
}


def _spec_by_name(name: str) -> dict:
    """按名取 pack 导出的 audit_tools 条目。"""
    specs = {s["name"]: s for s in get_tool_specs()}
    assert name in specs, f"pack 未定义工具 {name}"
    return specs[name]


class TestToolNameContract:
    """缺陷 2：pack 工具名与 engine ADAPTER_MAP/TOOL_TO_CATEGORIES 键完全一致。"""

    def test_pack_tool_names_are_engine_side_keys(self):
        """pack 工具名集合 == engine 侧键名集合（layout_audit/code_hygiene 漂移名禁再出现）。"""
        names = set(get_tool_names())
        assert names == EXPECTED_PACK_TOOL_NAMES, (
            f"pack 工具名漂移：{sorted(names ^ EXPECTED_PACK_TOOL_NAMES)}"
        )

    def test_every_pack_tool_name_tracked_by_engine_categories(self):
        """每个 pack 工具名都在 engine TOOL_TO_CATEGORIES 中有键（update_history 依赖）。"""
        missing = set(get_tool_names()) - set(TOOL_TO_CATEGORIES)
        assert not missing, f"engine TOOL_TO_CATEGORIES 缺少 pack 工具键: {sorted(missing)}"

    def test_adaptered_pack_tools_present_in_adapter_map(self):
        """有 adapter 的 pack 工具名都必须命中 engine ADAPTER_MAP（否则静默 no-op）。"""
        missing = EXPECTED_ADAPTERED_TOOLS - set(ADAPTER_MAP)
        assert not missing, f"engine ADAPTER_MAP 缺少 pack 工具键: {sorted(missing)}"

    def test_pack_tool_to_categories_match_engine_values(self):
        """pack 导出的 TOOL_TO_CATEGORIES 与 engine 侧同键同值。"""
        for name, categories in PACK_TOOL_TO_CATEGORIES.items():
            assert TOOL_TO_CATEGORIES.get(name) == categories, (
                f"{name} 的 category 集合与 engine 侧不一致: "
                f"pack={categories} engine={TOOL_TO_CATEGORIES.get(name)}"
            )


class TestErrorPatternsOutputFormat:
    """缺陷 1：error_patterns 输出（JSONL）与 ToolSpec 声明一致，run_audit_tool 全路径可解析。"""

    def test_error_patterns_declares_jsonl(self):
        assert _spec_by_name("error_patterns")["output_format"] == "jsonl"

    def test_other_pack_tools_declare_json(self):
        for name in EXPECTED_PACK_TOOL_NAMES - {"error_patterns"}:
            assert _spec_by_name(name)["output_format"] == "json", f"{name} 应声明 json"

    @staticmethod
    def _registry_entry(fp: str, etype: str, script: str, msg: str, count: int, threshold: str):
        return {
            "fingerprint": fp,
            "type": etype,
            "script": script,
            "normalized_msg": msg,
            "status": "detected",
            "total_count": count,
            "threshold_met": threshold,
        }

    def test_run_audit_tool_parses_multiple_jsonl_lines(self):
        """回归：2+ 条模式下旧单次 json.loads 必炸（Extra data），jsonl 路径必须出 findings。"""
        tool = {"name": "error_patterns", "output_format": "jsonl", "command": "echo"}
        stdout = (
            json.dumps(self._registry_entry("a" * 16, "llm_api_error", "svc_a", "m1", 5, "both"))
            + "\n"
            + json.dumps(self._registry_entry("b" * 16, "timeout", "svc_b", "m2", 2, "days"))
            + "\n"
        )
        with patch("infra_core.engine.evolution_scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            result = run_audit_tool(tool)
        assert result is not None
        assert len(result) == 2
        assert result[0]["rule_id"] == "ERROR_PATTERN_LLM_API_ERROR"
        assert result[0]["severity"] == "critical"
        assert result[1]["rule_id"] == "ERROR_PATTERN_TIMEOUT"
        assert result[1]["severity"] == "warning"

    def test_run_audit_tool_jsonl_single_line(self):
        tool = {"name": "error_patterns", "output_format": "jsonl", "command": "echo"}
        stdout = (
            json.dumps(self._registry_entry("c" * 16, "timeout", "svc", "m", 5, "count")) + "\n"
        )
        with patch("infra_core.engine.evolution_scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            result = run_audit_tool(tool)
        assert result is not None
        assert len(result) == 1
        assert result[0]["rule_id"] == "ERROR_PATTERN_TIMEOUT"

    def test_run_audit_tool_jsonl_empty_stdout_returns_none(self):
        """0 条模式：空 stdout 维持引擎既有语义（tool failure，非 []）。"""
        tool = {"name": "error_patterns", "output_format": "jsonl", "command": "echo"}
        with patch("infra_core.engine.evolution_scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = run_audit_tool(tool)
        assert result is None

    def test_run_audit_tool_jsonl_all_malformed_returns_none(self):
        """全 malformed JSONL → tool failure（None），不得伪造 findings。"""
        tool = {"name": "error_patterns", "output_format": "jsonl", "command": "echo"}
        with patch("infra_core.engine.evolution_scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{broken\n{x\n", stderr="")
            with patch("builtins.print"):
                result = run_audit_tool(tool)
        assert result is None

    def test_run_audit_tool_jsonl_mixed_lines_skips_malformed(self):
        """混合行：合法行照常出 findings，malformed 行告警跳过（与 registry_jsonl 等价）。"""
        tool = {"name": "error_patterns", "output_format": "jsonl", "command": "echo"}
        stdout = (
            json.dumps(self._registry_entry("d" * 16, "timeout", "svc", "m", 5, "count"))
            + "\n{broken json\n"
            + json.dumps(self._registry_entry("e" * 16, "timeout", "svc2", "m2", 5, "count"))
            + "\n"
        )
        with patch("infra_core.engine.evolution_scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            with patch("builtins.print") as mock_print:
                result = run_audit_tool(tool)
        assert result is not None
        assert len(result) == 2
        warning_calls = [str(c) for c in mock_print.call_args_list]
        assert any("malformed" in w for w in warning_calls), warning_calls

    def test_error_patterns_tool_end_to_end_jsonl_parseable(self, tmp_path):
        """真实 error_patterns 子进程 + run_audit_tool 全链路：2+ 模式可解析（原崩溃场景）。"""
        log_dir = tmp_path / "memory" / "log"
        log_dir.mkdir(parents=True)
        entries = []
        # 模式 A：days>=2 且 count>=5 → threshold both（critical）
        for day in ("2026-08-28", "2026-08-29"):
            for i in range(3):
                entries.append(
                    {
                        "ts": f"{day}T10:00:0{i}+08:00",
                        "type": "llm_api_error",
                        "script": "svc_a",
                        "project": str(tmp_path),
                        "msg": "boom alpha",
                    }
                )
        # 模式 B：days>=2 → threshold days（warning）
        for day in ("2026-08-28", "2026-08-29"):
            entries.append(
                {
                    "ts": f"{day}T11:00:00+08:00",
                    "type": "timeout",
                    "script": "svc_b",
                    "project": str(tmp_path),
                    "msg": "boom beta",
                }
            )
        (log_dir / "session-errors.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )
        tool = {
            "name": "error_patterns",
            "output_format": "jsonl",
            "command": (
                f"{sys.executable} -m infra_core.packs.memory.error_patterns"
                " --repo-root {repo_root} --json"
            ),
        }
        result = run_audit_tool(tool, tmp_path)
        assert result is not None
        assert len(result) == 2, f"两条阈值命中模式都应产出 findings，实际 {result}"
        assert {f["rule_id"] for f in result} == {
            "ERROR_PATTERN_LLM_API_ERROR",
            "ERROR_PATTERN_TIMEOUT",
        }


class TestDailyAuditConsumerSafety:
    """缺陷 3：消费者扫描零宿主写——--no-infra 与 --report-only 模板契约 + 行为锁。"""

    def test_daily_kb_audit_command_includes_no_infra_and_report_only(self):
        """越界写测试锁：pack 模板必须带 --no-infra（禁探测宿主 inventory）
        与 --report-only（禁写宿主 ~/.memory-core/audit/）。"""
        command = _spec_by_name("daily_kb_audit")["command"]
        assert "--no-infra" in command, f"daily_kb_audit 模板缺 --no-infra: {command}"
        assert "--report-only" in command, f"daily_kb_audit 模板缺 --report-only: {command}"

    def test_report_only_writes_nothing_to_host_home(self, tmp_path, monkeypatch):
        """行为锁：沙箱化 HOME 下真实跑 daily_kb_audit 扫描，宿主状态目录零创建。"""
        sandbox_home = tmp_path / "sandbox-home"
        sandbox_home.mkdir()
        project = tmp_path / "proj"
        (project / "memory" / "system").mkdir(parents=True)
        (project / "memory" / "system" / "memory.lock").write_text(
            '[memory]\nmemory_version = "0.0.0"\n', encoding="utf-8"
        )
        monkeypatch.setenv("HOME", str(sandbox_home))
        monkeypatch.delenv("INFRA_MEMORY_CORE_HOME", raising=False)
        monkeypatch.delenv("INFRA_GLOBAL_KB_ROOT", raising=False)
        tool = {
            "name": "daily_kb_audit",
            "output_format": "json",
            "command": (
                f"{sys.executable} -m infra_core.packs.memory.daily_audit"
                " --repo-root {repo_root} --no-infra --report-only --json"
            ),
        }
        result = run_audit_tool(tool, project)
        assert result is not None, "--json 单对象 stdout 应经 adapt_daily_audit 可解析"
        assert any(f["rule_id"] == "HASH_MISMATCH" for f in result), (
            "缺 manifest 的 fixture 应产出完整性违规（证明审计真实执行）"
        )
        # 宿主状态目录零写入（越界写禁令）
        assert not (sandbox_home / ".memory-core").exists()
        assert not (sandbox_home / ".memory").exists()
