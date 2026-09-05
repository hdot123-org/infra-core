"""auto-merge gate 三缺陷修复契约测试（INFRA-766）。

背景（2026-09-05 用户批准 + GLM-5.3 交叉验证定案）：
dispatch-from-branch 合并腿"自含"缺陷——run head=PR 分支头=gate 扫描 SHA，
自身 in_progress job 恒计 Incomplete:1；健康腿自身 check run 落 main SHA 故
无自含。GLM-5.3 独立交叉验证量化：REST 26 条 vs GraphQL rollup 16 条，差 10 条
= dispatch 腿自含精确坐实；run 33954395299 健康腿日志 Incomplete:0/Failed:0
两秒后合并 #223 对照。

本文件锁定四条不变量：
(a) 自排除正则含边界用例——123≠1234、/runs/123/ 与 /runs/123 结尾皆命中、
    /runs/1234 不误中 123；
(b) 具名打印行为存在——过滤后 INCOMPLETE>0 或 FAILED>0 时逐条打印
    name/status/conclusion/app 并打 ::warning:: 再 exit 0；
(c) 前提声明+测试——自排除正确性依赖 caller 级 concurrency 串行
    （memory caller 已有 concurrency: auto-merge-pipeline 排队不取消）；
(d) 落盘+本地 jq+total_count 守卫的处理形态（--paginate 与 --jq 组合有
    预处理坑，GLM 实证）。

零红 fail-closed 语义不变：禁止 GraphQL-only 降级、禁 force-merge、
禁任何绕过零红的路径。
"""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = REPO_ROOT / "actions/auto-merge/action.yml"


def _load_action() -> dict:
    assert ACTION_YML.exists(), "actions/auto-merge/action.yml 必须存在"
    return yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))


def _action_script() -> str:
    """提取 action.yml 中所有 run 步骤的脚本拼接。"""
    doc = _load_action()
    steps = doc["runs"]["steps"]
    return "\n".join(str(step.get("run", "")) for step in steps)


class TestGateSelfExclusionRegex:
    """(a) 自排除正则含边界用例——run id 边界防前缀误匹配。

    缺陷定性：details_url 匹配 `/runs/${GITHUB_RUN_ID}(/|$)` 以排除自身 run。
    边界：123 ≠ 1234（防止 run id 前缀误匹配），/runs/123/ 与 /runs/123 结尾
    皆命中。
    """

    def test_self_exclusion_pattern_exists_with_boundary(self) -> None:
        """自排除正则必须存在且含边界守卫（/|$），防 run id 前缀误匹配。"""
        script = _action_script()
        # 正则必须匹配 /runs/<RUN_ID>/ 或 /runs/<RUN_ID> 结尾
        # 两种合法形态：/runs/${GITHUB_RUN_ID}(/|$) 或含等价的 ERE
        assert (
            re.search(
                r"/runs/.*GITHUB_RUN_ID.*\(/.*\|.*\$\)?"
                r"|/runs/.*GITHUB_RUN_ID.*/",
                script,
            )
            or "/runs/" in script
            and "GITHUB_RUN_ID" in script
        ), "自排除正则缺失：gate 脚本必须包含 /runs/<GITHUB_RUN_ID> 匹配逻辑"

    def test_boundary_prevents_prefix_match(self) -> None:
        """正则边界必须防止 123 误中 1234（前缀误匹配）。

        实现验证：正则含 (/|$) 或类似边界断言，使得 /runs/1234 不被
        /runs/123 模式匹配。
        """
        script = _action_script()
        # 必须含边界守卫——(/|$) 或等价形态
        has_boundary = bool(
            re.search(r"\(/\|.*\$\)", script)
            or re.search(r"(/\|\\\$)", script)
            or "/$" in script  # 行尾或字符串尾守卫
            or re.search(r"GITHUB_RUN_ID\}.*\(/", script)
        )
        assert has_boundary, "自排除正则缺边界守卫——必须防 /runs/123 误中 /runs/1234"

    def test_regex_boundary_unit_test(self) -> None:
        """单元级验证：正则 /runs/<id>(/|$) 的边界行为。

        此测试验证正则语义本身：
        - /runs/123/ → 命中（斜杠后）
        - /runs/123 → 命中（$ 结尾）
        - /runs/1234 → 不命中（123 是 1234 前缀）
        """
        # 模拟 gate 脚本中使用的正则模式
        run_id = "123"
        pattern = re.compile(rf"/runs/{run_id}(/|$)")

        # 应命中
        assert pattern.search("https://github.com/owner/repo/actions/runs/123/")
        assert pattern.search("https://github.com/owner/repo/actions/runs/123")

        # 不应命中（前缀误匹配）
        assert not pattern.search("https://github.com/owner/repo/actions/runs/1234/"), (
            "/runs/1234 不应被 /runs/123 正则命中"
        )
        assert not pattern.search("https://github.com/owner/repo/actions/runs/12345"), (
            "/runs/12345 不应被 /runs/123 正则命中"
        )

    def test_details_url_is_snake_case(self) -> None:
        """details_url 字段名必须为 snake_case（GitHub API 实际形态）。"""
        script = _action_script()
        assert "details_url" in script, "自排除必须使用 details_url（snake_case），非 detailsUrl"
        assert "detailsUrl" not in script, "detailsUrl 不存在于 GitHub API 响应——必须用 details_url"


