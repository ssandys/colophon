// Pure presentation helpers for Colophon.
//
// Loaded by Panel.qml (import "Model.js" as Model) AND by node --test, and the
// two engines do not accept the same syntax. So: no I/O, no QML imports, no
// timers, no state between calls, and everything at top level is `var` or
// `function`. Never introduce arrow functions, spread, template literals,
// let/const, Object.assign, .includes( or .endsWith( in this file. The test
// file is exempt -- it only ever runs under node.

var COLOR_OK = "#22c55e"
var COLOR_WARN = "#eab308"
var COLOR_ERROR = "#ef4444"
var COLOR_BUSY = "#3b82f6"

// The bar glyph, defined once for the whole project: Panel.qml binds
// root.barIcon to this rather than carrying its own literal, and
// BarGlyphTest asserts both that this value is the intended escape and
// that Panel.qml does not inline one of its own.
//
// U+EE86 is nf-fa-stamp -- a colophon is a printer's mark, and the sibling
// plugin Galley wears a printer. Written as a \uXXXX escape and never as
// the literal character: it is in the Unicode Private Use Area, and a PUA
// character does not survive every editing path. See AGENTS.md trap #14.
var BAR_GLYPH = "\uEE86"

var BADGE_MAX = 9

// How long `starting` may persist before the label admits the server is not
// coming up. Presentation only: the collector keeps reporting `starting`,
// because "active but not answering" is genuinely all systemd knows.
var STARTING_RELABEL_SEC = 15

// Must stay equal to colophon_collect.STATUSES; tests/test_cross_language.py
// diffs the two sets, because a one-sided edit fails silently.
var STATUSES = ["running", "starting", "stopping", "stopped", "failed",
                "foreign", "missing"]

var EMPTY_SNAPSHOT = {
  schema: 1,
  status: "stopped",
  error: "",
  unit: { name: "ollama.service", loadState: "", activeState: "",
          subState: "", unitFileState: "", result: "", startedAt: null,
          nRestarts: 0, memoryBytes: null },
  api: { base: "", reachable: false, serverVersion: null,
         clientVersion: null, latencyMs: null },
  loaded: [],
  installed: [],
  summary: { loadedCount: 0, loadedBytes: 0, installedCount: 0,
             installedBytes: 0 }
}

function emptySnapshot(errorText) {
  // Deep clone via JSON so callers cannot mutate the shared constant, and
  // without Object.assign (banned above, and shallow anyway).
  var snapshot = JSON.parse(JSON.stringify(EMPTY_SNAPSHOT))
  snapshot.error = errorText || ""
  return snapshot
}

function parseSnapshot(raw) {
  var text = String(raw === undefined || raw === null ? "" : raw).trim()
  if (text === "") return emptySnapshot("The collector produced no output")
  var parsed
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    return emptySnapshot("The collector produced unreadable output")
  }
  if (!parsed || typeof parsed !== "object" || parsed instanceof Array)
    return emptySnapshot("The collector produced unreadable output")
  if (STATUSES.indexOf(parsed.status) < 0)
    return emptySnapshot("The collector reported an unknown status")
  return parsed
}

function statusDot(status) {
  if (status === "running") return "●"                       // ●
  if (status === "foreign") return "◐"                       // ◐
  if (status === "starting" || status === "stopping") return "◌"  // ◌
  if (status === "stopped") return "○"                       // ○
  return "✕"                                                 // ✕
}

function dotColor(status, fallback) {
  if (status === "running") return COLOR_OK
  if (status === "starting" || status === "stopping") return COLOR_BUSY
  if (status === "foreign") return COLOR_WARN
  if (status === "failed" || status === "missing") return COLOR_ERROR
  return fallback
}

function barSeverity(status) {
  if (status === "failed" || status === "missing") return "error"
  if (status === "starting" || status === "stopping" || status === "foreign")
    return "warn"
  if (status === "stopped") return "dim"
  return "normal"
}

