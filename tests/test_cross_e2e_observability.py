"""VAL-CROSS-006/007 evidence-surface tests: auto_close_resolved 与 tick 摘要的日志可审计性.

VAL-CROSS-006 要求 scheduled tick 日志 grep `auto_close_resolved` 命中 >0；
VAL-CROSS-007 要求从同源日志提取 rule_id 域。此前 auto_close_resolved 仅在
closed>0 时输出，rule_id 域完全不落日志——本文件锁定两条恒定证据线。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Engine modules (transplanted from memory-core scripts/) live in src/infra_core/engine
_engine_dir = Path(__file__).resolve().parent.parent / "src" / "infra_core" / "engine"
sys.path.insert(0, str(_engine_dir))

from evolution_scanner import Finding, _rule_id_domain_line
from evolution_utils import auto_close_resolved

pytestmark = pytest.mark.e2e


def test_auto_close_resolved_always_logs_identifier_zero_closed(capsys):
    """零关闭（全部 issue 仍命中当前 findings）也必须输出 auto_close_resolved 摘要行."""
    findings = [Finding("RULE_001", "warning", "test", "d", "f1.py", "e")]
    mock_issues = [
        {"number": 101, "body": "**Rule ID**: RULE_001\n**Location**: f1.py"},
    ]
    with patch("evolution_utils.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_issues), stderr="")
        auto_close_resolved(findings, "evolution-found")
    out = capsys.readouterr().out
    assert "auto_close_resolved" in out
    assert "examined=1" in out
    assert "closed=0" in out


def test_auto_close_resolved_logs_identifier_on_close(capsys):
    """有关闭行为时摘要行同样输出（含 closed 计数）."""
    findings = [Finding("RULE_001", "warning", "test", "d", "f1.py", "e")]
    mock_issues = [
        {"number": 101, "body": "**Rule ID**: RULE_001\n**Location**: f1.py"},
        {"number": 102, "body": "**Rule ID**: RULE_002\n**Location**: f2.py"},
    ]
    with patch("evolution_utils.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps(mock_issues), stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),  # comment fetch for #102
            MagicMock(returncode=0, stdout="", stderr=""),  # close issue 102
        ]
        auto_close_resolved(findings, "evolution-found")
    out = capsys.readouterr().out
    assert "auto_close_resolved" in out
    assert "closed=1" in out


def test_auto_close_resolved_logs_skip_on_fetch_failure(capsys):
    """gh 拉取失败（issues=None）路径输出 auto_close_resolved skip 行."""
    with patch("evolution_utils._fetch_open_issues", return_value=None):
        auto_close_resolved([], "evolution-found")
    out = capsys.readouterr().out
    assert "auto_close_resolved: skipped (failed to fetch open issues)" in out


def test_auto_close_resolved_logs_skip_on_partial_output_protection(capsys, tmp_path):
    """P0-A 部分输出保护路径输出 auto_close_resolved skip 行."""
    history = tmp_path / "findings_over_time.json"
    with patch("evolution_utils._should_skip_partial_output", return_value=True):
        auto_close_resolved([], "evolution-found", history_path=history)
    out = capsys.readouterr().out
    assert "auto_close_resolved: skipped (P0-A partial-output protection)" in out


def test_rule_id_domain_line_sorted_unique():
    """域行输出排序去重的 rule_id 集合与计数."""
    findings = [
        Finding("RULE_B", "warning", "test", "d", "f1.py", "e"),
        Finding("RULE_A", "info", "test", "d", "f2.py", "e"),
        Finding("RULE_A", "info", "test", "d2", "f3.py", "e"),
    ]
    line = _rule_id_domain_line(findings)
    assert line == "[evolution] Findings rule_id domain (2): RULE_A, RULE_B"


def test_rule_id_domain_line_empty():
    """空 findings 输出零规则域行（tick 空转也留证据）."""
    assert _rule_id_domain_line([]) == "[evolution] Findings rule_id domain (0): "
