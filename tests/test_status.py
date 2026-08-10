import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import colophon_collect as collect

# (activeState, subState, apiReachable, loadState, hasBinary, expected)
CASES = [
    ("active", "running", True, "loaded", True, "running"),
    ("active", "running", False, "loaded", True, "starting"),
    ("reloading", "running", True, "loaded", True, "running"),
    ("reloading", "running", False, "loaded", True, "starting"),
    ("activating", "start", False, "loaded", True, "starting"),
    ("activating", "start", True, "loaded", True, "starting"),
    ("deactivating", "stop", True, "loaded", True, "stopping"),
    ("deactivating", "stop", False, "loaded", True, "stopping"),
    ("inactive", "dead", True, "loaded", True, "foreign"),
    ("failed", "failed", True, "loaded", True, "foreign"),
    ("inactive", "dead", False, "loaded", True, "stopped"),
    ("failed", "failed", False, "loaded", True, "failed"),
    ("inactive", "dead", False, "not-found", True, "missing"),
    ("inactive", "dead", True, "not-found", True, "missing"),
    ("inactive", "dead", False, "loaded", False, "missing"),
    ("inactive", "dead", True, "loaded", False, "missing"),
]


class ResolveStatusTest(unittest.TestCase):
    def test_table(self):
        for active, sub, reachable, load, has_binary, expected in CASES:
            unit = {"activeState": active, "subState": sub, "loadState": load}
            with self.subTest(active=active, reachable=reachable, load=load,
                              has_binary=has_binary):
                self.assertEqual(
                    collect.resolve_status(unit, reachable, has_binary),
                    expected)

    def test_missing_wins_over_a_live_api(self):
        # A container bound to :11434 with no systemd unit reports `missing`,
        # not `foreign`. Deliberate: without a unit there is nothing to
        # control, so the widget says so rather than offering dead buttons.
        unit = {"activeState": "inactive", "subState": "dead",
                "loadState": "not-found"}
        self.assertEqual(collect.resolve_status(unit, True, True), "missing")

    def test_every_case_returns_a_declared_status(self):
        for active, sub, reachable, load, has_binary, _ in CASES:
            unit = {"activeState": active, "subState": sub, "loadState": load}
            self.assertIn(
                collect.resolve_status(unit, reachable, has_binary),
                collect.STATUSES)

    def test_unknown_active_state_degrades_to_stopped(self):
        unit = {"activeState": "banana", "subState": "?", "loadState": "loaded"}
        self.assertEqual(collect.resolve_status(unit, False, True), "stopped")

    def test_empty_unit_is_missing_without_a_binary(self):
        self.assertEqual(collect.resolve_status({}, False, False), "missing")