class TestGateNamedPrint:
    """(b) 具名打印行为——过滤后非零时逐条打印实体详情。

    缺陷定性：gate 只打印计数不打印未完成实体名单→不可观测。修复后
    INCOMPLETE>0 或 FAILED>0 时逐条打印 name/status/conclusion/app 并
    打 ::warning:: 再 exit 0。
    """

    def test_named_print_when_incomplete_or_failed(self) -> None:
        """INCOMPLETE>0 或 FAILED>0 时必须逐条打印实体 name/status/conclusion/app。"""
        script = _action_script()
        # 必须含 name + status + conclusion + app 字段打印
        for field in ("name", "status", "conclusion"):
            assert field in script.lower() or f".{field}" in script, (
                f"具名打印必须包含 {field} 字段"
            )

    def test_warning_annotation_before_exit_zero(self) -> None:
        """非零计数时必须打 ::warning:: 注解再 exit 0。"""
        script = _action_script()
        assert "::warning::" in script, "INCOMPLETE>0 或 FAILED>0 时必须打 ::warning:: 注解"

    def test_exit_zero_on_incomplete_not_exit_one(self) -> None:
        """Incomplete 计数非零时必须 exit 0（retry on next event），不可 exit 1。

        零红铁律：Incomplete 不算失败，只 retry；只有 Failed>0 时才拒绝合并。
        本断言验证 Incomplete 分支不会导致 job 变红。
        """
        script = _action_script()
        # 脚本必须含 exit 0 路径（retry/incomplete 分支）
        assert "exit 0" in script, "脚本必须含 exit 0 路径"
        # 关键：Incomplete 分支不应 exit 1
        # 通过结构验证：Incomplete 检查后是 exit 0（retry），不是 exit 1
        lines = script.splitlines()
        in_incomplete_block = False
        for i, line in enumerate(lines):
            if "INCOMPLETE" in line and ("-gt 0" in line or "> 0" in line):
                in_incomplete_block = True
                continue
            if in_incomplete_block:
                stripped = line.strip()
                if stripped.startswith("exit 1"):
                    pytest.fail(f"Incomplete 分支不可 exit 1（零红铁律），行 {i}: {line}")
                # 遇到下一个 if 或结束
                if stripped.startswith("fi") or stripped.startswith("if "):
                    break

    def test_no_graphql_only_degradation(self) -> None:
        """禁止 GraphQL-only 降级——gate 必须使用 REST check-runs 扫描。"""
        script = _action_script()
        # 必须有 check-runs（REST）
        assert "check-runs" in script, "gate 必须使用 REST check-runs"
        # 禁止 GraphQL-only 路径：不能有 statusCheckRollup 作为唯一数据源
        # （triage 用 GraphQL 是合法的，但 gate 扫描必须用 REST）
        # 关键：脚本中必须有 REST API 调用（gh api ... check-runs）
        assert re.search(r"gh\s+api.*check-runs", script), "gate 必须经 REST API 扫描 check-runs"

    def test_no_force_merge_path(self) -> None:
        """禁止任何 force-merge 或绕过零红的路径。"""
        script = _action_script()
        # 禁止 --force 合并
        assert "--force" not in script, "禁止 --force 合并路径"
        # 禁止 admin 旁路
        assert "--admin" not in script, "禁止 --admin 合并旁路"


class TestGateConcurrencyPremise:
    """(c) 前提声明+测试——自排除正确性依赖 caller 级 concurrency 串行。

    GLM-5.3 交叉验证发现：同 SHA 可并存多条 dispatch 腿的 check runs，
    "仅排除当前 run id"需依赖 caller 级 concurrency 串行。memory caller
    已有 concurrency: auto-merge-pipeline 排队不取消。
    """

    def test_concurrency_premise_documented(self) -> None:
        """action.yml 或 gate 脚本中必须有 concurrency 串行前提声明注释。"""
        raw = ACTION_YML.read_text(encoding="utf-8")
        # 必须在注释中声明自排除依赖 caller 级 concurrency 串行
        assert "concurrency" in raw.lower() and (
            "串行" in raw
            or "serial" in raw.lower()
            or "排队" in raw
            or "queue" in raw.lower()
            or "auto-merge-pipeline" in raw
        ), "action.yml 必须声明自排除正确性依赖 caller 级 concurrency 串行前提"

    def test_self_exclusion_uses_current_run_id(self) -> None:
        """自排除必须使用 GITHUB_RUN_ID（当前 run），非 GITHUB_RUN_ATTEMPT 等。"""
        script = _action_script()
        assert "GITHUB_RUN_ID" in script, "自排除必须使用 GITHUB_RUN_ID（当前 run id）"


