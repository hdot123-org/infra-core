import pytest


@pytest.fixture(autouse=True)
def _reset_tick_tracker():
    """Reset evolution_utils global tick tracker before each test.

    infra_core.engine.evolution_utils maintains a module-level _tick_tracker
    instance (TickBudgetTracker) that tracks API calls and duration across
    the session. Without resetting between tests, one test's accumulated
    calls can exhaust the budget (API_CALL_BUDGET=100), causing subsequent
    drift-watch tests to be silently skipped — leading to flaky CI failures
    depending on test order.

    This fixture ensures every test starts with a clean tracker state,
    covering all test files that import from evolution_utils (not just
    test_drift_watch_reverse_integration.py which had its own per-file fixture).

    Transplanted from memory-core conftest.py during the engine transplant;
    the sys.path bootstrap now points at src/infra_core/engine/ where
    evolution_utils.py lives in this repo.
    """
    import importlib
    import sys
    from pathlib import Path

    # src/infra_core/engine/ is not on sys.path by default; tests add it
    # manually. Mirror the same pattern so we can import evolution_utils here.
    _engine_dir = str(Path(__file__).resolve().parent.parent / "src" / "infra_core" / "engine")
    if _engine_dir not in sys.path:
        sys.path.insert(0, _engine_dir)

    _eu = importlib.import_module("evolution_utils")
    _eu._tick_tracker.start_time = None
    _eu._tick_tracker.api_calls = 0
    yield
