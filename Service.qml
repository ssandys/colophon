import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Non-visual: every mutable property, every Process, every Timer. Panel.qml
// binds to this and renders; it holds no state of its own.
//
// Split out from the start rather than retrofitted. galley#1 is this same file
// having grown to 777 lines with its state machine buried in the first 245,
// where it could not be read or reviewed without scrolling past layout.
// In-tree precedent: shell/plugins/panels/dropbox/Service.qml.
Item {
  id: root

  // Injected by Panel.qml. Ui/Panel.qml declares `settings`; this Item does
  // not, so the values must be passed in rather than read from here.
  property var settings: ({})
  property string collectPath: ""
  property string actionPath: ""
  property bool panelOpen: false

  // emptySnapshot(), not the EMPTY_SNAPSHOT constant: Model.js deliberately
  // hands out a deep clone so a caller cannot corrupt the shared default for
  // the process's lifetime, and there is a JS test guarding that.
  property var snapshot: Model.emptySnapshot()
  property int dataVersion: 0
  property bool loading: false
  property string status: "stopped"
  property string collectorError: ""

  property string actionInProgress: ""
  property string actionError: ""
  property bool actionExited: false
  property bool pendingRefresh: false

  // dropbox/Service.qml's `_desired` pattern: the UI reacts the instant you
  // click rather than one poll later. Empty means "just follow reality".
  property string optimisticStatus: ""
  readonly property string effectiveStatus:
    root.optimisticStatus !== "" ? root.optimisticStatus : root.status

  // Wall clock, ticked while the panel is open or a transition is in flight,
  // so uptime and the keep-alive countdown re-render without re-polling.
  property double nowSec: 0
  property double statusSinceSec: 0
  readonly property int secondsInStatus:
    Math.max(0, Math.floor(root.nowSec - root.statusSinceSec))

  // Set when the user asks for a stop or restart, so a running -> stopped
  // transition can be told apart from the service dying on its own.
  // Caller-owned on purpose: Model.js keeps no state between calls, which is
  // the lesson of galley trap #13.
  property bool expectedStop: false

  property string pendingNotification: ""

  // dataVersion as it stood when the action was issued. The settle ramp must
  // not conclude anything from a status that predates the action -- see the
  // comment in settleTimer.
  property int actionDataVersion: 0

  signal serviceDied(string reason)

  function setting(key, fallback) {
    var value = root.settings ? root.settings[key] : undefined
    return (value === undefined || value === null) ? fallback : value
  }

  readonly property int openInterval: setting("pollIntervalOpenSec", 2)
  readonly property int runningInterval: setting("pollIntervalRunningSec", 10)
  readonly property int idleInterval: setting("pollIntervalIdleSec", 30)
  readonly property int keepAliveMinutes: setting("keepAliveMinutes", 5)
  readonly property string apiBase: setting("apiBase", "http://127.0.0.1:11434")
  readonly property bool showInstalledModels: setting("showInstalledModels", true)
  readonly property bool notifyServiceDied: setting("notifyServiceDied", true)

  function refresh(fromTimer) {
    // A user-initiated refresh arriving mid-flight is coalesced rather than
    // dropped; the in-flight run re-triggers it on completion. A timer tick is
    // NOT coalesced: re-firing it immediately would decouple the cadence from
    // the configured interval whenever the collector runs slower than it.
    if (collectProc.running) {
      if (fromTimer !== true) root.pendingRefresh = true
      return
    }
    root.pendingRefresh = false
    root.loading = true
    collectProc.command = ["python3", root.collectPath,
                           "--api-base", root.apiBase]
    collectProc.running = true
  }

  function handleOutput(raw) {
    var next = Model.parseSnapshot(raw)
    root.loading = false
    root.collectorError = next.error || ""
    // A collector error must not destroy good content: only a clean parse
    // replaces the retained snapshot. A transient failure should not blank the
    // panel.
    if (root.collectorError !== "") return

    root.nowSec = Date.now() / 1000
    var previous = root.dataVersion > 0 ? root.status : ""
    if (next.status !== root.status || root.dataVersion === 0) {
      root.status = next.status
      root.statusSinceSec = root.nowSec
    }
    root.snapshot = next
    root.dataVersion++

    // Reality caught up to the click -- stop overriding it.
    if (root.optimisticStatus !== "" && root.status === root.optimisticStatus)
      root.optimisticStatus = ""

    // Suppressed on the first snapshot, so shell startup is silent.
    if (previous !== "") checkForDeath(previous, next)
  }

  function checkForDeath(previous, next) {
    if (!root.notifyServiceDied) return
    var reason = ""
    if (next.status === "failed" && previous !== "failed") {
      reason = (next.unit && next.unit.result) ? next.unit.result : "failed"
    } else if (previous === "running" && next.status === "stopped" &&
               !root.expectedStop) {
      // `foreign` -> `stopped` deliberately does not reach here: someone
      // quitting their own hand-run `ollama serve` is not our service dying.
      reason = (next.unit && next.unit.result)
        ? next.unit.result : "stopped unexpectedly"
    }
    if (reason !== "") root.serviceDied(reason)
  }

  function runAction(verb, target, kind) {
    if (root.actionInProgress !== "") return
    root.actionInProgress = target ? (verb + ":" + target) : verb
    root.actionError = ""
    root.actionExited = false
    if (verb === "stop" || verb === "restart") root.expectedStop = true
    root.actionDataVersion = root.dataVersion

    var optimistic = Model.optimisticStatusFor(verb)
    if (optimistic !== "") {
      root.optimisticStatus = optimistic
      root.statusSinceSec = Date.now() / 1000
    }

    var args = ["python3", root.actionPath, verb]
    if (target) args.push(target)
    args.push("--api-base", root.apiBase)
    if (verb === "warm") args.push("--keep-alive", String(root.keepAliveMinutes))
    if (kind) args.push("--kind", kind)
    actionProc.command = args
    actionProc.running = true
  }

  function notify(reason) {
    root.pendingNotification = reason
    sendNotification()
  }

  function sendNotification() {
    // Assigning Process.command while it is still running is a silent no-op in
    // Quickshell -- galley trap #11 -- so one at a time. A single pending slot
    // is enough here: there is only one notification type, so a burst is not
    // reachable, and a queue would be structure without a case.
    if (notifyProc.running) return
    if (root.pendingNotification === "") return
    var reason = root.pendingNotification
    root.pendingNotification = ""
    notifyProc.command = ["notify-send", "-a", "Colophon", "-u", "critical",
      "--", "Ollama stopped",
      "ollama.service is no longer running (" + reason + ")"]
    notifyProc.running = true
  }

  onServiceDied: function (reason) { root.notify(reason) }

  Timer {
    id: pollTimer
    running: true
    repeat: true
    triggeredOnStart: true
    interval: {
      if (root.panelOpen) return root.openInterval * 1000
      var status = root.status
      if (status === "stopped" || status === "failed" || status === "missing")
        return root.idleInterval * 1000
      // running, foreign, and the two transients all use the running cadence:
      // a transient resolves on its own, and it is not worth a fourth key.
      return root.runningInterval * 1000
    }
    onTriggered: root.refresh(true)
  }

  Timer {
    // dropbox/Service.qml's settleTimer. After an action the unit takes a
    // variable second or two to settle, so re-poll rather than waiting for the
    // next scheduled tick.
    id: settleTimer
    property int ticks: 0
    interval: 1000
    repeat: true
    running: false
    onTriggered: {
      settleTimer.ticks++
      root.refresh(true)
      // refresh() above is ASYNCHRONOUS, so root.status here still reflects the
      // previous poll -- it cannot yet know about the action. Concluding "not
      // transient" from a pre-action status clears expectedStop before the stop
      // is ever observed, and the confirming poll then fires a false "stopped
      // unexpectedly" for a stop the user themselves requested. So require a
      // snapshot taken AFTER the action to have landed before drawing any
      // conclusion; the tick cap remains the backstop for a broken collector.
      var settled = root.dataVersion > root.actionDataVersion
      // isTransient, not transient: `transient` is a reserved word in QML's
      // JS engine.
      var isTransient = root.status === "starting" || root.status === "stopping"
      if (settleTimer.ticks >= 6 || (settled && !isTransient)) {
        settleTimer.running = false
        settleTimer.ticks = 0
        root.optimisticStatus = ""
        root.expectedStop = false
      }
    }
  }

  Timer {
    id: clockTimer
    interval: 1000
    repeat: true
    triggeredOnStart: true
    // Only while there is something to re-render: an open panel, or a
    // transition whose 15-second relabel is counting.
    running: root.panelOpen || root.status === "starting" ||
             root.status === "stopping"
    onTriggered: root.nowSec = Date.now() / 1000
  }

  Process {
    id: collectProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleOutput(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: { if (text) root.collectorError = Model.actionErrorText(text) }
    }
    onRunningChanged: {
      if (collectProc.running) return
      // Quickshell calls neither streamEnded() nor exited() when a process
      // fails to spawn -- only runningChanged(). Clearing here is what keeps
      // `loading` from sticking true forever. Galley trap #10.
      root.loading = false
      if (root.pendingRefresh) Qt.callLater(root.refresh)
    }
  }

  Process {
    id: actionProc
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: { if (text) root.actionError = Model.actionErrorText(text) }
    }
    onExited: function (code, status) {
      root.actionExited = true
      if (code !== 0 && root.actionError === "")
        root.actionError = "Action failed with exit code " + code
    }
    onRunningChanged: {
      if (actionProc.running) return
      // Same spawn-failure trap as above. Without this branch, one bad helper
      // path leaves actionInProgress set forever and disables every button in
      // the panel -- the exact Critical defect galley shipped and fixed.
      if (!root.actionExited && root.actionInProgress !== "")
        root.actionError = "Could not run the action helper"
      if (root.actionError !== "") {
        root.optimisticStatus = ""
        root.expectedStop = false
      }
      root.actionInProgress = ""
      settleTimer.ticks = 0
      settleTimer.running = true
      Qt.callLater(root.refresh)
    }
  }

  Process {
    id: notifyProc
    onRunningChanged: {
      if (notifyProc.running) return
      Qt.callLater(root.sendNotification)
    }
  }

  Component.onCompleted: {
    root.nowSec = Date.now() / 1000
    root.statusSinceSec = root.nowSec
    root.refresh()
  }
}
