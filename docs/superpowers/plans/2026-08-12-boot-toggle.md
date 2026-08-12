# Boot Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Colophon's boot-state line settable — a switch beside it runs `systemctl enable` / `disable` on `ollama.service`.

**Architecture:** Four thin layers, each independently testable. `colophon_action.py` gains two verbs and a tuple whose contract is "everything that shells out to `systemctl`". `Model.js` gains two pure functions mapping `UnitFileState` to a label and to a toggleable predicate. `Service.qml` gains a boot branch with its own optimistic value and its own clearing rule. `Panel.qml` puts an upstream `ToggleSwitch` beside the existing `Text`.

**Tech Stack:** Python 3 stdlib, ES5-subset JavaScript, QML (Quickshell), systemd/polkit.

**Spec:** `docs/superpowers/specs/2026-08-12-boot-toggle-design.md`. Read it first — it carries the reasoning for the guard decision and the optimistic-clearing decision, both of which are load-bearing.

## Global Constraints

- **Python is stdlib-only, no pip ever.** Permitted: `datetime`, `glob`, `http.client`, `json`, `os`, `re`, `shlex`, `shutil`, `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`.
- **`Model.js` is ES5-subset and dual-engine.** No arrow functions, spread, template literals, `let`/`const`, `Object.assign`, `.includes(`, `.endsWith(`. Top level is `var`/`function` only. `ModelJsSyntaxTest` enforces it. Test files are exempt.
- **`Model.js` is a pure presentation layer.** No state between calls, no I/O, no `Date.now()`. Suite-enforced.
- **Never write a literal Unicode Private Use Area character** anywhere — code, docs, or commit message. Reference codepoints numerically (`chr(0xEE86)`) if you must manipulate one. A repo-wide scan is currently clean; keep it so.
- **`transient`, `volatile`, `synchronized`, `native`, `throws`, `goto`, `implements`** are reserved in QML's JS grammar. `qmllint` here reports every parse error as a bare exit 255 with **no message**. `transient` appears in this plan only as a string *value* — never make it an identifier.
- The unit name is the fixed literal `ollama.service`.
- Never edit `/usr/share/omarchy/` — but reading it is expected and encouraged.
- **Standing safety rule:** no test may start, stop, restart, **enable, or disable** `ollama.service`, and none may pull or delete a model. Every privileged verb is asserted through `--dry-run` only. Task 6's by-hand checks are the deliberate exception.
- **Every enable/disable raises an authentication dialog** (trap #31). Do not run a boot verb without `--dry-run` during implementation — it prompts on the owner's screen.
- Baseline before you start: **120 Python + 24 JavaScript tests, 0 skips.**

## File Structure

| File | Change |
|---|---|
| `scripts/colophon_action.py` | Add `BOOT_VERBS`, `SYSTEMCTL_VERBS`; accept both verbs in `plan()`, `execute()`, and validation |
| `tests/test_action.py` | Widen the flag guard to `SYSTEMCTL_VERBS`; add boot-verb argv cases |
| `Model.js` | Extend `bootLabel`; add `bootIsToggleable`; export it |
| `tests/model.test.js` | Cover the state table, the predicate, and `optimisticStatusFor`'s silence on boot verbs |
| `Service.qml` | `optimisticBootState` property, boot branch in `runAction`, clearing rule |
| `Panel.qml` | `RowLayout` wrapping the boot `Text` plus a `ToggleSwitch`; delete the stale comment |
| `README.md` | Invert "Boot start"; delete the Troubleshooting line |
| `AGENTS.md` | Dated note on trap #28 |

---

## Task 1: Two verbs, and a guard that cannot be escaped

**Files:**
- Modify: `scripts/colophon_action.py:32-33` (the verb tuples), `plan()` at line 92, `execute()` at line 183, validation at line 231
- Test: `tests/test_action.py:20-41`

**Interfaces:**
- Consumes: nothing.
- Produces: `BOOT_VERBS = ("enable", "disable")` and `SYSTEMCTL_VERBS = LIFECYCLE_VERBS + BOOT_VERBS` as module-level names in `scripts/colophon_action.py`. `plan("enable", …)` returns `["/usr/bin/systemctl enable ollama.service"]`. `systemctl_command("enable")` returns `["/usr/bin/systemctl", "enable", "ollama.service"]`. Task 3 relies on `optimisticStatusFor` returning `""` for both boot verbs, which is `Model.js`'s side of this contract, not Python's.

**Why the tuple split matters.** `test_the_prompt_is_never_suppressed` is, per the 2026-08-11 final review's mutation testing, the assertion standing between this project and its signature failure mode. It currently iterates a hardcoded `("start", "stop", "restart")`. Two new `systemctl` verbs added beside it would leave the guard passing while shipping unguarded calls. `SYSTEMCTL_VERBS` exists so the guard's contract is "everything that shells out to `systemctl`".

- [ ] **Step 1: Widen the flag guard and add the boot-verb plan assertions**

In `tests/test_action.py`, replace `PlanTest`'s two methods (lines 21-41) entirely:

```python
    def test_lifecycle_verbs_are_one_systemctl_call(self):
        for verb in ("start", "stop", "restart"):
            with self.subTest(verb=verb):
                self.assertEqual(
                    action.plan(verb, "", "generate", 5,
                                "http://127.0.0.1:11434", False),
                    ["/usr/bin/systemctl " + verb + " ollama.service"])

    def test_boot_verbs_are_one_systemctl_call(self):
        # enable/disable go through manage-unit-files rather than manage-units,
        # but the constructed command is the same shape: one systemctl call,
        # no flag. They never touch run state, so plan() must not add a start
        # step the way `warm` does on a stopped server.
        for verb in ("enable", "disable"):
            with self.subTest(verb=verb):
                self.assertEqual(
                    action.plan(verb, "", "generate", 5,
                                "http://127.0.0.1:11434", False),
                    ["/usr/bin/systemctl " + verb + " ollama.service"])

    def test_the_prompt_is_never_suppressed(self):
        # --no-ask-password sets allow_interactive_authorization=false on the
        # D-Bus call, which turns Omarchy's authentication dialog into a bare
        # "Access denied". Re-adding it does not fail loudly -- every action
        # silently becomes permission denied, with no error anywhere. The flag
        # looks defensive, and galley is one copy-paste away, so this asserts
        # its absence rather than trusting nobody re-adds it.
        #
        # This iterates SYSTEMCTL_VERBS, not LIFECYCLE_VERBS, deliberately: the
        # guard's contract is every verb that shells out to systemctl. A new
        # verb category added to its own tuple would otherwise ship unguarded
        # while this test kept passing.
        self.assertEqual(action.SYSTEMCTL_VERBS,
                         action.LIFECYCLE_VERBS + action.BOOT_VERBS,
                         "SYSTEMCTL_VERBS must cover every systemctl verb")
        for verb in action.SYSTEMCTL_VERBS:
            with self.subTest(verb=verb):
                self.assertNotIn(
                    "--no-ask-password", action.systemctl_command(verb),
                    "the prompt must not be suppressed -- see "
                    "docs/superpowers/specs/2026-08-11-prompted-privilege-design.md")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest tests.test_action -v 2>&1 | tail -25`

Expected: FAIL, two failures, both confirmed against the current tree on 2026-08-12:

- `test_boot_verbs_are_one_systemctl_call` — `plan("enable", …)` falls past the lifecycle branch into the model-verb path and returns
  `['POST http://127.0.0.1:11434/api/generate {"keep_alive": "5m", "model": ""}']`
  where the test expects `['/usr/bin/systemctl enable ollama.service']`.
- `test_the_prompt_is_never_suppressed` — `AttributeError: module 'colophon_action' has no attribute 'SYSTEMCTL_VERBS'`, raised at the `assertEqual` before the loop runs.

Note what does **not** fail: `systemctl_command("enable")` already returns `['/usr/bin/systemctl', 'enable', 'ollama.service']` today, because it interpolates whatever verb it is handed and carries no flag. The per-verb half of the guard would pass on day one; the attribute assertion is what makes the test red. That is the point — the tuple, not the command builder, is what this task adds.

- [ ] **Step 3: Add the tuples**

In `scripts/colophon_action.py`, replace lines 32-33:

```python
LIFECYCLE_VERBS = ("start", "stop", "restart")
BOOT_VERBS = ("enable", "disable")
# Every verb that shells out to systemctl. The flag guard in
# tests/test_action.py iterates this rather than LIFECYCLE_VERBS so a new verb
# category cannot ship without the --no-ask-password assertion covering it.
SYSTEMCTL_VERBS = LIFECYCLE_VERBS + BOOT_VERBS
MODEL_VERBS = ("warm", "unload")
```

- [ ] **Step 4: Route both verbs through plan, execute, and validation**

Three one-line changes.

`plan()` — line 92 currently reads `if verb in LIFECYCLE_VERBS:`. Replace with:

```python
    if verb in SYSTEMCTL_VERBS:
```

`execute()` — line 183 currently reads `if verb in LIFECYCLE_VERBS:`. Replace with:

```python
    if verb in SYSTEMCTL_VERBS:
```

Validation — line 231 currently reads `if verb not in LIFECYCLE_VERBS + MODEL_VERBS:`. Replace with:

```python
    if verb not in SYSTEMCTL_VERBS + MODEL_VERBS:
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `python3 -m unittest tests.test_action -v 2>&1 | tail -10`
Expected: OK.

- [ ] **Step 6: Confirm the dry-run output by hand, without authenticating**

Run: `python3 scripts/colophon_action.py enable --dry-run && python3 scripts/colophon_action.py disable --dry-run`

Expected, exactly:

```
/usr/bin/systemctl enable ollama.service
/usr/bin/systemctl disable ollama.service
```

`--dry-run` prints and exits without calling systemd, so this raises no dialog. **Do not run either verb without `--dry-run`.**

- [ ] **Step 7: Run the whole suite**

Run: `./bin/test`
Expected: **121 Python + 24 JavaScript, 0 skips**, exit 0. Python is up one from 120: `PlanTest` gained `test_boot_verbs_are_one_systemctl_call`.

- [ ] **Step 8: Commit**

```bash
git add scripts/colophon_action.py tests/test_action.py
git commit -m "feat: enable and disable verbs, and a guard that covers them"
```

---

## Task 2: Boot state presentation

**Files:**
- Modify: `Model.js:117-121` (`bootLabel`), and the export block at the file's end
- Test: `tests/model.test.js`

**Interfaces:**
- Consumes: nothing from Task 1 — this task is pure presentation and shares no code with the action script.
- Produces: `Model.bootLabel(unitFileState) -> string` (extended) and `Model.bootIsToggleable(unitFileState) -> bool` (new), both exported from the object `Model.js` returns. Task 3 binds `Panel.qml`'s switch `visible` to `bootIsToggleable`; Task 4 renders `bootLabel`.

**The unknown-value rule.** An unrecognised non-empty state renders the raw systemd string. The current disappearing-line behaviour is the bug being fixed; reintroducing it one layer down for unknown values would be the same mistake. Only genuinely empty input returns `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/model.test.js`, before the file's closing lines:

`tests/model.test.js` already does `const Model = require("../Model.js")` at the
top of the file, and every existing test calls `Model.someFunction(...)`
directly. Follow that — there is no per-test loader helper and you must not add
one.

```javascript
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `node --test tests/model.test.js 2>&1 | tail -20`

Expected: FAIL. `bootLabel("enabled-runtime")` returns `""` against an expected `"enabled until reboot"`, and `bootIsToggleable` is `undefined`, not a function. The `optimisticStatusFor` test should **pass already** — it returns `""` for any unrecognised verb — and that is intentional: it pins existing correct behaviour so a later change cannot quietly route boot verbs through the run-status path.

- [ ] **Step 3: Extend bootLabel and add the predicate**

In `Model.js`, replace `bootLabel` (lines 117-121) entirely:

```javascript
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

function bootLabel(unitFileState) {
  var state = String(unitFileState === undefined || unitFileState === null
                     ? "" : unitFileState)
  if (state === "") return ""
  var known = BOOT_LABELS[state]
  return known === undefined ? state : known
}

// Only enabled and disabled can be flipped. enable on a masked or static unit
// fails, and enabled-runtime has no unambiguous meaning for a click -- it
// would have to choose between making it permanent and clearing it. Those
// states show their label with no switch.
function bootIsToggleable(unitFileState) {
  var state = String(unitFileState === undefined || unitFileState === null
                     ? "" : unitFileState)
  return state === "enabled" || state === "disabled"
}
```

- [ ] **Step 4: Export the new function**

In `Model.js`'s returned object, the line `bootLabel: bootLabel,` already exists. Add the new export immediately after it:

```javascript
    bootLabel: bootLabel,
    bootIsToggleable: bootIsToggleable,
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `node --test tests/model.test.js 2>&1 | tail -12`
Expected: all pass.

- [ ] **Step 6: Run the whole suite**

Run: `./bin/test`
Expected: **121 Python + 27 JavaScript, 0 skips**, exit 0. JavaScript is up three from 24.

`BOOT_LABELS` is an object literal at the top level, which the ES5-subset guard permits — it is `var`, not `let`/`const`, and uses no forbidden syntax. If `ModelJsSyntaxTest` fails, read its failure message before changing anything: it names the construct it objected to.

- [ ] **Step 7: Commit**

```bash
git add Model.js tests/model.test.js
git commit -m "feat: boot state labels for every UnitFileState, and a toggleable predicate"
```

---

## Task 3: The boot branch, and its own clearing rule

**Files:**
- Modify: `Service.qml` — add a property near line 39, a branch in `runAction` at line 144, and clearing in three existing sites (lines 122-123, 231-236, 290-293)
- Test: none automated — QML, same limitation as Task 3

**Interfaces:**
- Consumes: `Model.optimisticStatusFor(verb)` returning `""` for both boot verbs, pinned by Task 2's test.
- Produces: `service.optimisticBootState` — `""`, `"enabled"`, or `"disabled"` — which Task 4's switch reads.

**The trap this task exists to not repeat.** `AGENTS.md` trap #19 records that `optimisticStatus` and `expectedStop` look like the same kind of bridge state but have **opposite failure costs**, and that giving them one shared clearing rule broke one of them. `optimisticBootState` is a third such value. Its failure cost: clearing early means the knob snaps back to its previous position for at most one poll — cheap, visible, self-correcting. Clearing late means the switch lies about system state. So it **fails safe toward reality** and clears on the first authoritative snapshot after the action completes, following `optimisticStatus` exactly and **not** `expectedStop`, which persists through a fixed six-tick ramp because its early-clear cost is a false critical alert.

- [ ] **Step 1: Add the property**

In `Service.qml`, immediately after line 39's `property string optimisticStatus: ""`, add:

```qml
  // "", "enabled", or "disabled". The boot switch's optimistic value, so the
  // knob throws on click instead of waiting a poll.
  //
  // This clears like optimisticStatus, NOT like expectedStop -- see trap #19.
  // Clearing early costs at most one poll of knob snap-back, so it fails safe
  // toward reality. expectedStop fails the other way, toward suppression,
  // because clearing it early fires a false "stopped unexpectedly" alert.
  // Do not unify these clearing rules "for consistency": that is the bug
  // trap #19 exists to prevent.
  property string optimisticBootState: ""
```

- [ ] **Step 2: Add the boot branch to runAction**

`runAction` currently begins at line 144. Its `expectedStop` and `optimisticStatus` lines are lines 148-155. Replace that span — from `if (verb === "stop" || verb === "restart") root.expectedStop = true` through the closing brace of the `if (optimistic !== "")` block — with:

```qml
    if (verb === "stop" || verb === "restart") root.expectedStop = true

    // Boot verbs touch no run state: enable does not start, disable does not
    // stop. They must not set expectedStop (nothing can stop, so the
    // suppression would be armed for an impossible event) and must not set
    // optimisticStatus (which holds a *run* status). They get their own value.
    if (verb === "enable" || verb === "disable") {
      root.optimisticBootState = verb === "enable" ? "enabled" : "disabled"
    }

    var optimistic = Model.optimisticStatusFor(verb)
    if (optimistic !== "") {
      root.optimisticStatus = optimistic
      root.statusSinceSec = Date.now() / 1000
    }
```

- [ ] **Step 3: Clear it on the first authoritative snapshot**

Three existing clearing sites gain one line each, in each case beside the `optimisticStatus` clear and never beside an `expectedStop`-only clear.

In `handleOutput`, lines 122-123 currently read:

```qml
    if (root.optimisticStatus !== "" && root.actionInProgress === "")
      root.optimisticStatus = ""
```

Replace with:

```qml
    if (root.optimisticStatus !== "" && root.actionInProgress === "")
      root.optimisticStatus = ""
    if (root.optimisticBootState !== "" && root.actionInProgress === "")
      root.optimisticBootState = ""
```

In `settleTimer`, lines 231-236 currently read:

```qml
      if (settleTimer.ticks >= 6) {
        settleTimer.running = false
        settleTimer.ticks = 0
        root.optimisticStatus = ""
        root.expectedStop = false
      }
```

Replace with:

```qml
      if (settleTimer.ticks >= 6) {
        settleTimer.running = false
        settleTimer.ticks = 0
        root.optimisticStatus = ""
        root.optimisticBootState = ""
        root.expectedStop = false
      }
```

In the process's `onRunningChanged` error path, lines 290-293 currently read:

```qml
      if (root.actionError !== "") {
        root.optimisticStatus = ""
        root.expectedStop = false
      }
```

Replace with:

```qml
      if (root.actionError !== "") {
        root.optimisticStatus = ""
        root.optimisticBootState = ""
        root.expectedStop = false
      }
```

That third site is what returns the knob to its original position when the user dismisses the authentication dialog.

- [ ] **Step 4: Confirm the file parses**

Run: `./bin/test`
Expected: **121 Python + 27 JavaScript, 0 skips**, exit 0, `== qml syntax ==` prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add Service.qml
git commit -m "feat: the boot branch, with its own clearing rule"
```

---

## Task 4: The switch

**Files:**
- Modify: `Panel.qml:211-222` (the boot `Text` and the comment above it)
- Test: none automated — `qmllint` parse gate only, for the reason below

**Interfaces:**
- Consumes: `Model.bootLabel(state)` and `Model.bootIsToggleable(state)` from Task 2; `service.runAction(verb, target, kind)` and `service.actionInProgress` which already exist; `service.optimisticBootState` from Task 3.
- Produces: nothing later tasks consume.

**Ordering note.** `service.optimisticBootState` already exists when this task runs — Task 3 created it along with its clearing rule. The original plan had these two tasks the other way round, which would have left this binding pointing at a property that did not exist yet; QML resolves properties at runtime, so that fails as a runtime binding warning rather than a parse error, and `qmllint` cannot see it either way. Swapped 2026-08-12 before execution. The dependency runs one way: Task 3 produces the property, this task consumes it.

**Why no automated test.** `qmllint` here cannot resolve `qs.Ui` at all, so it sees neither `ToggleSwitch` nor a mistyped property on it. It reports parse errors only — and per trap #15 it reports them as a bare exit 255 with no message. This gate proves the file parses, nothing more.

- [ ] **Step 1: Replace the boot line with a row carrying a switch**

In `Panel.qml`, replace lines 211-222 — the comment and the `Text` — entirely:

```qml
        // Boot state, and the switch that changes it. enable/disable go
        // through manage-unit-files, which systemd invokes with no `unit`
        // detail, so no polkit rule could ever scope it to this one unit --
        // which is why this was read-only until 2026-08-12. Colophon installs
        // no rule any more; it prompts. Prompted authorization has nothing to
        // scope, so the missing detail stopped mattering. See AGENTS.md #28.
        RowLayout {
          Layout.fillWidth: true
          Layout.leftMargin: Style.space(14)
          spacing: Style.space(6)
          visible: bootText.text !== "" && root.status !== "missing"

          Text {
            id: bootText
            text: Model.bootLabel(root.snap.unit ? root.snap.unit.unitFileState : "")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Item { Layout.fillWidth: true }

          ToggleSwitch {
            id: bootSwitch

            // Hidden for masked, static, enabled-runtime and anything else
            // systemd will not simply flip -- those states show their label
            // and offer no control.
            visible: Model.bootIsToggleable(
                       root.snap.unit ? root.snap.unit.unitFileState : "")

            // The optimistic value when one is set, reality otherwise: the
            // knob throws the instant it is clicked rather than waiting a
            // poll. ToggleSwitch's own docs describe this pattern.
            checked: service.optimisticBootState !== ""
                     ? service.optimisticBootState === "enabled"
                     : (root.snap.unit
                        ? root.snap.unit.unitFileState === "enabled"
                        : false)

            // Swallows further clicks while a verb is in flight without
            // dropping hover or tooltips on a background refresh.
            busy: service.actionInProgress !== ""

            foreground: root.fg

            onToggled: service.runAction(checked ? "disable" : "enable", "", "")

            // ToggleSwitch has no tooltipText property -- Button does, but this
            // is not a Button. PanelToolTip is the shell's drop-in for exactly
            // this: declare it inside the hovered item and bind `visible` to
            // the hover state. ToggleSwitch exposes `containsMouse` as a
            // readonly alias for that purpose.
            PanelToolTip {
              visible: bootSwitch.containsMouse
              text: "Start ollama.service at boot -- does not start it now"
            }
          }
        }
```

**On `onToggled`'s inverted-looking expression:** `checked` is the switch's *current* value at click time, so the verb is the opposite one. Reading `checked` after the click would depend on whether the component flips itself first — it does not, because it is stateless about the value by design. Do not "simplify" this to `checked ? "enable" : "disable"`.

- [ ] **Step 2: Re-confirm the upstream API before trusting this plan's code**

Run: `grep -n "property\|signal\|alias" /usr/share/omarchy/shell/Ui/ToggleSwitch.qml`

Verified on 2026-08-12, and the reason this step exists is that `/usr/share/omarchy/` is overwritten wholesale on `omarchy update` (trap #29): `checked`, `busy`, `interactive`, `foreground`, `accent` are properties; `toggled()` is a signal; `containsMouse` is a `readonly property alias`. There is **no** `tooltipText` — that belongs to `Button`, which this is not.

If any of those have changed since, stop and report rather than guessing at a replacement.

- [ ] **Step 3: Confirm the file still parses**

Run: `./bin/test`
Expected: **121 Python + 27 JavaScript, 0 skips**, exit 0, and the `== qml syntax ==` gate prints `ok`.

If `qmllint` exits 255 with no output, that is trap #15: a parse error with no message. Bisect by commenting out blocks of the block you just added, or run `qmlformat Panel.qml >/dev/null` which reports parse errors with an actual message where `qmllint` here does not.

- [ ] **Step 4: Commit**

```bash
git add Panel.qml
git commit -m "feat: a switch on the boot line"
```

---

## Task 5: Correct the record

**Files:**
- Modify: `README.md:112-131` ("Boot start") and line 229 (Troubleshooting), `AGENTS.md` trap #28
- Test: none — documentation

**Interfaces:** none.

- [ ] **Step 1: Invert the README's "Boot start" section**

`README.md:112-131` currently tells the reader the widget "cannot change it from the panel" and prescribes `sudo systemctl enable ollama.service`. Rewrite it so:

- the switch on the boot line is the instruction
- each flip raises the authentication dialog, once per flip, per trap #31
- enabling at boot does **not** start the service now, and disabling does not stop it — the start and stop buttons do that
- states other than enabled and disabled — `masked`, `static` — show their label with no switch, because systemd will not simply flip them
- the manual `sudo systemctl enable ollama.service` command **stays**, demoted to a footnote for anyone who prefers a terminal

This is user-facing documentation, so no dated note: just make it correct. Do not explain polkit subject scoping to a user.

- [ ] **Step 2: Delete the stale Troubleshooting line**

`README.md:229` reads:

```
- Boot state is reported, not settable, from the widget — see Boot start,
```

Delete that bullet, including its continuation line. Read the surrounding list first and confirm the remaining bullets still parse as a list.

- [ ] **Step 3: Date-stamp trap 28**

In `AGENTS.md`, trap #28's row already carries a `**It no longer blocks anything (2026-08-11):**` correction. Append one sentence recording that the follow-up landed on 2026-08-12 and pointing at `docs/superpowers/specs/2026-08-12-boot-toggle-design.md`. **Keep the trap** — it is still a true polkit/systemd fact and still what anyone writing a rule for this unit needs to know. Do not renumber it or any other trap.

- [ ] **Step 4: Confirm nothing still says the boot state is read-only**

Run:

```bash
grep -rni "not settable\|cannot change it\|one-time\|read-only" README.md AGENTS.md | grep -vi "trap"
```

Judge every hit. A hit that describes the boot state as unchangeable is a defect. A hit about something else — the API base, the model list — is fine. Report each with a one-line verdict.

- [ ] **Step 5: Run the suite and commit**

Run: `./bin/test`
Expected: **121 Python + 27 JavaScript, 0 skips**, exit 0. `bin/test` lints the manifest and shell scripts, so documentation edits can still break it.

```bash
git add README.md AGENTS.md
git commit -m "docs: the boot toggle landed"
```

---

## Task 6: Verify on the machine

**Files:** none — this task changes nothing.

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: the only evidence the switch works. Nothing in this repository can raise a dialog or read a fingerprint.

**This task is for the owner, not an agent.** It enables and disables the real unit and requires someone watching the screen. **An implementer must not run it.** Each flip raises an authentication dialog per trap #31.

Record the starting boot state before you begin, so you can put it back.

- [ ] **Step 1: Deploy**

```bash
cd ~/Src/colophon && ./bin/install && omarchy restart shell
```

- [ ] **Step 2: The switch flips and prompts**

Open the panel. The boot line should read `enabled at boot` or `disabled at boot` with a switch beside it, positioned to match. Click it.

Expect: the knob throws immediately — before any dialog resolves — then Omarchy's authentication dialog appears offering fingerprint. Authenticate. The knob stays in its new position, and within one poll the label updates to match.

- [ ] **Step 3: A dismissed dialog returns the knob**

Click the switch again, then dismiss the dialog without authenticating.

Expect: the knob throws, then returns to its original position, and the error strip reads `not authorized — the authentication prompt was dismissed or denied`. The switch becomes clickable again rather than staying inert.

- [ ] **Step 4: A masked unit shows state and no switch**

```bash
sudo systemctl mask ollama.service
```

Expect: the boot line reads `masked` with **no switch** beside it. Then restore:

```bash
sudo systemctl unmask ollama.service
```

Expect the line and switch to come back within one poll.

- [ ] **Step 5: Put the boot state back and report**

Return the unit to whatever state step 2 started from, then record the outcome of each step in the spec's Testing section. **Do not mark anything verified that was not observed on screen** — the 2026-08-11 spec recorded a hand-verification claim that was false and had to be corrected.

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `enable`/`disable` verbs in the action script | 1 |
| `BOOT_VERBS` + `SYSTEMCTL_VERBS`, guard iterates the latter | 1 |
| `bootLabel` extended with the exact state table | 2 |
| `bootIsToggleable`, true for exactly two states | 2 |
| Unknown states render raw, never hidden | 2 |
| `optimisticStatusFor` returns `""` for boot verbs | 2 (assertion), 3 (relied on) |
| Bare `ToggleSwitch` beside the untouched caption | 4 |
| Switch hidden for non-toggleable states | 4 |
| `busy` bound to `actionInProgress` | 4 |
| Tooltip carrying the boot/run distinction | 4 |
| Stale `Panel.qml` comment deleted | 4 |
| `optimisticBootState` with its own clearing rule | 3 |
| No `expectedStop`, no `optimisticStatus` for boot verbs | 3 |
| Dismissed dialog returns the knob | 3 (step 3), 6 (verified) |
| README inverted, Troubleshooting line deleted | 5 |
| Trap 28 dated note | 5 |
| Three by-hand checks | 6 |
| No test enables or disables the unit | Global constraint; 1 asserts via `--dry-run` only |

No gaps.

**Placeholder scan:** clean — every code step carries the actual code, and the two "judge every hit" steps name the judgement criterion rather than deferring it.

**Type consistency:** `optimisticBootState` is `""` / `"enabled"` / `"disabled"` in Task 3 and read as `service.optimisticBootState === "enabled"` in Task 4 — consistent. `bootIsToggleable` and `bootLabel` take the same single `unitFileState` argument in Tasks 2 and 4. `SYSTEMCTL_VERBS` is defined in Task 1 step 3 and consumed by Task 1 step 1's assertion — the test is written first and fails on the missing attribute, which is the intended red phase.

**Test counts:** 120 → 121 Python (Task 1 adds one) → 27 JavaScript (Task 2 adds three). Every task after Task 2 expects 121 + 27.
