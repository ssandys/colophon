"""Executable coverage for Service.qml, the singleton behind every bar surface.

Everything else in this repo tests Python or plain JavaScript. Service.qml is
neither: it is QML driving Quickshell's Process, and `qmllint` only proves the
file parses. So a regression in it is invisible to the whole suite -- which is
how every user setting stopped reaching the service when it became a singleton
(#19), and why this file exists.

These run the real Service.qml under the real Quickshell with a harness that
reads properties afterwards and reports through the exit code (Qt logging is
suppressed in this environment). The pattern is galley's
tests/test_controller_lifecycle.py.

PATH is emptied, so python3, ollama and notify-send all fail to spawn: nothing
reaches the user's ollama, nothing is collected, no notification is raised. A
failed spawn is a path Service.qml already handles. quickshell itself is
invoked by absolute path so the empty PATH does not hide the runtime too.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))

HARNESS = """
import QtQuick
import Quickshell
import "."

ShellRoot {
  Component.onCompleted: {
    %(script)s
  }

  Timer {
    running: true; interval: %(wait)d
    onTriggered: Qt.exit((%(check)s) ? 0 : 1)
  }
}
"""


def quickshell_missing():
    return shutil.which("quickshell") is None


@unittest.skipIf(quickshell_missing(), "quickshell is required to run Service.qml")
class SettingsDeliveryTest(unittest.TestCase):
    """Settings reaching the singleton at all (#19).

    The widget called Service.attach({settings}) from Component.onCompleted,
    and attach() latched the first object it saw. The bar sets a widget's
    settings from its Loader's onLoaded, AFTER the item completes, so what got
    latched was Ui/Panel.qml's empty default -- every setting fell back to its
    hardcoded value for good, notification toggles included.
    """

    def _run(self, script, check, wait=1500):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Service.qml", "Model.js", "qmldir"):
                shutil.copy(os.path.join(ROOT, name), os.path.join(tmp, name))
            harness = os.path.join(tmp, "harness.qml")
            with open(harness, "w") as handle:
                handle.write(HARNESS % {"script": script, "check": check,
                                        "wait": wait})
            empty_bin = os.path.join(tmp, "empty-bin")
            os.mkdir(empty_bin)
            env = dict(os.environ)
            env["PATH"] = empty_bin
            return subprocess.run([shutil.which("quickshell"), "-p", harness],
                                  capture_output=True, text=True,
                                  timeout=30, env=env)

    def test_with_no_settings_the_service_uses_its_defaults(self):
        # The control. Every assertion below is about a value DIFFERENT from
        # these, and it proves the harness really executes Service.qml.
        proc = self._run(
            "Service.attach({})",
            "Service.idleInterval === 30"
            " && Service.apiBase === 'http://127.0.0.1:11434'"
            " && Service.notifyServiceDied === true")
        self.assertEqual(proc.returncode, 0,
                         "defaults did not hold\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_settings_that_arrive_after_attach_still_take_effect(self):
        # Exactly the order the host produces: attach holding the empty
        # default, then the real settings.
        proc = self._run(
            "Service.attach({ settings: ({}) });"
            " Service.configure({ pollIntervalIdleSec: 45,"
            " apiBase: 'http://127.0.0.1:9', notifyServiceDied: false })",
            "Service.idleInterval === 45"
            " && Service.apiBase === 'http://127.0.0.1:9'"
            " && Service.notifyServiceDied === false")
        self.assertEqual(proc.returncode, 0,
                         "late settings were ignored\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_a_later_settings_change_replaces_the_earlier_one(self):
        # The settings UI assigns a new object on every edit; the latest wins.
        proc = self._run(
            "Service.attach({});"
            " Service.configure({ pollIntervalIdleSec: 45 });"
            " Service.configure({ pollIntervalIdleSec: 120 })",
            "Service.idleInterval === 120")
        self.assertEqual(proc.returncode, 0,
                         "the first settings object stuck\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_a_second_surface_attaching_does_not_clobber_settings(self):
        # Every surface attaches with whatever its widget held at completion,
        # which is the empty default. Settings must come from configure().
        proc = self._run(
            "Service.attach({});"
            " Service.configure({ pollIntervalIdleSec: 45 });"
            " Service.attach({ settings: ({}) })",
            "Service.idleInterval === 45 && Service.consumers === 2")
        self.assertEqual(proc.returncode, 0,
                         "a later attach wiped the settings\n%s%s"
                         % (proc.stdout, proc.stderr))


if __name__ == "__main__":
    unittest.main()