function statusLabel(status, secondsInState) {
  if (status === "running") return "running"
  if (status === "stopping") return "stopping…"
  if (status === "stopped") return "stopped"
  if (status === "failed") return "failed"
  if (status === "missing") return "ollama.service not found"
  if (status === "foreign") return "running — not managed by systemd"
  if (status === "starting") {
    var seconds = Number(secondsInState)
    if (isFinite(seconds) && seconds >= STARTING_RELABEL_SEC)
      return "started, but not answering on :11434"
    return "starting…"
  }
  return String(status || "")
}

// systemd's UnitFileState has far more values than enabled/disabled. Returning
// "" for the rest hid the line completely, which reads as a widget bug -- a
// masked unit showed nothing at all. Unknown values now render raw so a state
// this table does not anticipate is visible rather than silent.
var BOOT_LABELS = {
  "enabled": "enabled at boot",
  "disabled": "disabled at boot",
  "enabled-runtime": "enabled until reboot",
  "masked": "masked",
  "masked-runtime": "masked",
  // No [Install] section, so there is nothing to enable or disable.
  "static": "no boot setting",
  "generated": "generated unit",
  "transient": "transient unit"
}

// Deliberately not `String(x || "")`, the shorter idiom used elsewhere in this
// file: `||` collapses every falsy value, so a unitFileState of 0 or false --
// reachable if the collector's JSON shape ever changes, since the value is
// JSON-derived -- would become "", and bootLabel treats "" as "hide the boot
// line". A vanishing boot line is the defect the boot toggle was built to fix.
// Only genuinely absent state hides it. Pinned by a test in model.test.js.
function coerceUnitFileState(unitFileState) {
  return String(unitFileState === undefined || unitFileState === null
                ? "" : unitFileState)
}

function bootLabel(unitFileState) {
  var state = coerceUnitFileState(unitFileState)
  if (state === "") return ""
  // hasOwnProperty.call, not a bare BOOT_LABELS[state]: a bare lookup walks the
  // prototype chain, so a state named "constructor" or "toString" returns an
  // inherited function instead of falling through to the raw value below.
  if (!Object.prototype.hasOwnProperty.call(BOOT_LABELS, state)) return state
  return BOOT_LABELS[state]
}

// Only enabled and disabled can be flipped. enable on a masked or static unit
// fails, and enabled-runtime has no unambiguous meaning for a click -- it
// would have to choose between making it permanent and clearing it. Those
// states show their label with no switch.
function bootIsToggleable(unitFileState) {
  var state = coerceUnitFileState(unitFileState)
  return state === "enabled" || state === "disabled"
}

// The four parameters the panel's editor owns, in display order. Bounds are
// mirrored in colophon_action.py, which is the only surface that writes, and
// tests/test_cross_language.py asserts the two agree along with Panel.qml --
// a one-sided edit here fails silently otherwise. See AGENTS.md trap #12.
var PARAM_SPECS = [
  { key: "num_ctx", label: "context", min: 4096, max: 131072,
    step: 1, decimals: 0 },
  { key: "temperature", label: "temperature", min: 0, max: 2,
    step: 0.01, decimals: 2 },
  { key: "top_p", label: "top_p", min: 0, max: 1,
    step: 0.01, decimals: 2 },
  { key: "top_k", label: "top_k", min: 1, max: 200,
    step: 1, decimals: 0 }]

function paramSpec(key) {
  for (var i = 0; i < PARAM_SPECS.length; i++)
    if (PARAM_SPECS[i].key === key) return PARAM_SPECS[i]
  return null
}

function paramValue(entry, key) {
  if (!entry || !entry.parameters) return null
  var raw = entry.parameters[key]
  if (typeof raw !== "number" || !isFinite(raw)) return null
  return raw
}

function formatParamValue(key, value) {
  if (value === null || value === undefined) return ""
  var spec = paramSpec(key)
  if (!spec) return ""
  var number = Number(value)
  if (!isFinite(number)) return ""
  // toFixed then strip trailing zeros, so 0.60 reads as 0.6 while 0.95 keeps
  // both digits. A fixed 2dp would render every context as "8192.00".
  if (spec.decimals === 0) return String(Math.round(number))
  var text = number.toFixed(spec.decimals)
  while (text.indexOf(".") >= 0 &&
         (text.charAt(text.length - 1) === "0" ||
          text.charAt(text.length - 1) === "."))
    text = text.substring(0, text.length - 1)
  return text
}

