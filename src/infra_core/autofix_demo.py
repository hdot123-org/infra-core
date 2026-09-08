"""Droid autofix demo fixture: intentional real bug.

This module exists to feed the droid-autofix closed loop a real failing
scenario on CI. The unit test (tests/test_autofix_demo.py) encodes the
CORRECT behavior; the implementation below carries an intentional
single-token bug.

Fix policy: repair the implementation. Do NOT modify the test.
"""


def count_enabled(flags: list[bool]) -> int:
    """Return the number of enabled (True) flags."""
    total = 0
    for flag in flags:
        if not flag:
            total += 1
    return total
