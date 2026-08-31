"""droid-review-aggregate composite action 契约测试（M4 gate-droid-review）

锁定聚合发布 composite 的不变量：
- composite 形态（不改 caller 的 check 名——`droid-review` 精确契约）
- 内嵌 publish_findings.py 与引擎权威副本字节一致（自包含分发，先例：
  actions/branch-cleanup 的 test_branch_cleanup_action_copies.py）
- composite 内禁止 vars./secrets. context 引用（GitHub composite 上下文不可用，
  2026-08-27 branch-cleanup vars 事故先例；token 由 caller 以 input 传入）
- artifact 下载 pattern 保持 droid-review-debug- 前缀
- run 块引用脚本必须在 action 目录内解析（$GITHUB_ACTION_PATH，禁止 ../ 越出）
- 字节一致副本的 duplicate findings 由 suppress.json 精确抑制且双向契约锁定（INFRA-681）
"""

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_DIR = REPO_ROOT / "actions/droid-review-aggregate"
ACTION_YML = ACTION_DIR / "action.yml"
ENGINE_PUBLISH = REPO_ROOT / "src/infra_core/engine/droid_review/publish_findings.py"


@pytest.fixture(scope="module")
def action_data() -> dict:
    return yaml.safe_load(ACTION_YML.read_text())


class TestCompositeShape:
    def test_is_composite(self, action_data):
        assert action_data["runs"]["using"] == "composite"

    def test_required_inputs(self, action_data):
        inputs = action_data["inputs"]
        for name in (
            "github-token",
            "pr-number",
            "head-sha",
            "docs-only",
            "shards",
            "shards-result",
        ):
            assert name in inputs, f"composite 缺少 input: {name}"
        assert inputs["github-token"].get("required") is True

    def test_all_run_steps_declare_shell(self, action_data):
        """composite run 步骤必须显式 shell: bash（缺省即失败）"""
        for step in action_data["runs"]["steps"]:
            if "run" in step:
                assert step.get("shell") == "bash", f"step {step.get('name')} 缺少 shell: bash"


class TestCompositeContextGuard:
    """composite action 内 vars/secrets context 不可用（branch-cleanup 事故先例）。

    模板校验（Unrecognized named-value）只有 actionlint 能查 workflow 层的
    引用，composite 内部引用要到运行时才爆——这里静态锁定零出现。
    """

    def test_no_vars_context(self):
        raw = ACTION_YML.read_text()
        assert not re.search(r"\$\{\{\s*vars\.", raw), "composite 内禁止 vars. context"

    def test_no_secrets_context(self):
        raw = ACTION_YML.read_text()
        assert not re.search(r"\$\{\{\s*secrets\.", raw), (
            "composite 内禁止 secrets. context——token 必须经 input 传入"
        )

    def test_token_flows_from_input_to_env(self, action_data):
        publish_step = next(
            (s for s in action_data["runs"]["steps"] if s.get("name") == "Publish findings"),
            None,
        )
        assert publish_step is not None
        assert publish_step["env"]["GH_TOKEN"] == "${{ inputs.github-token }}"


class TestArtifactAndScriptPaths:
    def test_download_pattern_keeps_debug_prefix(self, action_data):
        download_step = next(
            (
                s
                for s in action_data["runs"]["steps"]
                if s.get("uses", "").startswith("actions/download-artifact")
            ),
            None,
        )
        assert download_step is not None, "缺少 findings artifact 下载步骤"
        pattern = download_step["with"]["pattern"]
        assert pattern.startswith("droid-review-debug-"), f"pattern 前缀漂移：{pattern}"
        assert "-shard-*" in pattern

    def test_publish_script_resolves_within_action_dir(self, action_data):
        """run 块引用脚本必须 $GITHUB_ACTION_PATH/<script>（禁止 ../ 越出）"""
        publish_step = next(
            (s for s in action_data["runs"]["steps"] if s.get("name") == "Publish findings"),
            None,
        )
        assert "$GITHUB_ACTION_PATH/publish_findings.py" in publish_step["run"]
        for step in action_data["runs"]["steps"]:
            if "run" in step:
                assert "../" not in step["run"], f"step {step.get('name')} run 块包含路径穿越"

    def test_publish_script_exists_in_action_dir(self):
        assert (ACTION_DIR / "publish_findings.py").exists()

    def test_publish_args_unchanged(self, action_data):
        """--pattern/--pr-number/--repository/--commit-id 接口与引擎版一致"""
        publish_step = next(
            (s for s in action_data["runs"]["steps"] if s.get("name") == "Publish findings"),
            None,
        )
        run_block = publish_step["run"]
        for arg in ("--pattern", "--pr-number", "--repository", "--commit-id"):
            assert arg in run_block


