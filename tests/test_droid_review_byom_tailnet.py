"""droid-review BYOM tailnet 路由回归测试（2026-08-29 PR #47 / INFRA-603）。

回归保护：BYOM LLM 调用的 baseUrl 必须走 ts 内网直达 Kong
（node1.tail5e888.ts.net，tailscale serve 入口，tailnet only + LE 证书）。

背景（PR #47 实证）：原 https://ai.exa.edu.kg/v1 链路为
ce-01 runner → 公网/CF → node-22(东京) → ts 隧道 → node-01 Kong(杭州) → Bailian，
4 段网络、2 次公网进出，地理上绕两国三地访问国内服务（Bailian）。切换后：
- LLM 调用延迟显著降低（去掉 CF + 东京两跳）
- 公网 LLM 端点对 CI 的暴露面归零（爆破面消失）

本测试钉住该选择，防止回退到公网端点（INFRA-603 补 Droid 流程执行记录）。
"""

import json

import pytest
import yaml

pytestmark = pytest.mark.integration

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# BYOM 路由契约覆盖两个载体：自仓 droid-review.yml + reusable workflow
# droid-review-shards.yml（M4 起 memory-core 等 thin caller 的分片流水线走后者）
WORKFLOW_PATHS = [
    REPO_ROOT / ".github/workflows/droid-review.yml",
    REPO_ROOT / ".github/workflows/droid-review-shards.yml",
]

# 向后兼容别名（旧引用点）
WORKFLOW_PATH = WORKFLOW_PATHS[0]

BYOM_STEP_NAME = "Write BYOM settings file"
HEREDOC_DELIMITER = "SETTINGS_EOF"


def _get_byom_step(workflow_path: Path) -> dict:
    """定位 review-shard job 中写 BYOM settings 的 step。"""
    data = yaml.safe_load(workflow_path.read_text())
    shard_job = data["jobs"]["review-shard"]
    for step in shard_job.get("steps", []):
        if step.get("name") == BYOM_STEP_NAME:
            return step
    pytest.fail(f"{workflow_path.name}: review-shard job must have a {BYOM_STEP_NAME!r} step")


def _get_step_comment_block(workflow_path: Path, step_name: str) -> str:
    """提取 step 的 YAML comment 块（# 开头行）。

    yaml.safe_load 会丢弃 comment；前置依赖（/etc/hosts 条目）文档化在
    step 的 name: 行之后、run: 之前的缩进 comment 块中，回读原文按行提取。
    """
    raw = workflow_path.read_text().splitlines()
    step_lines = [i for i, line in enumerate(raw) if f"name: {step_name}" in line]
    assert step_lines, f"{workflow_path.name}: step {step_name!r} not found in workflow source"
    comments: list[str] = []
    for line in raw[step_lines[0] + 1 :]:
        if line.strip().startswith("#"):
            comments.append(line)
        elif line.strip() == "" or "run:" not in line:
            continue
        else:
            break
    return "\n".join(comments)


def _extract_settings_block(workflow_path: Path) -> str:
    """从 run: 块提取 heredoc 内嵌的 settings JSON 原文。"""
    run_script = _get_byom_step(workflow_path)["run"]
    lines = run_script.splitlines()
    start = end = None
    for idx, line in enumerate(lines):
        if f"<< '{HEREDOC_DELIMITER}'" in line or f"<< '{HEREDOC_DELIMITER}'" in line:
            start = idx + 1
        elif line.strip() == HEREDOC_DELIMITER and start is not None:
            end = idx
            break
    assert start is not None, f"heredoc << '{HEREDOC_DELIMITER}' not found in BYOM step"
    assert end is not None, f"heredoc terminator {HEREDOC_DELIMITER} not found"
    return "\n".join(lines[start:end])


def _load_settings(workflow_path: Path) -> dict:
    """解析内嵌 settings JSON（缩进对 json.loads 无害，整体即合法性校验）。"""
    return json.loads(_extract_settings_block(workflow_path))


@pytest.fixture(params=WORKFLOW_PATHS, ids=[p.name for p in WORKFLOW_PATHS])
def wf_path(request) -> Path:
    return request.param


class TestByomTailnetRouting:
    """BYOM baseUrl 必须走 ts 内网直达 Kong，禁止回退公网端点。

    覆盖两个载体：自仓 droid-review.yml 与 reusable droid-review-shards.yml。
    """

    def test_baseurl_points_to_tailnet_kong(self, wf_path):
        """baseUrl 必须是 node1.tail5e888.ts.net（ts 内网直达，tailnet only）。"""
        settings = _load_settings(wf_path)
        model = settings["customModels"][0]
        assert model["baseUrl"] == "https://node1.tail5e888.ts.net/v1", (
            "BYOM baseUrl 必须走 ts 内网直达 Kong（PR #47 / INFRA-603）："
            "公网端点会把 LLM 流量绕 CF → 东京 → 隧道回杭州，且暴露爆破面"
        )

    def test_public_endpoint_absent_from_active_config(self, wf_path):
        """活跃配置（heredoc JSON 块）不得出现旧公网端点。

        注释中允许提及旧端点作为历史说明（解释切换原因），但 JSON 块是
        实际写入 runner ~/.factory/settings.json 的内容，必须零公网引用。
        """
        block = _extract_settings_block(wf_path)
        assert "ai.exa.edu.kg" not in block, (
            "活跃 BYOM 配置不得引用公网端点 ai.exa.edu.kg（INFRA-603 暴露面归零要求）"
        )

    def test_settings_block_is_valid_json(self, wf_path):
        """内嵌 settings 块必须是合法 JSON（workflow 只做写入后校验，这里前置拦截）。"""
        settings = _load_settings(wf_path)
        assert isinstance(settings, dict)
        assert len(settings["customModels"]) == 1

    def test_heredoc_delimiter_quoted(self, wf_path):
        """heredoc 定界符必须单引号（变量不展开）。

        apiKey 是 provider 格式占位（内网 Kong 无认证，request-transformer
        注入真实上游 key）；若定界符失去引号，${NVIDIA_KONG_PROXY_KEY} 会从
        runner env 展开成真实 secret 写入 settings 文件——无意义且扩大
        secret 落盘面。
        """
        run_script = _get_byom_step(wf_path)["run"]
        assert f"<< '{HEREDOC_DELIMITER}'" in run_script, (
            "BYOM settings heredoc 必须使用单引号定界符（禁止变量展开）"
        )

    def test_hosts_prerequisite_documented(self, wf_path):
        """运维前置依赖必须在 step 注释中文档化：runner /etc/hosts 静态条目。

        runner 的 tailscale accept-dns=false，MagicDNS 不可用，解析依赖
        /etc/hosts 的 100.100.1.9 node1.tail5e888.ts.net 静态条目。
        注释丢失会导致新 runner 部署时 DNS 解析失败且无从排查。
        """
        run_script = _get_byom_step(wf_path)["run"]
        # /etc/hosts 前置依赖文档化在 step 的 name: 与 run: 之间的 comment 块，
        # 也可能出现在 run: 内 —— 两者合并检查。
        comments = _get_step_comment_block(wf_path, BYOM_STEP_NAME)
        combined = comments + "\n" + run_script
        assert "/etc/hosts" in combined, (
            "BYOM step 必须文档化 /etc/hosts 前置依赖（MagicDNS 不可用的 runner 解析方案）"
        )
