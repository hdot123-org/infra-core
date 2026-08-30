"""消费接入指南契约测试：指南内的 config.yml 示例必须覆盖全部 REQUIRED_CONFIG_KEYS.

VAL-CROSS-008(d) 的回归防线：指南示例若缺引擎必填键（如
max_self_audit_issues_per_tick），消费者按指南 verbatim 建仓后首次
report-only 试扫即报 Missing required config keys——本测试在 CI 拦截。
"""

import re
import sys
from pathlib import Path

import yaml

# 引擎模块间为裸名导入（transplanted 代码），复用各测试文件的 sys.path 引导
_engine_dir = Path(__file__).resolve().parent.parent / "src" / "infra_core" / "engine"
sys.path.insert(0, str(_engine_dir))

from evolution_utils import REQUIRED_CONFIG_KEYS

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "onboarding" / "consumer-onboarding.md"


def _guide_config_example() -> dict:
    """提取指南 §3 的 config.yml yaml 代码块（以 rule_packs 注释行定位主块）."""
    text = GUIDE.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert blocks, "指南中不存在 yaml 代码块"
    # 主 config 块 = 含 dedup_label 的那个（其余 yaml 块为依赖声明等片段）
    for block in blocks:
        if "dedup_label" in block:
            return yaml.safe_load(block)
    raise AssertionError("指南中找不到含 dedup_label 的 config.yml 示例块")


def test_guide_config_example_covers_all_required_keys():
    """指南 config 示例必须包含引擎 REQUIRED_CONFIG_KEYS 全部键."""
    example = _guide_config_example()
    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in example]
    assert not missing, f"指南 config 示例缺少必填键: {missing}"


def test_guide_config_example_declares_memory_rule_pack():
    """指南 config 示例必须声明 rule_packs: [pack: memory]（VAL-CROSS-008(c) 面）."""
    example = _guide_config_example()
    packs = example.get("rule_packs")
    assert isinstance(packs, list) and len(packs) >= 1
    assert any(p.get("pack") == "memory" for p in packs)
