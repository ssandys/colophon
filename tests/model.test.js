// tests/model.test.js
const test = require("node:test")
const assert = require("node:assert/strict")

const Model = require("../Model.js")

const RUNNING = {
  schema: 1, status: "running", error: null,
  unit: { name: "ollama.service", loadState: "loaded", activeState: "active",
          subState: "running", unitFileState: "disabled", result: "success",
          startedAt: 1786726000, nRestarts: 0, memoryBytes: 4100000000 },
  api: { base: "http://127.0.0.1:11434", reachable: true,
         serverVersion: "0.32.6", clientVersion: null, latencyMs: 2 },
  loaded: [{ name: "llama3.2:3b", sizeBytes: 3400000000,
             vramBytes: 3400000000, processor: "gpu", gpuPercent: 100,
             expiresAt: 1786726252, parameterSize: "3.2B",
             quantization: "Q4_K_M", kind: "generate" }],
  installed: [{ name: "llama3.2:3b", sizeBytes: 3400000000, family: "llama",
                parameterSize: "3.2B", quantization: "Q4_K_M",
                kind: "generate", modifiedAt: 1739646000 }],
  summary: { loadedCount: 1, loadedBytes: 3400000000,
             installedCount: 9, installedBytes: 20401094656 }
}

function withStatus(status) {
  const copy = JSON.parse(JSON.stringify(RUNNING))
  copy.status = status
  return copy
}

test("parseSnapshot returns the parsed object", () => {
  const parsed = Model.parseSnapshot(JSON.stringify(RUNNING))
  assert.equal(parsed.status, "running")
  assert.equal(parsed.loaded.length, 1)
})

test("parseSnapshot reports empty, unreadable, and unknown-status input", () => {
  assert.match(Model.parseSnapshot("").error, /no output/)
  assert.match(Model.parseSnapshot("{not json").error, /unreadable/)
  assert.match(Model.parseSnapshot("[]").error, /unreadable|unknown/)
  assert.match(Model.parseSnapshot('{"status":"banana"}').error, /unknown/)
})

test("emptySnapshot does not mutate the shared constant", () => {
  const first = Model.emptySnapshot("boom")
  assert.equal(first.error, "boom")
  assert.equal(Model.EMPTY_SNAPSHOT.error, "")
  first.loaded.push("x")
  assert.equal(Model.EMPTY_SNAPSHOT.loaded.length, 0)
})

test("every declared status has a dot, a severity, and a label", () => {
  for (const status of Model.STATUSES) {
    assert.ok(Model.statusDot(status).length > 0, status)
    assert.ok(["error", "warn", "dim", "normal"].includes(
      Model.barSeverity(status)), status)
    assert.ok(Model.statusLabel(status, 0).length > 0, status)
  }
})

test("bar severity follows the design table", () => {
  assert.equal(Model.barSeverity("running"), "normal")
  assert.equal(Model.barSeverity("stopped"), "dim")
  assert.equal(Model.barSeverity("starting"), "warn")
  assert.equal(Model.barSeverity("stopping"), "warn")
  assert.equal(Model.barSeverity("foreign"), "warn")
  assert.equal(Model.barSeverity("failed"), "error")
  assert.equal(Model.barSeverity("missing"), "error")
})

test("starting relabels itself once it has been starting too long", () => {
  assert.equal(Model.statusLabel("starting", 0), "starting…")
  assert.equal(Model.statusLabel("starting", 14), "starting…")
  // Active with the port unbound is usually the ~1s bind window, but past 15s
  // it is a wedged server, and saying "starting" forever would be a lie.
  assert.match(Model.statusLabel("starting", 15), /not answering on :11434/)
  assert.match(Model.statusLabel("starting", 600), /not answering on :11434/)
})

test("foreign says why systemd cannot help", () => {
  assert.match(Model.statusLabel("foreign", 0), /not managed by systemd/)
  assert.match(Model.actionDisabledReason("foreign"), /outside ollama\.service/)
  assert.match(Model.actionDisabledReason("missing"), /not installed/)
  assert.equal(Model.actionDisabledReason("running"), "")
})