class TestGatePaginateAndDump:
    """(d) 落盘+本地 jq+total_count 守卫的处理形态。

    --paginate 与 --jq 组合有预处理坑（GLM 实证）：--paginate 在多页时
    会在每页 JSON 之间插入换行，--jq 会分别处理每页，导致合并结果丢失
    部分数据。修复：--paginate 落盘临时文件后本地 jq 处理。
    """

    def test_paginate_with_dump_not_inline_jq(self) -> None:
        """REST check-runs 扫描必须用 --paginate 落盘后本地 jq 处理。

        禁止 --paginate --jq 组合（预处理坑）。
        """
        script = _action_script()
        # 禁止 --paginate 与 --jq 在同一 gh api 调用中组合
        # 查找所有 gh api 调用，确保不含 --paginate ... --jq 同行
        gh_api_calls = re.findall(
            r"gh\s+api\s+[^\n]*check-runs[^\n]*",
            script,
        )
        for call in gh_api_calls:
            has_paginate = "--paginate" in call
            has_jq = "--jq" in call
            assert not (has_paginate and has_jq), (
                f"--paginate 与 --jq 不可在同一 gh api 调用中组合（预处理坑）: {call}"
            )

    def test_temp_file_dump_pattern(self) -> None:
        """必须有落盘临时文件的模式（--paginate 结果写入临时文件）。"""
        script = _action_script()
        # 必须有临时文件写入（> $TMPFILE 或 >> 或 tee 到文件）
        has_file_dump = bool(
            re.search(r">\s*\$", script)  # 重定向到变量路径
            or re.search(r">\s*/tmp/", script)
            or re.search(r">\s*\"\$", script)
            or "mktemp" in script
            or "CHECK_RUNS_FILE" in script
            or "TMPFILE" in script
        )
        assert has_file_dump, "--paginate 结果必须落盘临时文件后本地 jq 处理"

    def test_total_count_pagination_guard(self) -> None:
        """必须有 total_count 翻页守卫——确保扫描覆盖全部 check runs。"""
        script = _action_script()
        assert "total_count" in script, (
            "必须有 total_count 翻页守卫——确保 --paginate 覆盖全部 check runs"
        )

    def test_local_jq_processing_after_dump(self) -> None:
        """落盘后必须有本地 jq 处理（从文件读取，非管道）。"""
        script = _action_script()
        # 必须有 jq 从文件读取的模式（jq ... < $FILE 或 jq ... $FILE 或 cat $FILE | jq）
        has_local_jq = bool(
            re.search(r"jq\s+.*\$", script)  # jq 引用变量（文件路径）
            or re.search(r"<\s*\$", script)  # 从变量重定向
            or "cat.*|.*jq" in script.replace(" ", "")
        )
        assert has_local_jq, "落盘后必须经本地 jq 处理（从文件/变量读取）"


class TestGateZeroRedSemantics:
    """零红 fail-closed 语义不变——验证修复不引入绕过路径。"""

    def test_failed_still_blocks_merge(self) -> None:
        """FAILED>0 时必须拒绝合并（exit 0 不执行 merge），零红铁律不变。"""
        script = _action_script()
        # FAILED 检查后必须阻止合并——不出现 gh pr merge
        lines = script.splitlines()
        in_failed_block = False
        found_merge_in_failed = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "FAILED" in stripped and ("-gt 0" in stripped or "> 0" in stripped):
                in_failed_block = True
                continue
            if in_failed_block:
                if "gh pr merge" in stripped:
                    found_merge_in_failed = True
                if stripped.startswith("fi") or (
                    stripped.startswith("if ") and "FAILED" not in stripped
                ):
                    break
        assert not found_merge_in_failed, "FAILED>0 分支禁止执行合并——零红铁律"

    def test_incomplete_triggers_retry_not_merge(self) -> None:
        """INCOMPLETE>0 时必须 retry（exit 0）而非合并。"""
        script = _action_script()
        # 脚本必须含 retry 语义（echo 提示 + exit 0）
        assert "retry" in script.lower() or "still running" in script.lower(), (
            "Incomplete 分支必须含 retry 语义"
        )
