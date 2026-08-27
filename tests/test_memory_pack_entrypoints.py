"""INFRA-571: memory 规则包 infra-* CLI 入口点契约测试。

PR #12 迁入 memory 规则包（packs/memory/ + infra-* console scripts + M2
路径/旗标兼容），但入口点契约此前无测试防护。本文件锁定三条契约：

1. pyproject 声明的 5 个 infra-* console scripts 指向的模块/属性可加载，
   且暴露可调用的 main。
2. pack 公开 API（get_tool_specs）给出的工具命令与 pyproject 声明的
   infra-* 脚本名一致（漂移会让 scanner 起错误命令，静默失败）。
3. entry point infra_core.packs=memory 指向的包模块暴露
   get_tool_specs()/get_tool_names()（scanner `_load_pack_tools` 依赖）。
"""

import importlib
import re
from importlib.metadata import distribution
from pathlib import Path

import pytest

from infra_core.packs.memory import get_tool_specs as _get_tool_specs

# pyproject [project.scripts] 中本包声明的 infra-* 入口（名称 → 模块:属性）
EXPECTED_CONSOLE_SCRIPTS: dict[str, str] = {
    "infra-self-audit": "infra_core.engine.evolution_self_audit:main",
    "infra-hygiene-audit": "infra_core.packs.memory.hygiene:main",
    "infra-error-patterns": "infra_core.packs.memory.error_patterns:main",
    "infra-daily-audit": "infra_core.packs.memory.daily_audit:main",
    "infra-layout-audit": "infra_core.packs.memory.layout_audit:main",
}

# 公开 API 视角的工具条目（name/command/timeout）
PACK_TOOL_ENTRIES: list[dict[str, object]] = _get_tool_specs()


def _repo_root() -> Path:
    """测试仓库根（tests/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def _declared_console_scripts() -> dict[str, str]:
    """解析 pyproject.toml 中声明的 console scripts（不依赖 toml 库）。

    pyproject 由本仓库维护，[project.scripts] 段格式稳定，正则解析足够；
    避免 dev 依赖之外引入 toml 解析库。
    """
    pyproject = _repo_root() / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    scripts: dict[str, str] = {}
    in_scripts = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_scripts:
                break
            continue
        if in_scripts and "=" in stripped:
            name, _, target = stripped.partition("=")
            scripts[name.strip()] = target.strip().strip('"').strip("'")
    return scripts


def _installed_console_scripts() -> dict[str, str]:
    """读取已安装发行版注册的 console scripts（entry_points 镜像）。"""
    scripts: dict[str, str] = {}
    for ep in distribution("infra-core").entry_points:
        if ep.group == "console_scripts":
            scripts[ep.name] = ep.value
    return scripts


class TestConsoleScriptDeclarations:
    """契约 1：pyproject 声明 vs 安装元数据 vs 模块可加载性。"""

    def test_pyproject_declares_all_infra_tool_scripts(self):
        """pyproject [project.scripts] 包含全部 5 个 infra-* 工具入口。"""
        declared = _declared_console_scripts()
        for name, target in EXPECTED_CONSOLE_SCRIPTS.items():
            assert declared.get(name) == target, (
                f"console script {name} 声明漂移：期望 {target}，实际 {declared.get(name)}"
            )

    def test_installed_entry_points_match_declarations(self):
        """安装元数据中的 console scripts 与 pyproject 声明一致（editable 安装镜像）。"""
        installed = _installed_console_scripts()
        for name, target in EXPECTED_CONSOLE_SCRIPTS.items():
            assert installed.get(name) == target, (
                f"console script {name} 安装漂移：期望 {target}，实际 {installed.get(name)}。"
                "重新 pip install -e . 后重试。"
            )

    @pytest.mark.parametrize("name,target", sorted(EXPECTED_CONSOLE_SCRIPTS.items()))
    def test_console_script_target_loads_callable_main(self, name: str, target: str):
        """每个 console script 目标可导入且暴露可调用的 main。"""
        module_name, _, attr = target.partition(":")
        module = importlib.import_module(module_name)
        func = getattr(module, attr)
        assert callable(func), f"{name} 的入口 {target} 不是可调用对象"


class TestPackCommandTemplateContract:
    """契约 2：pack 工具 command ↔ pyproject 脚本名一致。"""

    @pytest.mark.parametrize("entry", PACK_TOOL_ENTRIES, ids=lambda e: str(e["name"]))
    def test_command_uses_declared_script(self, entry):
        """每个 pack 工具的命令使用 pyproject 声明的 infra-* 脚本名。"""
        declared = _declared_console_scripts()
        match = re.match(r"^([A-Za-z0-9_-]+)\s", str(entry["command"]) + " ")
        assert match is not None, f"无法解析命令：{entry['command']}"
        command = match.group(1)
        assert command in declared, (
            f"{entry['name']} 的命令 {command} 未在 pyproject [project.scripts] 声明；"
            "scanner 会执行不存在的命令并静默失败"
        )

    def test_every_pack_tool_has_a_script_entry(self):
        """pack 中每个工具都能映射到某个已声明的 infra-* 脚本。"""
        declared = _declared_console_scripts()
        commands = set()
        for entry in PACK_TOOL_ENTRIES:
            match = re.match(r"^([A-Za-z0-9_-]+)\s", str(entry["command"]) + " ")
            if match:
                commands.add(match.group(1))
        assert commands, "pack 工具集为空或全部无法解析"
        missing = {c for c in commands if c not in declared}
        assert not missing, f"pack 命令未声明 console script：{sorted(missing)}"


class TestPackEntryPointDiscovery:
    """契约 3：scanner entry point 发现机制（infra_core.packs 组）。"""

    def test_pack_entry_point_module_path(self):
        """infra_core.packs 组的 memory entry point 指向包模块。"""
        eps = {
            ep.name: ep.value
            for ep in distribution("infra-core").entry_points
            if ep.group == "infra_core.packs"
        }
        assert eps.get("memory") == "infra_core.packs.memory", (
            f"pack entry point 漂移：{eps.get('memory')!r}"
        )

    def test_pack_module_exposes_discovery_api(self):
        """包模块暴露 scanner 依赖的 get_tool_specs / get_tool_names。"""
        from infra_core.packs import memory as memory_pack

        assert callable(memory_pack.get_tool_specs)
        assert callable(memory_pack.get_tool_names)

    def test_get_tool_specs_shape(self):
        """get_tool_specs 输出可被 scanner 合并的 audit_tools 条目。"""
        from infra_core.packs import memory as memory_pack

        specs = memory_pack.get_tool_specs()
        assert specs, "memory pack 应至少注册一个工具"
        for entry in specs:
            assert entry["name"], "条目缺少 name"
            assert entry["command"], f"{entry['name']} 缺少 command"
            assert entry["output_format"] == "json"
            assert isinstance(entry["timeout"], int) and entry["timeout"] > 0

    def test_tool_names_match_specs(self):
        """get_tool_names 与 get_tool_specs 的 name 集一致。"""
        from infra_core.packs import memory as memory_pack

        assert memory_pack.get_tool_names() == [e["name"] for e in memory_pack.get_tool_specs()]