function parseParamInput(key, text) {
  var spec = paramSpec(key)
  if (!spec) return NaN
  var trimmed = String(text === undefined || text === null ? "" : text).trim()
  if (trimmed === "") return NaN
  var number = Number(trimmed)
  if (!isFinite(number)) return NaN
  // Not Math.trunc: it is ES6, and ModelJsSyntaxTest is a regex list that
  // could not catch it if the QML engine choked. Nothing here tests that
  // engine, so use the form that has always worked.
  if (spec.decimals === 0)
    number = number < 0 ? Math.ceil(number) : Math.floor(number)
  // Clamp rather than reject: a typed 999999 is an unambiguous intent to go as
  // high as allowed, and rejecting it would just revert the field silently.
  return Math.max(spec.min, Math.min(spec.max, number))
}

function paramIsDirty(entry, key, text) {
  var typed = parseParamInput(key, text)
  var current = paramValue(entry, key)
  // Garbage never counts as a change: the field reverts, so apply must not
  // offer to send a value that cannot exist.
  if (isNaN(typed)) return false
  if (current === null) return true
  return typed !== current
}

function formatBytes(bytes) {
  // SI, base 1000, matching `ollama list`. See the plan's deviations note.
  var value = Number(bytes)
  if (!isFinite(value) || value <= 0) return "0 B"
  var units = ["B", "KB", "MB", "GB", "TB"]
  var index = 0
  while (value >= 1000 && index < units.length - 1) {
    value = value / 1000
    index++
  }
  var digits = (index >= 2 && value < 100) ? 1 : 0
  return value.toFixed(digits) + " " + units[index]
}

function formatDuration(seconds) {
  var total = Number(seconds)
  if (!isFinite(total) || total < 0) return ""
  total = Math.floor(total)
  if (total < 60) return total + "s"
  var minutes = Math.floor(total / 60)
  if (minutes < 60) return minutes + "m"
  var hours = Math.floor(minutes / 60)
  var restMinutes = minutes % 60
  if (hours < 24)
    return restMinutes > 0 ? hours + "h " + restMinutes + "m" : hours + "h"
  var days = Math.floor(hours / 24)
  var restHours = hours % 24
  return restHours > 0 ? days + "d " + restHours + "h" : days + "d"
}

function formatCountdown(seconds) {
  var total = Number(seconds)
  if (!isFinite(total) || total <= 0) return "expired"
  total = Math.floor(total)
  if (total >= 3600) return formatDuration(total)
  var minutes = Math.floor(total / 60)
  var rest = total % 60
  return minutes + ":" + (rest < 10 ? "0" + rest : String(rest))
}

function uptimeSeconds(snapshot, nowSec) {
  if (!snapshot || !snapshot.unit) return null
  var startedAt = snapshot.unit.startedAt
  if (startedAt === null || startedAt === undefined) return null
  var delta = Math.floor(Number(nowSec) - Number(startedAt))
  if (!isFinite(delta) || delta < 0) return null
  return delta
}

function badgeText(snapshot) {
  if (!snapshot) return ""
  if (snapshot.status !== "running" && snapshot.status !== "foreign") return ""
  var count = snapshot.summary ? Number(snapshot.summary.loadedCount) : 0
  if (!isFinite(count) || count <= 0) return ""
  return count > BADGE_MAX ? BADGE_MAX + "+" : String(count)
}

function plural(count, word) {
  return count + " " + word + (count === 1 ? "" : "s")
}

function processorLabel(model) {
  if (!model) return ""
  if (model.processor === "gpu") return "GPU"
  if (model.processor === "cpu") return "CPU"
  return Number(model.gpuPercent) + "% GPU"
}

function canStart(status, actionInProgress) {
  if (actionInProgress !== "") return false
  return status === "stopped" || status === "failed"
}

