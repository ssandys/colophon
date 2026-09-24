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
import re
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
  id: root
  property int idleMs: -1
  property int runningMs: -1

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

    def test_clearing_a_setting_puts_its_default_back(self):
        # configure() REPLACES the settings object; it does not merge into
        # it. A merge would keep a cleared key's old value forever -- the
        # settings UI drops a key back to the manifest default by leaving it
        # out.
        proc = self._run(
            "Service.attach({});"
            " Service.configure({ pollIntervalIdleSec: 45,"
            " notifyServiceDied: false });"
            " Service.configure({})",
            "Service.idleInterval === 30 && Service.notifyServiceDied === true")
        self.assertEqual(proc.returncode, 0,
                         "a cleared setting kept its old value\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_settings_naming_only_some_keys_leave_the_rest_at_defaults(self):
        proc = self._run(
            "Service.attach({}); Service.configure({ keepAliveMinutes: 9 })",
            "Service.keepAliveMinutes === 9 && Service.idleInterval === 30"
            " && Service.runningInterval === 10"
            " && Service.apiBase === 'http://127.0.0.1:11434'")
        self.assertEqual(proc.returncode, 0,
                         "an unnamed key lost its default\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_configure_with_nothing_falls_back_to_defaults(self):
        proc = self._run(
            "Service.attach({});"
            " Service.configure({ pollIntervalIdleSec: 45 });"
            " Service.configure(null);"
            " Service.configure({ pollIntervalIdleSec: 46 });"
            " Service.configure(undefined)",
            "Service.idleInterval === 30")
        self.assertEqual(proc.returncode, 0,
                         "configure(null/undefined) misbehaved\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_the_poll_timer_runs_on_the_configured_intervals(self):
        # pollIntervalMs aliases pollTimer.interval itself, so this is the
        # schedule the timer is really on. With PATH empty the collector
        # cannot run and the service starts stopped, so the idle interval
        # applies first. Nothing here can make ollama run, so `status` is set
        # directly and read back in the same tick, before a failed collection
        # could change it; the open panel then overrides both.
        proc = self._run(
            "Service.attach({});"
            " Service.configure({ pollIntervalIdleSec: 45,"
            " pollIntervalRunningSec: 25, pollIntervalOpenSec: 7 });"
            " root.idleMs = Service.pollIntervalMs;"
            " Service.status = 'running';"
            " root.runningMs = Service.pollIntervalMs;"
            " Service.setPanelOpen(false, true)",
            "root.idleMs === 45000 && root.runningMs === 25000"
            " && Service.pollIntervalMs === 7000")
        self.assertEqual(proc.returncode, 0,
                         "the timer did not follow the settings\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_with_no_settings_the_poll_timer_runs_on_the_default(self):
        proc = self._run("Service.attach({})",
                         "Service.pollIntervalMs === 30000")
        self.assertEqual(proc.returncode, 0,
                         "the default schedule is wrong\n%s%s"
                         % (proc.stdout, proc.stderr))


def read(name):
    with open(os.path.join(ROOT, name)) as handle:
        return handle.read()


def strip_comments(source):
    # Line comments only, and only where `//` starts the line or follows
    # whitespace: a URL's `//` follows a colon, so "http://..." survives. The
    # comments around this wiring NAME everything checked below, and a match
    # found only in prose must not satisfy -- or fail -- a guard.
    return re.sub(r"(^|\s)//.*", r"\1", source, flags=re.M)


class WidgetWiringTest(unittest.TestCase):
    """The widget's half of #19, which SettingsDeliveryTest cannot see.

    Those tests call Service.configure() themselves, so they pass whether or
    not Panel.qml ever does -- and the whole suite passed with this fix's
    Service.qml before Panel.qml had its onSettingsChanged. Loading Panel.qml
    for real needs the bar's own Ui components, so these read the source
    instead: crude, but they fail on exactly the edits that bring #19 back.
    Static, so unlike the tests above they run without quickshell.
    """

    def setUp(self):
        self.panel = strip_comments(read("Panel.qml"))
        self.service = strip_comments(read("Service.qml"))

    def test_the_widget_hands_over_every_settings_change(self):
        self.assertRegex(
            self.panel,
            r"onSettingsChanged:\s*Service\.configure\(\s*root\.settings\s*\)",
            "Panel.qml must forward settings from onSettingsChanged: the bar "
            "injects them after Component.onCompleted, so attach() is too early")

    def test_the_widget_does_not_hand_settings_to_attach(self):
        start = self.panel.index("Service.attach(")
        call = self.panel[start:self.panel.index("})", start) + 2]
        self.assertNotIn("settings", call,
                         "attach() runs before the bar injects settings; "
                         "whatever it is handed there is the empty default")

    def test_attach_does_not_take_settings(self):
        start = self.service.index("function attach(options) {")
        body = self.service[start:self.service.index("\n  }\n", start)]
        self.assertNotIn("settings", body,
                         "attach() must not latch settings: the first surface "
                         "attaches holding the empty default (#19)")


if __name__ == "__main__":
    unittest.main()