test("formatBytes uses SI units so rows and totals are comparable", () => {
  // Base 1000, matching `ollama list`. Base 1024 would render the 5.2 GB row
  // as 4.9 GB while the mockup's du-derived total said 19 GB -- two bases in
  // one section.
  assert.equal(Model.formatBytes(5225375512), "5.2 GB")
  assert.equal(Model.formatBytes(20401094656), "20.4 GB")
  assert.equal(Model.formatBytes(522000000), "522 MB")
  assert.equal(Model.formatBytes(274000000), "274 MB")
  assert.equal(Model.formatBytes(3400000000), "3.4 GB")
  assert.equal(Model.formatBytes(0), "0 B")
  assert.equal(Model.formatBytes(null), "0 B")
  assert.equal(Model.formatBytes(-5), "0 B")
})

test("formatDuration reads like uptime", () => {
  assert.equal(Model.formatDuration(45), "45s")
  assert.equal(Model.formatDuration(840), "14m")
  assert.equal(Model.formatDuration(3600), "1h")
  assert.equal(Model.formatDuration(7860), "2h 11m")
  assert.equal(Model.formatDuration(86400), "1d")
  assert.equal(Model.formatDuration(97200), "1d 3h")
  assert.equal(Model.formatDuration(-1), "")
})

test("formatCountdown reads like a keep-alive clock", () => {
  assert.equal(Model.formatCountdown(252), "4:12")
  assert.equal(Model.formatCountdown(65), "1:05")
  assert.equal(Model.formatCountdown(9), "0:09")
  assert.equal(Model.formatCountdown(0), "expired")
  assert.equal(Model.formatCountdown(-30), "expired")
  assert.equal(Model.formatCountdown(7200), "2h")
})

test("uptimeSeconds is null when the unit never started", () => {
  assert.equal(Model.uptimeSeconds(RUNNING, 1786726840), 840)
  const never = JSON.parse(JSON.stringify(RUNNING))
  never.unit.startedAt = null
  assert.equal(Model.uptimeSeconds(never, 1786726840), null)
  // A clock that went backwards must not render a negative uptime.
  assert.equal(Model.uptimeSeconds(RUNNING, 1786725000), null)
})

test("the badge counts loaded models, and only while something serves", () => {
  assert.equal(Model.badgeText(RUNNING), "1")
  assert.equal(Model.badgeText(withStatus("foreign")), "1")
  assert.equal(Model.badgeText(withStatus("stopped")), "")
  assert.equal(Model.badgeText(withStatus("failed")), "")
  const many = JSON.parse(JSON.stringify(RUNNING))
  many.summary.loadedCount = 12
  assert.equal(Model.badgeText(many), "9+")
  const none = JSON.parse(JSON.stringify(RUNNING))
  none.summary.loadedCount = 0
  assert.equal(Model.badgeText(none), "")
})

test("processorLabel distinguishes GPU, CPU, and a split", () => {
  assert.equal(Model.processorLabel({ processor: "gpu", gpuPercent: 100 }), "GPU")
  assert.equal(Model.processorLabel({ processor: "cpu", gpuPercent: 0 }), "CPU")
  assert.equal(Model.processorLabel({ processor: "split", gpuPercent: 62 }),
               "62% GPU")
  assert.equal(Model.processorLabel(null), "")
})

test("action availability follows the panel mockups", () => {
  assert.equal(Model.canStart("stopped", ""), true)
  assert.equal(Model.canStart("failed", ""), true)
  assert.equal(Model.canStop("running", ""), true)
  assert.equal(Model.canStop("starting", ""), true)
  assert.equal(Model.canRestart("running", ""), true)
  assert.equal(Model.canRestart("failed", ""), true)
  // The widget must never offer to stop something systemd cannot stop.
  assert.equal(Model.canStop("foreign", ""), false)
  assert.equal(Model.canRestart("foreign", ""), false)
  assert.equal(Model.canStart("foreign", ""), false)
  assert.equal(Model.canStart("missing", ""), false)
  assert.equal(Model.canStop("missing", ""), false)
  // Nothing is clickable while an action is in flight.
  for (const status of Model.STATUSES) {
    assert.equal(Model.canStart(status, "start"), false)
    assert.equal(Model.canStop(status, "stop:x"), false)
    assert.equal(Model.canRestart(status, "warm:llama3.2:3b"), false)
  }
})