function canStop(status, actionInProgress) {
  if (actionInProgress !== "") return false
  return status === "running" || status === "starting"
}

function canRestart(status, actionInProgress) {
  if (actionInProgress !== "") return false
  return status === "running" || status === "failed"
}

function actionDisabledReason(status) {
  if (status === "foreign")
    return "Started outside ollama.service — systemd cannot stop it"
  if (status === "missing") return "ollama.service is not installed"
  return ""
}

function optimisticStatusFor(verb) {
  if (verb === "start" || verb === "restart") return "starting"
  if (verb === "stop") return "stopping"
  return ""
}

function actionErrorText(stderr) {
  var text = String(stderr === undefined || stderr === null ? "" : stderr)
  text = text.replace(/\s+/g, " ").trim()
  if (text === "") return ""
  if (text.indexOf("Interactive authentication required") >= 0 ||
      text.indexOf("Access denied") >= 0 ||
      text.indexOf("not authorized") >= 0) {
    return "not authorized — the authentication prompt was dismissed or denied"
  }
  return text.length > 160 ? text.substring(0, 157) + "…" : text
}

function tooltipText(snapshot, nowSec) {
  if (!snapshot) return "Colophon"
  var status = snapshot.status
  if (status === "missing") return "ollama.service not found"

  var api = snapshot.api || {}
  var version = api.serverVersion || api.clientVersion || ""
  var head = "ollama" + (version ? " " + version : "")

  if (status === "running" || status === "foreign") {
    var parts = [head]
    if (status === "foreign") parts.push("not managed by systemd")
    else {
      var up = uptimeSeconds(snapshot, nowSec)
      if (up !== null) parts.push("up " + formatDuration(up))
    }
    var loaded = snapshot.loaded || []
    if (loaded.length === 0) parts.push("no models loaded")
    else if (loaded.length === 1)
      parts.push(loaded[0].name + " loaded (" + processorLabel(loaded[0]) + ")")
    else parts.push(loaded.length + " models loaded")
    return parts.join(" · ")
  }

  var summary = snapshot.summary || {}
  var count = Number(summary.installedCount) || 0
  return head + " " + statusLabel(status, 0) + " · " +
         plural(count, "model") + ", " + formatBytes(summary.installedBytes)
}

// QML's engine has no `module`, so this block is skipped there and the file
// stays a plain script for `import "Model.js" as Model`.
if (typeof module !== "undefined") {
  module.exports = {
    COLOR_OK: COLOR_OK,
    COLOR_WARN: COLOR_WARN,
    COLOR_ERROR: COLOR_ERROR,
    COLOR_BUSY: COLOR_BUSY,
    BAR_GLYPH: BAR_GLYPH,
    BADGE_MAX: BADGE_MAX,
    STARTING_RELABEL_SEC: STARTING_RELABEL_SEC,
    STATUSES: STATUSES,
    EMPTY_SNAPSHOT: EMPTY_SNAPSHOT,
    emptySnapshot: emptySnapshot,
    parseSnapshot: parseSnapshot,
    statusDot: statusDot,
    dotColor: dotColor,
    barSeverity: barSeverity,
    statusLabel: statusLabel,
    bootLabel: bootLabel,
    bootIsToggleable: bootIsToggleable,
    PARAM_SPECS: PARAM_SPECS,
    paramValue: paramValue,
    formatParamValue: formatParamValue,
    parseParamInput: parseParamInput,
    paramIsDirty: paramIsDirty,
    formatBytes: formatBytes,
    formatDuration: formatDuration,
    formatCountdown: formatCountdown,
    uptimeSeconds: uptimeSeconds,
    badgeText: badgeText,
    plural: plural,
    processorLabel: processorLabel,
    canStart: canStart,
    canStop: canStop,
    canRestart: canRestart,
    actionDisabledReason: actionDisabledReason,
    optimisticStatusFor: optimisticStatusFor,
    actionErrorText: actionErrorText,
    tooltipText: tooltipText
  }
}