class TestBundledPublishCopy:
    """action 内嵌 publish_findings.py 与引擎权威副本字节一致（drift 防护）"""

    def test_copy_matches_engine_copy(self):
        assert ENGINE_PUBLISH.exists(), "引擎权威副本缺失"
        bundled = (ACTION_DIR / "publish_findings.py").read_bytes()
        engine = ENGINE_PUBLISH.read_bytes()
        assert bundled == engine, (
            "actions/droid-review-aggregate/publish_findings.py 与 "
            "src/infra_core/engine/droid_review/publish_findings.py 漂移——"
            "action 自包含分发要求字节一致，改动必须双侧同步并经 PR 评审"
        )

    def test_copy_git_mode_matches_engine(self):
        import subprocess

        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--stage",
                str(ACTION_DIR / "publish_findings.py"),
                str(ENGINE_PUBLISH),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        modes = [line.split()[1] for line in result.stdout.splitlines() if line.strip()]
        assert len(modes) == 2, f"git index 应含两份副本，实际: {result.stdout!r}"
        assert modes[0] == modes[1], f"git 文件模式漂移：{modes}"


class TestDuplicateSuppressionContract:
    """字节一致副本的 CODE_HYGIENE_DUPLICATE_BLOCK 抑制契约（INFRA-681）。

    引擎权威副本与 action 自包含分发副本字节一致（TestBundledPublishCopy 锁定），
    hygiene 审计对每个同名函数产出一条 duplicate finding——这是设计性重复的
    固有误报，经 .evolution/suppress.json 精确抑制（INFRA-659 先例）。

    本契约双向锁定：
    - 正向：该文件对实际产出的全部 duplicate finding（两种遍历顺序各一形态，
      location 经 sanitize_structured_field 归一化）都被 suppress.json 覆盖；
    - 反向：suppress.json 中该文件对的抑制条目与实际发现一一对应，
      副本消亡（如未来恢复单源）后残留条目会被测试逼出清理。
    行号漂移（双侧同步改副本）时哈希形态变化，测试自动要求同步更新抑制条目。
    """

    RULE_ID = "CODE_HYGIENE_DUPLICATE_BLOCK"

    @staticmethod
    def _sanitize(text: str) -> str:
        from infra_core.engine.evolution_adapters import sanitize_structured_field

        return sanitize_structured_field(text)

    def _duplicate_locations(self) -> set[str]:
        """对该文件对跑 hygiene 重复检测，返回归一化 location 全集。

        location 的 pair 顺序（哪个文件在前）取决于 os.walk 遍历顺序，
        本地 macOS 与 CI Linux 文件系统顺序不同（INFRA-681 实证：issue
        为 S-first，本地运行为 A-first）。对正反两种 funcs 顺序各跑一次，
        覆盖双形态——抑制条目必须同时登记两种顺序。
        """
        from infra_core.packs.memory.hygiene import (
            check_duplicates,
            extract_functions_for_duplicate_check,
        )

        funcs = []
        for path in (ACTION_DIR / "publish_findings.py", ENGINE_PUBLISH):
            funcs.extend(extract_functions_for_duplicate_check(path, REPO_ROOT))

        locations: set[str] = set()
        for ordered in (funcs, funcs[::-1]):
            for f in check_duplicates(ordered):
                if f["rule_id"] == self.RULE_ID:
                    locations.add(self._sanitize(f["location"]))
        return locations

    def _suppressed_locations(self) -> set[str]:
        suppress = json.loads((REPO_ROOT / ".evolution" / "suppress.json").read_text())
        return {
            e["location"]
            for e in suppress["suppressed"]
            if e.get("rule_id") == self.RULE_ID
            and (
                "publish_findings" in e["location"]
                or "droid-review-aggre" in e["location"]
                or "droid_rev" in e["location"]
            )
        }

    def test_all_duplicate_findings_suppressed(self):
        findings = self._duplicate_locations()
        assert findings, "字节一致副本（TestBundledPublishCopy）必然产出 duplicate findings"
        unsuppressed = findings - self._suppressed_locations()
        assert not unsuppressed, (
            f"duplicate finding 未在 suppress.json 登记（INFRA-681 契约）：{unsuppressed}——"
            "复制 sanitize 后的 location 作为新条目加入 .evolution/suppress.json"
        )

    def test_no_stale_suppression_entries(self):
        stale = self._suppressed_locations() - self._duplicate_locations()
        assert not stale, (
            f"suppress.json 含该文件对的失效抑制条目（finding 已不存在）：{stale}——"
            "副本消亡或行号漂移后必须同步清理/更新抑制条目"
        )


class TestFailClosedSemantics:
    def test_shard_pipeline_failure_blocks(self, action_data):
        """check_results 步骤：shards-result 非 success/skipped → fail-closed"""
        check_step = next(
            (s for s in action_data["runs"]["steps"] if s.get("id") == "check_results"),
            None,
        )
        assert check_step is not None
        run_block = check_step["run"]
        assert '!= "success"' in run_block or "!= 'success'" in run_block
        assert "::error::" in run_block
        assert "exit 1" in run_block

    def test_docs_only_still_publishes_success_check(self, action_data):
        """docs-only → should_publish=false（跳过发布但 job success，VAL-DRSKIP-005）"""
        check_step = next(
            (s for s in action_data["runs"]["steps"] if s.get("id") == "check_results"),
            None,
        )
        assert 'echo "should_publish=false" >> "$GITHUB_OUTPUT"' in check_step["run"]
