"""engine 包 lazy init 契约（M4）。

消费仓（memory-core）scripts/ 与本引擎存在同名裸名模块（evolution_utils 等）。
engine.__init__ 若强制 import evolution_scanner，消费仓进程中已污染的裸名
sys.modules 会让 version_sync 集成调用在 import 期崩掉（INFRA 无号，
memory-core 全量 xdist 实测）。lazy export 必须保持：
  1. import 子模块（infra_core.engine.version_sync）不拉起 scanner 链
  2. 旧包级导出名（Finding 等）经 __getattr__ 仍可用
"""

import subprocess
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_submodule_import_does_not_pull_scanner_chain(monkeypatch):
    """version_sync 子模块 import 不触发 evolution_scanner（消费仓碰撞面根因）。"""

    # 模拟消费仓污染：裸名 evolution_utils 已被占用且缺引擎侧 API（INFRA-601）
    poisoned = ModuleType("evolution_utils")
    assert not hasattr(poisoned, "gh_repo_args")
    monkeypatch.setitem(sys.modules, "evolution_utils", poisoned)

    scanner_before = sys.modules.get("evolution_scanner")
    import infra_core.engine.version_sync as vs  # noqa: F401  (import 即断言)

    # scanner 裸名未被 engine.__init__ 拉起（除非测试进程先前已装入）
    assert sys.modules.get("evolution_scanner") is scanner_before
    assert hasattr(vs, "sync_single_project"), "version_sync 公开 API 必须可用"


def test_package_lazy_attrs_still_exported():
    """旧包级导出名（Finding / sync_single_project 等）经 __getattr__ 保持。"""
    import infra_core.engine as engine_pkg

    for name in ("Finding", "load_config", "normalize_finding", "run_audit_tool"):
        assert hasattr(engine_pkg, name), f"engine 包级导出 {name} 不得丢失"
    for name in ("sync_single_project", "probe_version_and_sync", "set_resign_hook"):
        assert hasattr(engine_pkg, name), f"engine 包级导出 {name} 不得丢失"


def test_unknown_attr_raises_attribute_error():
    import infra_core.engine as engine_pkg

    try:
        engine_pkg.definitely_not_an_attr  # noqa: B018
    except AttributeError as e:
        assert "definitely_not_an_attr" in str(e)
    else:
        raise AssertionError("未知属性必须 AttributeError")


def test_fresh_interpreter_can_import_version_sync():
    """干净解释器（无 pytest conftest 干扰）直接 import version_sync 成功。"""
    result = subprocess.run(
        [sys.executable, "-c", "import infra_core.engine.version_sync as vs; print(vs.__name__)"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "infra_core.engine.version_sync" in result.stdout
