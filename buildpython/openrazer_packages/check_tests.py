"""Run the pinned focused suite with compiler preflight and no silent skips."""

from __future__ import annotations

import shutil
import sys
import unittest

TEST_MODULES = (
    "daemon.tests.test_daemon_hotplug",
    "daemon.tests.test_mouse_monitor",
    "daemon.tests.test_keyboard_probe",
    "daemon.tests.test_mouse_activity",
    "daemon.tests.test_mouse_scroll_wheel",
    "pylib.tests.test_mouse_scroll_mode",
)
EXPECTED_TESTS = 55


def main() -> int:
    for compiler in ("cc", "clang"):
        if shutil.which(compiler) is None:
            print(f"Required regression compiler missing: {compiler}", file=sys.stderr)
            return 1
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print(f"Required focused suite skipped tests: {result.skipped}", file=sys.stderr)
    if result.testsRun != EXPECTED_TESTS:
        print(f"Expected {EXPECTED_TESTS} tests, ran {result.testsRun}", file=sys.stderr)
    return int(
        not result.wasSuccessful() or bool(result.skipped) or result.testsRun != EXPECTED_TESTS
    )


if __name__ == "__main__":
    raise SystemExit(main())