test("optimisticStatusFor drives the instant-feedback override", () => {
  assert.equal(Model.optimisticStatusFor("start"), "starting")
  assert.equal(Model.optimisticStatusFor("restart"), "starting")
  assert.equal(Model.optimisticStatusFor("stop"), "stopping")
  // warm and unload do not change the service's status, so they must not
  // override it -- their feedback is the row label.
  assert.equal(Model.optimisticStatusFor("warm"), "")
  assert.equal(Model.optimisticStatusFor("unload"), "")
})

test("actionErrorText reports the action as not authorized", () => {
  const denied = Model.actionErrorText(
    "Failed to start ollama.service: Interactive authentication required.")
  assert.match(denied, /not authorized/)
  assert.ok(!denied.includes("install-privileges"))
  assert.ok(!denied.includes("polkit rule"))
  assert.equal(Model.actionErrorText(""), "")
  assert.equal(Model.actionErrorText("boom"), "boom")
  assert.ok(Model.actionErrorText("x".repeat(400)).length <= 160)
})

test("bootLabel labels enabled and disabled, and hides the line when empty", () => {
  assert.equal(Model.bootLabel("disabled"), "disabled at boot")
  assert.equal(Model.bootLabel("enabled"), "enabled at boot")
  assert.equal(Model.bootLabel(""), "")
})

test("tooltipText summarises each state", () => {
  assert.match(Model.tooltipText(RUNNING, 1786726840),
               /ollama 0\.32\.6 · up 14m · llama3\.2:3b loaded \(GPU\)/)
  const stopped = withStatus("stopped")
  stopped.api.reachable = false
  stopped.api.serverVersion = null
  stopped.api.clientVersion = "0.32.6"
  stopped.loaded = []
  stopped.summary.loadedCount = 0
  assert.match(Model.tooltipText(stopped, 1786726840),
               /ollama 0\.32\.6 stopped · 9 models, 20\.4 GB/)
  assert.match(Model.tooltipText(withStatus("missing"), 0), /not found/)
  assert.equal(Model.tooltipText(null, 0), "Colophon")
})

