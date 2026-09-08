"""Droid autofix demo fixture tests (correct expectations).

These assertions describe the intended behavior of count_enabled.
The implementation in src/infra_core/autofix_demo.py contains an
intentional bug; the fix must land in the implementation, not here.
"""

from infra_core.autofix_demo import count_enabled


def test_count_enabled_counts_true_flags():
    assert count_enabled([True, False, True]) == 2


def test_count_enabled_empty():
    assert count_enabled([]) == 0


def test_count_enabled_all_true():
    assert count_enabled([True, True]) == 2


def test_count_enabled_all_false():
    assert count_enabled([False, False]) == 0