test("dotColor maps every status to its panel color", () => {
  const DIM = "#777777"   // stand-in for the panel's dim fallback
  assert.equal(Model.dotColor("running", DIM), Model.COLOR_OK)
  assert.equal(Model.dotColor("starting", DIM), Model.COLOR_BUSY)
  assert.equal(Model.dotColor("stopping", DIM), Model.COLOR_BUSY)
  assert.equal(Model.dotColor("foreign", DIM), Model.COLOR_WARN)
  assert.equal(Model.dotColor("failed", DIM), Model.COLOR_ERROR)
  assert.equal(Model.dotColor("missing", DIM), Model.COLOR_ERROR)
  // stopped is the only status that defers to the caller's dim color.
  assert.equal(Model.dotColor("stopped", DIM), DIM)
  // And nothing returns undefined, which would paint an invisible dot.
  for (const status of Model.STATUSES) {
    assert.match(Model.dotColor(status, DIM), /^#[0-9a-f]{6}$/i, status)
  }
})

test("dotColor and barSeverity diverge only where intended", () => {
  // barSeverity buckets the two transients with foreign as "warn" for the bar
  // glyph; dotColor gives them their own COLOR_BUSY in the panel. That
  // divergence is deliberate -- pin it so neither side drifts silently.
  assert.equal(Model.barSeverity("starting"), "warn")
  assert.equal(Model.dotColor("starting", "#000000"), Model.COLOR_BUSY)
  assert.equal(Model.barSeverity("foreign"), "warn")
  assert.equal(Model.dotColor("foreign", "#000000"), Model.COLOR_WARN)
})

test("tooltipText names the foreign case and claims no uptime for it", () => {
  const foreign = withStatus("foreign")
  const text = Model.tooltipText(foreign, 1786726840)
  assert.match(text, /not managed by systemd/)
  // No uptime claim for a server systemd did not start.
  assert.ok(!text.includes("up "))
})

test("actionErrorText explains a refused prompt without naming a script", () => {
  for (const phrase of ["Interactive authentication required",
                        "Access denied", "not authorized"]) {
    const text = Model.actionErrorText("systemctl: " + phrase + ".")
    assert.match(text, /not authorized/, phrase)
    // The old message told the user to run bin/install-privileges. That script
    // no longer exists, and a dismissed dialog was never a setup problem.
    assert.ok(!text.includes("install-privileges"), phrase)
    assert.ok(!text.includes("polkit rule"), phrase)
  }
})

test("BAR_GLYPH is one BMP character, and the intended codepoint", () => {
  // Asserted numerically, never against a pasted literal: U+EE86 is in the
  // Private Use Area, and a literal here would be exactly the fragility the
  // constant exists to avoid. Length 1 pins the single-escape property --
  // a surrogate pair would be length 2 and would break the guard's regex.
  assert.equal(typeof Model.BAR_GLYPH, "string")
  assert.equal(Model.BAR_GLYPH.length, 1)
  assert.equal(Model.BAR_GLYPH.codePointAt(0), 0xEE86)
})

test("bootLabel names every state it knows and never hides an unknown one", () => {
  assert.equal(Model.bootLabel("enabled"), "enabled at boot")
  assert.equal(Model.bootLabel("disabled"), "disabled at boot")
  assert.equal(Model.bootLabel("enabled-runtime"), "enabled until reboot")
  assert.equal(Model.bootLabel("masked"), "masked")
  assert.equal(Model.bootLabel("masked-runtime"), "masked")
  // static means the unit has no [Install] section, so there is nothing to
  // enable or disable -- not a state the user could change.
  assert.equal(Model.bootLabel("static"), "no boot setting")
  assert.equal(Model.bootLabel("generated"), "generated unit")
  assert.equal(Model.bootLabel("transient"), "transient unit")
  // An unrecognised state renders raw rather than vanishing. A line that
  // disappears reads as a bug -- that is the defect this feature fixes, and
  // it must not come back for values this table does not list.
  assert.equal(Model.bootLabel("linked"), "linked")
  assert.equal(Model.bootLabel("indirect"), "indirect")
  assert.equal(Model.bootLabel("some-future-systemd-state"),
               "some-future-systemd-state")
  // Only genuinely absent state hides the line.
  assert.equal(Model.bootLabel(""), "")
  assert.equal(Model.bootLabel(undefined), "")
  assert.equal(Model.bootLabel(null), "")
})

test("bootLabel never returns an inherited Object.prototype member", () => {
  // BOOT_LABELS is an object literal, so a bare table[state] lookup walks the
  // prototype chain: for these names it yields a function or Object.prototype
  // itself rather than undefined, and the raw-string fallback never runs. The
  // fallback is the whole point of the table -- an unanticipated state must
  // render visibly instead of vanishing -- so this is the one input class where
  // it silently would not. Reaching a QML Text.text binding, a function renders
  // as nonsense rather than as the state name.
  for (const state of ["constructor", "toString", "hasOwnProperty", "valueOf",
                       "isPrototypeOf", "propertyIsEnumerable", "__proto__"]) {
    const label = Model.bootLabel(state)
    assert.equal(typeof label, "string", state + " must yield a string")
    assert.equal(label, state, state + " must fall through to the raw value")
  }
})

test("bootIsToggleable is true for exactly the two states systemd can flip", () => {
  assert.equal(Model.bootIsToggleable("enabled"), true)
  assert.equal(Model.bootIsToggleable("disabled"), true)
  for (const state of ["enabled-runtime", "masked", "masked-runtime", "static",
                       "generated", "transient", "linked", "linked-runtime",
                       "alias", "indirect", "bad", "", "unknown"]) {
    assert.equal(Model.bootIsToggleable(state), false, state)
  }
  assert.equal(Model.bootIsToggleable(undefined), false)
  assert.equal(Model.bootIsToggleable(null), false)
})

test("optimisticStatusFor stays silent for the boot verbs", () => {
  // enable/disable change nothing about run state. Returning a run status here
  // would make the panel claim the service was starting when it was not --
  // and would arm the wrong bridge state. See AGENTS.md trap #19: the boot
  // toggle's optimistic value is separate, with its own clearing rule.
  assert.equal(Model.optimisticStatusFor("enable"), "")
  assert.equal(Model.optimisticStatusFor("disable"), "")
})

test("Model.js holds no state between calls", () => {
  const first = Model.tooltipText(RUNNING, 1786726840)
  Model.badgeText(RUNNING)
  Model.statusLabel("starting", 900)
  assert.equal(Model.tooltipText(RUNNING, 1786726840), first)
})
