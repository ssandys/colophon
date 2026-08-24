# Per-Model Parameter Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Amended 2026-08-24 — this plan is a historical record, not current truth.**
> Tasks 1-6 executed as written. The owner then saw the editor running and
> narrowed it from four parameters to two (`num_ctx`, `temperature`), added a
> range placeholder and a visible caption per parameter, and asked for
> inapplicable parameters to be hidden by model kind. That work is **Task 6b**,
> which has no entry below; its requirements live in
> `.superpowers/sdd/2026-08-23-model-parameter-editor/task-6b-brief.md` and the
> reasoning is in the spec's `Amendment 2026-08-24` section. Wherever this plan
> says "four parameters", "top_p" or "top_k" below, it is describing what was
> built and then deliberately narrowed — read the spec amendment first.

**Goal:** Open an installed model in the panel, see the parameters it actually carries, edit them, and write them back with one explicit apply.

**Architecture:** Reading needs no new I/O — parameters already live on disk in an `application/vnd.ollama.image.params` manifest layer, so `scan_installed` reads one more blob and each entry gains a `parameters` object that rides the existing snapshot. Writing is one new verb in `colophon_action.py` posting to `POST /api/create` with inline parameters, which is the same `post_json` shape `warm` and `unload` already use. The panel expands a model row in place to show click-to-type fields and an apply.

**Tech Stack:** Python 3 stdlib, ES5-subset JavaScript, QML (Quickshell), Ollama HTTP API.

**Spec:** `docs/superpowers/specs/2026-08-23-model-parameter-editor-design.md`. Read it first — it carries the measured evidence for every claim below, including why the write goes through the API rather than the `ollama` CLI.

## Global Constraints

- **Python is stdlib-only, no pip ever.** Permitted: `datetime`, `glob`, `http.client`, `json`, `os`, `re`, `shlex`, `shutil`, `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`.
- **`Model.js` is ES5-subset and dual-engine.** No arrow functions, spread, template literals, `let`/`const`, `Object.assign`, `.includes(`, `.endsWith(`. Top level is `var`/`function` only. `ModelJsSyntaxTest` enforces it; test files are exempt.
- **`Model.js` is a pure presentation layer.** No state between calls, no I/O, no `Date.now()`.
- **`transient`, `volatile`, `synchronized`, `native`, `throws`, `goto`, `implements`** are reserved in QML's JS grammar. `qmllint` here reports every parse error as a bare exit 255 with **no message**.
- **Never write a literal Unicode Private Use Area character** anywhere, including commit messages. The one glyph lives in `Model.BAR_GLYPH` as a `\uXXXX` escape.
- The unit name is the fixed literal `ollama.service`.
- Never edit `/usr/share/omarchy/` — but reading it is expected.
- **Standing safety rule, widened by this plan:** no test may start, stop, restart, enable or disable `ollama.service`, and **none may create, overwrite, pull or delete a model**. Every privileged verb is asserted through `--dry-run` only. Task 8's by-hand checks are the deliberate exception.
- The four parameters are exactly `num_ctx`, `temperature`, `top_p`, `top_k`. No others.
- Baseline before you start: **150 Python + 29 JavaScript tests, 0 skips.**

## File Structure

| File | Change |
|---|---|
| `scripts/colophon_collect.py` | `scan_installed` reads the params layer; each entry gains `parameters` |
| `tests/test_collect.py` | params reading, absent layer, unreadable blob, filtering |
| `Model.js` | `PARAM_SPECS`, `paramValue`, `formatParamValue`, `parseParamInput`, `paramIsDirty` |
| `tests/model.test.js` | the above |
| `scripts/colophon_action.py` | `PARAM_VERBS`, bounds validation, `create_body`, `set-params` |
| `tests/test_action.py` | argv, bounds, body shape, dry-run |
| `Service.qml` | `paramEdits`, `commitParams`, clearing rule |
| `Panel.qml` | expanding row, four fields, apply |
| `tests/test_cross_language.py` | `ParamSpecTest` pinning names and bounds across JS, Python and `Panel.qml` |
| `README.md` | a panel-usage bullet |
| `AGENTS.md` | widened safety rule, new trap |

---

## Task 1: The collector reads parameters off disk

**Files:**
- Modify: `scripts/colophon_collect.py` — `scan_installed`, around lines 246-310
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: nothing.
- Produces: every entry in the snapshot's `installed` list gains `"parameters"`, a dict containing only keys from `num_ctx`, `temperature`, `top_p`, `top_k` that the model actually declares. A model declaring none gets `{}`. Never `None`.

**Why this needs no API.** Ollama stores parameters as a manifest layer with `mediaType: "application/vnd.ollama.image.params"` whose blob is plain JSON — verified on this machine: `nomic-embed-text` carries `{"num_ctx":8192}` and `gemma3:4b` carries `{"stop":["<end_of_turn>"],"temperature":1,"top_k":64,"top_p":0.95}`. `scan_installed` already reads the config blob the same way, so this is one more `_read_json`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_collect.py`, inside the existing `ScanInstalledTest` class:

```python
    def test_reads_the_four_parameters_from_the_params_layer(self):
        # Ollama stores parameters as their own manifest layer, blob = plain
        # JSON. Verified on the target machine: nomic-embed-text carries
        # {"num_ctx":8192}. Only the four the editor owns are surfaced; a model
        # declaring `stop` alone reports {} rather than leaking a list the panel
        # has no idiom for.
        root = self.make_store({
            "params": {"num_ctx": 8192, "temperature": 0.6,
                       "top_p": 0.95, "top_k": 40,
                       "stop": ["<end>"], "mirostat": 2}})
        entries, _ = collect.scan_installed(root)
        self.assertEqual(entries[0]["parameters"],
                         {"num_ctx": 8192, "temperature": 0.6,
                          "top_p": 0.95, "top_k": 40})

    def test_a_model_with_no_params_layer_reports_an_empty_dict(self):
        # Not None: Model.js and Panel.qml both index this, and a null would
        # make every consumer guard for it.
        root = self.make_store({})
        entries, _ = collect.scan_installed(root)
        self.assertEqual(entries[0]["parameters"], {})

    def test_an_unreadable_params_blob_costs_that_model_only(self):
        # Same principle as the config blob above it: a corrupted manifest that
        # still parses must cost one model's parameters, not the inventory.
        root = self.make_store({"params_raw": "{not json"})
        entries, _ = collect.scan_installed(root)
        self.assertEqual(entries[0]["parameters"], {})
        self.assertEqual(entries[0]["name"], "library/testmodel:latest")
```

`ScanInstalledTest` already has a helper that builds a fake store on disk. **Read it before writing these** — if it is not named `make_store` or does not accept a spec dict, adapt these three tests to the helper that exists rather than adding a second one. Extend it to write a params layer and blob; do not duplicate it.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest tests.test_collect -v 2>&1 | tail -20`
Expected: FAIL — three failures, each `KeyError: 'parameters'`, because entries carry no such key yet.

- [ ] **Step 3: Read the params layer**

In `scripts/colophon_collect.py`, add a module-level constant near the other literals:

```python
# The four parameters the panel's editor owns. Ollama stores every parameter in
# one layer, so the filter is here rather than in the reader: a `stop` list or a
# `mirostat` int must not reach a panel that has no idiom for them.
EDITABLE_PARAMS = ("num_ctx", "temperature", "top_p", "top_k")
PARAMS_MEDIA_TYPE = "application/vnd.ollama.image.params"
```

Then inside `scan_installed`, after the existing `blob = _read_json(...)` / `family = ...` lines and before the `try: modified = ...` block:

```python
        parameters = {}
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            if layer.get("mediaType") != PARAMS_MEDIA_TYPE:
                continue
            raw = _read_json(os.path.join(
                root, "blobs", str(layer.get("digest", "")).replace(":", "-")))
            if not isinstance(raw, dict):
                continue
            for key in EDITABLE_PARAMS:
                if key in raw and isinstance(raw[key], (int, float)):
                    parameters[key] = raw[key]
```

and add to the `entries.append({...})` dict, after `"kind"`:

```python
            "parameters": parameters,
```

The `isinstance(raw[key], (int, float))` guard matters: all four are numeric, and a string where a number belongs would reach the panel's field and the action script's bounds check as the wrong type. Note `bool` is a subclass of `int` in Python — a `true` would pass this guard. That is acceptable here because Ollama never writes a boolean for these four, and the action script validates on the way out, which is the surface that writes.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `python3 -m unittest tests.test_collect -v 2>&1 | tail -8`
Expected: OK.

- [ ] **Step 5: Confirm against the real store, read-only**

Run:

```bash
python3 scripts/colophon_collect.py | python3 -c "import json,sys; [print('  %-28s %s' % (m['name'], m['parameters'])) for m in json.load(sys.stdin)['installed']]"
```

Expected: every installed model listed with its four-key-filtered parameters. On the target machine `nomic-embed-text:latest` shows `{'num_ctx': 8192}` and `gemma3:4b` shows `{'temperature': 1, 'top_k': 64, 'top_p': 0.95}`. Reading the store is unprivileged and touches nothing.

- [ ] **Step 6: Run the whole suite**

Run: `./bin/test`
Expected: **153 Python + 29 JavaScript, 0 skips**, exit 0. Python up three.

- [ ] **Step 7: Commit**

```bash
git add scripts/colophon_collect.py tests/test_collect.py
git commit -m "feat: the collector reads model parameters off disk"
```

---

## Task 2: Model.js parameter metadata and formatting

**Files:**
- Modify: `Model.js` — new constants and functions, plus the `module.exports` block
- Test: `tests/model.test.js`

**Interfaces:**
- Consumes: the `parameters` object Task 1 puts on each installed entry.
- Produces, all exported:
  - `Model.PARAM_SPECS` — an array of four objects, each `{key, label, min, max, step, decimals}`, in display order `num_ctx`, `temperature`, `top_p`, `top_k`.
  - `Model.paramValue(entry, key)` → the model's declared number, or `null` when absent.
  - `Model.formatParamValue(key, value)` → display string; `""` for `null`.
  - `Model.parseParamInput(key, text)` → a clamped number, or `NaN` when the text is not a valid value for that key.
  - `Model.paramIsDirty(entry, key, text)` → bool.

`Panel.qml` binds field text to `formatParamValue`, validates on edit with `parseParamInput`, and enables apply when any `paramIsDirty`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/model.test.js`. It requires the module once at the top as `Model` and calls `Model.fn(...)` directly — there is no per-test loader:

```javascript
test("PARAM_SPECS covers exactly the four editable parameters, in order", () => {
  assert.deepEqual(Model.PARAM_SPECS.map(s => s.key),
                   ["num_ctx", "temperature", "top_p", "top_k"])
  for (const spec of Model.PARAM_SPECS) {
    assert.ok(spec.label.length > 0, spec.key)
    assert.ok(spec.max > spec.min, spec.key)
    assert.equal(typeof spec.decimals, "number", spec.key)
  }
})

test("paramValue reads a declared parameter and reports absence as null", () => {
  const entry = { name: "m", parameters: { num_ctx: 8192, temperature: 0.6 } }
  assert.equal(Model.paramValue(entry, "num_ctx"), 8192)
  assert.equal(Model.paramValue(entry, "temperature"), 0.6)
  // Absent is null, never 0 -- a field showing 0 would claim the model
  // declares a value it does not.
  assert.equal(Model.paramValue(entry, "top_p"), null)
  assert.equal(Model.paramValue({ name: "m", parameters: {} }, "top_k"), null)
  assert.equal(Model.paramValue({ name: "m" }, "top_k"), null)
  assert.equal(Model.paramValue(null, "top_k"), null)
})

test("formatParamValue renders integers and decimals per spec", () => {
  assert.equal(Model.formatParamValue("num_ctx", 8192), "8192")
  assert.equal(Model.formatParamValue("top_k", 40), "40")
  assert.equal(Model.formatParamValue("temperature", 0.6), "0.6")
  assert.equal(Model.formatParamValue("top_p", 0.95), "0.95")
  // An absent value renders empty, so the field reads as "not set" rather than
  // as a number the model does not declare.
  assert.equal(Model.formatParamValue("num_ctx", null), "")
  assert.equal(Model.formatParamValue("num_ctx", undefined), "")
})

test("parseParamInput clamps in range and rejects nonsense", () => {
  assert.equal(Model.parseParamInput("num_ctx", "16384"), 16384)
  assert.equal(Model.parseParamInput("temperature", "0.42"), 0.42)
  // Clamped, not rejected: a typed 999999 is a clear intent to go high.
  assert.equal(Model.parseParamInput("num_ctx", "999999"), 131072)
  assert.equal(Model.parseParamInput("num_ctx", "1"), 4096)
  assert.equal(Model.parseParamInput("temperature", "-3"), 0)
  // num_ctx and top_k are integers; a typed decimal truncates rather than
  // reaching the API as a float it would reject.
  assert.equal(Model.parseParamInput("num_ctx", "8192.7"), 8192)
  assert.equal(Model.parseParamInput("top_k", "40.9"), 40)
  // Garbage is NaN so the caller can revert the field.
  assert.ok(Number.isNaN(Model.parseParamInput("num_ctx", "banana")))
  assert.ok(Number.isNaN(Model.parseParamInput("num_ctx", "")))
  assert.ok(Number.isNaN(Model.parseParamInput("num_ctx", "   ")))
  assert.ok(Number.isNaN(Model.parseParamInput("nope", "1")))
})

test("paramIsDirty compares typed text against the model's declared value", () => {
  const entry = { name: "m", parameters: { num_ctx: 8192 } }
  assert.equal(Model.paramIsDirty(entry, "num_ctx", "8192"), false)
  assert.equal(Model.paramIsDirty(entry, "num_ctx", "16384"), true)
  // Setting a value the model does not declare is a change.
  assert.equal(Model.paramIsDirty(entry, "top_k", "40"), true)
  // Leaving an undeclared field blank is not.
  assert.equal(Model.paramIsDirty(entry, "top_k", ""), false)
  // Garbage is not a change -- the field will revert, so apply must not light
  // up for a value that can never be sent.
  assert.equal(Model.paramIsDirty(entry, "num_ctx", "banana"), false)
})
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `node --test tests/model.test.js 2>&1 | tail -20`
Expected: FAIL — `Model.PARAM_SPECS` is `undefined`, so the first test throws on `.map`, and the rest fail on `Model.paramValue is not a function`.

- [ ] **Step 3: Add the constants and functions**

In `Model.js`, after the `BOOT_LABELS` block and its two functions:

```javascript
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
    step: 1, decimals: 0 }
]

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
```

The truncation deliberately avoids `Math.trunc`. `ModelJsSyntaxTest`'s banned list is a regex over eight specific constructs — `=>`, `let`, `const`, `...`, backticks, `Object.assign`, `.includes(`, `.endsWith(` — so it would pass `Math.trunc` regardless of whether the QML engine accepts it, and no test in this repository exercises that engine. The `Math.floor`/`Math.ceil` form removes the question.

- [ ] **Step 4: Export the four public functions**

In `Model.js`'s `module.exports` block, after `bootIsToggleable: bootIsToggleable,`:

```javascript
    PARAM_SPECS: PARAM_SPECS,
    paramValue: paramValue,
    formatParamValue: formatParamValue,
    parseParamInput: parseParamInput,
    paramIsDirty: paramIsDirty,
```

Do **not** export `paramSpec`. It is an internal lookup and widening the public surface for it buys nothing.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `node --test tests/model.test.js 2>&1 | tail -10`
Expected: all pass.

- [ ] **Step 6: Run the whole suite**

Run: `./bin/test`
Expected: **153 Python + 34 JavaScript, 0 skips**, exit 0. JavaScript up five.

If `ModelJsSyntaxTest` fails, read its message before changing anything — it names the construct it objected to. Its banned list is `=>`, `let`, `const`, `...`, backticks, `Object.assign`, `.includes(` and `.endsWith(`; nothing in the code above uses any of them, so a failure here means you introduced one, not that the plan did.

- [ ] **Step 7: Commit**

```bash
git add Model.js tests/model.test.js
git commit -m "feat: parameter specs, parsing and formatting in Model.js"
```

---

## Task 3: The action script writes parameters

**Files:**
- Modify: `scripts/colophon_action.py` — verb tuples near line 32, `plan()`, `execute()`, `main()`'s argument loop and validation
- Test: `tests/test_action.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. Bounds are duplicated here deliberately — this is the surface that writes, and Task 6's guard asserts they match `Model.js`.
- Produces: `set-params <model> --param KEY=VALUE [--param KEY=VALUE ...]`. `PARAM_VERBS = ("set-params",)`, `PARAM_BOUNDS` as a dict of `key -> (min, max, is_int)`, and `create_body(model, params) -> dict`. `plan()` returns one line per verb; `--dry-run` prints it and exits 0.

**Why the API and not the `ollama` CLI.** `POST /api/create` accepts parameters inline — verified: `{"model":X,"from":X,"parameters":{...}}` returns `{"status":"success"}` and is additive. That means no temp Modelfile, no `/tmp` path to be symlinked, no `ollama` binary on `PATH`, and no mismatch between the host enumerated and the host written to. It is the same `post_json` shape `warm` already uses.

- [ ] **Step 1: Write the failing tests**

Add a new class to `tests/test_action.py`:

```python
class SetParamsTest(unittest.TestCase):
    def test_the_body_names_the_model_as_its_own_base(self):
        # from == model is how Ollama re-stamps a definition in place. Verified
        # additive on the target machine: template, system message, stop
        # sequences and an existing temperature all survive.
        body = action.create_body("llama3.2:3b", {"num_ctx": 16384})
        self.assertEqual(body["model"], "llama3.2:3b")
        self.assertEqual(body["from"], "llama3.2:3b")
        self.assertEqual(body["parameters"], {"num_ctx": 16384})

    def test_every_parameter_has_bounds_and_a_type(self):
        self.assertEqual(sorted(action.PARAM_BOUNDS),
                         ["num_ctx", "temperature", "top_k", "top_p"])
        for key, (low, high, is_int) in action.PARAM_BOUNDS.items():
            self.assertLess(low, high, key)
            self.assertIsInstance(is_int, bool, key)

    def test_a_value_out_of_range_is_refused(self):
        for args in (["set-params", "llama3.2:3b", "--param", "num_ctx=1"],
                     ["set-params", "llama3.2:3b", "--param", "num_ctx=999999"],
                     ["set-params", "llama3.2:3b", "--param", "temperature=9"],
                     ["set-params", "llama3.2:3b", "--param", "top_p=2"],
                     ["set-params", "llama3.2:3b", "--param", "top_k=0"]):
            with self.subTest(args=args):
                result = run(args + ["--dry-run"])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("must be between", result.stderr)

    def test_an_unknown_parameter_is_refused(self):
        # The editor owns four keys. Accepting a fifth here would let the write
        # surface drift from the panel and from Model.PARAM_SPECS.
        result = run(["set-params", "llama3.2:3b",
                      "--param", "mirostat=2", "--dry-run"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unknown parameter", result.stderr)

    def test_a_malformed_param_argument_is_refused(self):
        for bad in ("num_ctx", "num_ctx=", "=8192", "num_ctx=banana"):
            with self.subTest(bad=bad):
                result = run(["set-params", "llama3.2:3b",
                              "--param", bad, "--dry-run"])
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_an_integer_parameter_refuses_a_decimal(self):
        # Model.js truncates before it gets here; if a decimal still arrives it
        # is a bug upstream, and silently rounding would hide it.
        result = run(["set-params", "llama3.2:3b",
                      "--param", "num_ctx=8192.5", "--dry-run"])
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_a_suspicious_model_name_is_refused(self):
        result = run(["set-params", "../../etc/passwd\n",
                      "--param", "num_ctx=8192", "--dry-run"])
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_dry_run_prints_the_create_and_touches_nothing(self):
        result = run(["set-params", "llama3.2:3b", "--param", "num_ctx=16384",
                      "--param", "temperature=0.42", "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/api/create", result.stdout)
        self.assertIn("num_ctx", result.stdout)
        self.assertIn("16384", result.stdout)
        self.assertIn("temperature", result.stdout)

    def test_set_params_requires_at_least_one_param(self):
        result = run(["set-params", "llama3.2:3b", "--dry-run"])
        self.assertEqual(result.returncode, 2, result.stderr)
```

`run(...)` is the existing helper in this file that invokes the script as a subprocess. **Read it first** and match its signature; do not add a second one.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest tests.test_action -v 2>&1 | tail -25`
Expected: FAIL. `test_the_body_names_the_model_as_its_own_base` and `test_every_parameter_has_bounds_and_a_type` fail with `AttributeError` on `create_body` / `PARAM_BOUNDS`. The rest fail because `set-params` is an unknown verb, so the script exits 2 — which some of them expect for the *wrong reason*. That is fine for the red phase; step 4's green run is what proves the reasons are right.

- [ ] **Step 3: Add the verb, bounds and body builder**

In `scripts/colophon_action.py`, extend the verb tuples (leave `SYSTEMCTL_VERBS` exactly as it is — `set-params` does not shell out to systemctl):

```python
MODEL_VERBS = ("warm", "unload")
PARAM_VERBS = ("set-params",)

# key -> (min, max, is_int). Mirrored in Model.js's PARAM_SPECS; this is the
# only surface that writes, and tests/test_cross_language.py asserts the two
# agree along with Panel.qml. See AGENTS.md trap #12.
PARAM_BOUNDS = {
    "num_ctx": (4096, 131072, True),
    "temperature": (0.0, 2.0, False),
    "top_p": (0.0, 1.0, False),
    "top_k": (1, 200, True),
}
```

Add the body builder next to `load_body`:

```python
def create_body(model, params):
    """The POST /api/create body that re-stamps `model` in place.

    `from` is the model's own name: that is how Ollama re-stamps a definition,
    and the create is additive -- template, system message and existing
    parameters all survive, verified on the target machine. It is metadata-only,
    so it does not scale with model size (45ms on an 18.2 GB model).
    """
    return {"model": model, "from": model, "parameters": dict(params)}
```

- [ ] **Step 4: Parse and validate `--param`**

In `main()`'s argument loop, beside the existing `--keep-alive` branch:

```python
        elif arg == "--param" and args:
            raw = args.pop(0)
            if "=" not in raw:
                sys.stderr.write(
                    "colophon_action: --param needs KEY=VALUE, got '"
                    + raw + "'\n")
                return 2
            key, _, value_text = raw.partition("=")
            if key not in PARAM_BOUNDS:
                sys.stderr.write(
                    "colophon_action: unknown parameter '" + key + "'\n")
                return 2
            low, high, is_int = PARAM_BOUNDS[key]
            try:
                value = int(value_text) if is_int else float(value_text)
            except ValueError:
                sys.stderr.write(
                    "colophon_action: " + key + " must be "
                    + ("an integer" if is_int else "a number")
                    + ", got '" + value_text + "'\n")
                return 2
            if value < low or value > high:
                sys.stderr.write(
                    "colophon_action: " + key + " must be between "
                    + str(low) + " and " + str(high) + "\n")
                return 2
            params[key] = value
```

Declare `params = {}` beside the other defaults before the loop. Then in the validation block, extend the accepted-verb check and require at least one param:

```python
    if verb not in SYSTEMCTL_VERBS + MODEL_VERBS + PARAM_VERBS:
        sys.stderr.write("colophon_action: unknown verb '" + verb + "'\n")
        return 2
    if verb in PARAM_VERBS and not params:
        sys.stderr.write(
            "colophon_action: set-params needs at least one --param\n")
        return 2
```

`set-params` takes a model target, so it must reach the existing `MODEL_RE.match(target)` check the model verbs already use — confirm by reading that block that `set-params` is covered, and widen its condition if it names `MODEL_VERBS` explicitly. `MODEL_RE` uses `\Z`, not `$`, per trap 26; do not "simplify" it.

- [ ] **Step 5: Route the verb through plan and execute**

In `plan()`, before the model-verb path:

```python
    if verb in PARAM_VERBS:
        return ["POST " + str(api_base).rstrip("/") + "/api/create "
                + json.dumps(create_body(target, params), sort_keys=True)]
```

`plan()` will need `params` in its signature. Add it as a keyword argument with a `None` default that becomes `{}`, so existing callers and their tests keep working unchanged — there are several, and changing them all is churn this task does not need.

In `execute()`, after the `SYSTEMCTL_VERBS` branch:

```python
    if verb in PARAM_VERBS:
        return post_json(str(api_base).rstrip("/") + "/api/create",
                         create_body(target, params))
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `python3 -m unittest tests.test_action -v 2>&1 | tail -12`
Expected: OK. Read the output for the five refusal tests specifically and confirm each now fails for its own stated reason — an out-of-range value reporting "unknown verb" would mean the verb never registered.

- [ ] **Step 7: Confirm the dry-run by hand**

Run:

```bash
python3 scripts/colophon_action.py set-params llama3.2:3b --param num_ctx=16384 --param temperature=0.42 --dry-run
```

Expected, one line:

```
POST http://127.0.0.1:11434/api/create {"from": "llama3.2:3b", "model": "llama3.2:3b", "parameters": {"num_ctx": 16384, "temperature": 0.42}}
```

**Never run `set-params` without `--dry-run`.** It would rewrite a real model's definition on the owner's machine.

- [ ] **Step 8: Run the whole suite**

Run: `./bin/test`
Expected: **162 Python + 34 JavaScript, 0 skips**, exit 0. Python up nine.

- [ ] **Step 9: Commit**

```bash
git add scripts/colophon_action.py tests/test_action.py
git commit -m "feat: set-params writes model parameters through the API"
```

---

## Task 4: Service.qml holds the edits

**Files:**
- Modify: `Service.qml` — a new property near `optimisticBootState`, a branch in `runAction`, clearing beside the existing clears
- Test: none automated — QML, see the note below

**Interfaces:**
- Consumes: `Model.paramIsDirty`, `Model.parseParamInput` from Task 2; `set-params` from Task 3.
- Produces: `service.paramEdits` — a plain object keyed `"<model>|<param>" -> typed text`; `service.paramDirty(entry)` → bool; `service.setParamEdit(model, key, text)`; `service.commitParams(entry)` which builds the argv and calls the existing action path.

**Why no automated test.** `qmllint` here cannot resolve `qs.Ui` at all, and per trap 15 it reports parse errors as a bare exit 255 with no message. The QML gate proves the file parses, nothing more. Task 8's by-hand checks are the verification.

**The clearing rule, which is where this project has been bitten three times.** `paramEdits` is a fourth piece of bridge state alongside `optimisticStatus`, `expectedStop` and `optimisticBootState`. Trap 19 records that giving two of them one shared clearing rule broke one. State this one's failure cost explicitly:

- Clearing `paramEdits` **too early** discards what the user typed. Expensive and infuriating — typing is not recoverable by waiting.
- Clearing it **too late** leaves a field showing a value the model no longer has. Cheap: one poll of a stale number in a field nobody is looking at.

So it fails safe toward **keeping** the edit. It clears only for the model that was just applied, only on success, and never on a poll. This is the opposite of `optimisticBootState`, which fails toward reality — and that difference is the point.

- [ ] **Step 1: Add the property**

In `Service.qml`, after `property string optimisticBootState: ""`:

```qml
  // Typed-but-unapplied parameter edits, keyed "<model>|<param>". A plain
  // object, not a ListModel: it is read by binding and never iterated in QML.
  //
  // Clears differently from every other bridge state here, deliberately. See
  // AGENTS.md trap #19: optimisticStatus and optimisticBootState fail safe
  // toward reality because a wrong value costs a flicker. This one fails safe
  // toward KEEPING the edit, because clearing early discards typing the user
  // cannot get back by waiting. It is never cleared by a poll -- only by a
  // successful apply, and then only for that model.
  property var paramEdits: ({})
```

- [ ] **Step 2: Add the edit accessors**

```qml
  function paramEditKey(model, key) { return String(model) + "|" + String(key) }

  function paramEditText(entry, key) {
    if (!entry) return ""
    var k = root.paramEditKey(entry.name, key)
    if (root.paramEdits.hasOwnProperty(k)) return root.paramEdits[k]
    return Model.formatParamValue(key, Model.paramValue(entry, key))
  }

  function setParamEdit(model, key, text) {
    // Reassign rather than mutate: QML property-change notification on a var
    // does not fire for an in-place key write, so bindings would go stale.
    var next = {}
    for (var existing in root.paramEdits) next[existing] = root.paramEdits[existing]
    next[root.paramEditKey(model, key)] = String(text)
    root.paramEdits = next
  }

  function paramDirty(entry) {
    if (!entry) return false
    for (var i = 0; i < Model.PARAM_SPECS.length; i++) {
      var key = Model.PARAM_SPECS[i].key
      if (Model.paramIsDirty(entry, key, root.paramEditText(entry, key)))
        return true
    }
    return false
  }
```

The reassign-not-mutate comment is load-bearing: assigning into a `var` object in place does not notify, and every field bound to `paramEditText` would silently stop updating.

- [ ] **Step 3: Add the commit**

```qml
  function commitParams(entry) {
    if (!entry || root.actionInProgress !== "") return
    var args = []
    for (var i = 0; i < Model.PARAM_SPECS.length; i++) {
      var key = Model.PARAM_SPECS[i].key
      var text = root.paramEditText(entry, key)
      if (!Model.paramIsDirty(entry, key, text)) continue
      var value = Model.parseParamInput(key, text)
      if (isNaN(value)) continue
      args.push("--param")
      args.push(key + "=" + value)
    }
    if (args.length === 0) return
    root.pendingParamModel = entry.name
    root.runAction("set-params", entry.name, "", args)
  }
```

`runAction` currently takes `(verb, target, kind)`. Add a fourth optional parameter `extraArgs` defaulting to `undefined`, and push its members onto the argv it builds — after the existing `--api-base` push, so a malformed extra cannot displace a required flag. Also add `property string pendingParamModel: ""` beside `paramEdits`.

- [ ] **Step 4: Clear on success only**

`set-params` changes no unit state, so it must not set `expectedStop` or `optimisticStatus` — `Model.optimisticStatusFor` already returns `""` for any unrecognised verb, so nothing is needed there. Confirm by reading it rather than assuming.

In the process's `onRunningChanged`, inside the existing block that runs on exit, after `root.actionInProgress = ""`:

```qml
      // Only on success, and only for the model that was applied. A failed
      // apply keeps the edits so the user can correct and retry rather than
      // retyping.
      if (root.pendingParamModel !== "" && root.actionError === "") {
        var next = {}
        var prefix = root.pendingParamModel + "|"
        for (var k in root.paramEdits)
          if (k.indexOf(prefix) !== 0) next[k] = root.paramEdits[k]
        root.paramEdits = next
      }
      root.pendingParamModel = ""
```

Place this **before** the existing `settleTimer` restart lines, and leave those alone: the ramp is harmless here and suppressing it is a separate change this task should not smuggle in.

- [ ] **Step 5: Confirm the file parses**

Run: `./bin/test`
Expected: **162 Python + 34 JavaScript, 0 skips**, exit 0, and the `== qml syntax ==` gate prints `ok`.

If `qmllint` exits 255 with no output, that is trap 15. Run `qmlformat Service.qml >/dev/null`, which reports parse errors with an actual message.

- [ ] **Step 6: Commit**

```bash
git add Service.qml
git commit -m "feat: hold and commit parameter edits in Service.qml"
```

---

## Task 5: Panel.qml expands the row

**Files:**
- Modify: `Panel.qml` — the installed-model `Repeater` delegate, around lines 663-720
- Test: none automated — same QML limitation as Task 4

**Interfaces:**
- Consumes: `Model.PARAM_SPECS`, `Model.formatParamValue`, `Model.parseParamInput` from Task 2; `service.paramEditText`, `service.setParamEdit`, `service.paramDirty`, `service.commitParams` from Task 4.
- Produces: nothing later tasks consume.

**Three constraints from the spec, each with a reason this project learned the hard way.**

**1. The key catcher must be blocked while a field has focus.** `PanelKeyCatcher` declares `Keys.priority: Keys.BeforeItem` and swallows `k`, `j`, `h`, `l`, Enter and Escape. Its own header says "the panel must set `blocked: editor.activeFocus`". Three first-party panels do (`network:996`, `clock:250`, `weather:501`). Omitting it is what made PR #6's `k` shorthand work only in uppercase.

Add to the existing `PanelKeyCatcher`:

```qml
      blocked: root.paramFieldFocused
```

and to the widget root, a property the fields set:

```qml
  property bool paramFieldFocused: false
```

**2. Fields are click-to-type only, never wheel-adjustable.** `Panel.qml` already carries a hand-tuned `Binding` governing when the inner Flickable claims wheel input. A wheel-consuming control inside that negotiation eats scrolls meant for the list. Use `TextField`; do not add `PanelSlider`, a spinner, or an `onWheel`.

**3. The section is hidden unless the server is running.** Both halves need the daemon. Every other control gates on status.

- [ ] **Step 1: Add the expanded editor to the delegate**

Inside the installed-model `Repeater`'s delegate, after the existing row that shows the model name and size, add:

```qml
                // Expanded parameter editor. Hidden unless this row is the
                // selected one AND the server is up: both reading the values
                // and writing them need the daemon, and every other control in
                // this panel already gates on status.
                ColumnLayout {
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  spacing: Style.space(2)
                  visible: root.expandedModel === modelData.name &&
                           root.status === "running"

                  Repeater {
                    model: Model.PARAM_SPECS

                    RowLayout {
                      Layout.fillWidth: true
                      spacing: Style.space(6)

                      Text {
                        text: modelData.label
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        Layout.fillWidth: true
                      }

                      TextField {
                        id: paramField
                        // The outer delegate's modelData is the model entry;
                        // this Repeater's is the spec. Capture both explicitly
                        // rather than relying on which one `modelData` means
                        // at this nesting depth.
                        readonly property string paramKey: modelData.key
                        readonly property var entry:
                          root.snap.installed[index] !== undefined
                            ? root.snap.installed[index] : null

                        text: service.paramEditText(root.expandedEntry, paramKey)
                        color: root.fg
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        horizontalAlignment: TextInput.AlignRight
                        implicitWidth: Style.space(70)

                        onActiveFocusChanged: root.paramFieldFocused = activeFocus

                        onEditingFinished: {
                          var parsed = Model.parseParamInput(paramKey, text)
                          if (isNaN(parsed)) {
                            // Garbage reverts rather than being stored, so
                            // apply can never offer to send it.
                            text = Qt.binding(function () {
                              return service.paramEditText(root.expandedEntry,
                                                           paramKey)
                            })
                            return
                          }
                          service.setParamEdit(root.expandedModel, paramKey,
                                               String(parsed))
                        }

                        Keys.onEscapePressed: function (event) {
                          // Revert and defocus. Does NOT close the panel --
                          // esc inside an editor means "abandon this edit".
                          text = Qt.binding(function () {
                            return service.paramEditText(root.expandedEntry,
                                                         paramKey)
                          })
                          focus = false
                          event.accepted = true
                        }
                      }
                    }
                  }

                  Button {
                    text: "apply"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: service.paramDirty(root.expandedEntry) &&
                             service.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    tooltipText: "Rewrite this model's parameters"
                    onClicked: service.commitParams(root.expandedEntry)
                  }
                }
```

- [ ] **Step 2: Add the selection state**

On the widget root, beside `paramFieldFocused`:

```qml
  // Which installed model has its editor expanded, by name. One at a time:
  // the list is height-capped and clips, so two open editors would mean
  // scrolling inside a scroll to reach the second one's apply.
  property string expandedModel: ""

  readonly property var expandedEntry: {
    var list = root.snap.installed || []
    for (var i = 0; i < list.length; i++)
      if (list[i].name === root.expandedModel) return list[i]
    return null
  }
```

Toggle it from the existing model row's click handler. The row currently warms the model on click; **keep that as the primary action** and put expansion on a separate small affordance in the row rather than stealing the click — warming is the panel's documented behaviour ("click a model to run it") and repurposing it would break a documented interaction.

- [ ] **Step 3: Confirm the file parses**

Run: `./bin/test`
Expected: **162 Python + 34 JavaScript, 0 skips**, exit 0, `== qml syntax ==` prints `ok`.

Then run `qmlformat Panel.qml >/dev/null` — it reports parse errors with a message where `qmllint` here gives a bare 255.

- [ ] **Step 4: Confirm the upstream API before trusting this plan**

Run: `grep -nE "property|signal" /usr/share/omarchy/shell/Ui/Button.qml | head -20`

Confirm `text`, `fontFamily`, `fontSize`, `horizontalPadding`, `verticalPadding`, `enabled`, `tooltipText` and `onClicked` all exist. `/usr/share/omarchy/` is overwritten wholesale on `omarchy update` (trap 29), so this is verification rather than busywork. If a property has gone, stop and report rather than inventing a replacement.

- [ ] **Step 5: Commit**

```bash
git add Panel.qml
git commit -m "feat: the installed row expands into a parameter editor"
```

---

## Task 6: The cross-language guard

**Files:**
- Modify: `tests/test_cross_language.py`
- Test: itself

**Interfaces:**
- Consumes: `Model.PARAM_SPECS` (Task 2), `PARAM_BOUNDS` (Task 3), and `Panel.qml` (Task 5).
- Produces: `ParamSpecTest`.

**Why it reads all three files.** Trap 12: "Values hand-duplicated across the Python/JS/QML boundary fail *silently* on a one-sided edit." PR #6 wrote a guard for exactly this and **omitted `Panel.qml`**, which let a hardcoded clamp drift with the suite green. `ColorPaletteTest` in this same file already reads `Panel.qml` for exactly this reason — follow it.

- [ ] **Step 1: Write the test**

```python
class ParamSpecTest(unittest.TestCase):
    """The four parameters and their bounds live in three files. A one-sided
    edit fails silently: the panel would clamp to one range while the script
    refused another, and the user would see a field that will not commit with
    no error explaining why. See AGENTS.md trap #12.
    """

    KEYS = ["num_ctx", "temperature", "top_p", "top_k"]

    def test_the_parameter_set_agrees_across_all_three_surfaces(self):
        model_js = read("Model.js")
        # Order matters in Model.js: PARAM_SPECS drives display order.
        found = re.findall(r'\{\s*key:\s*"([a-z_]+)"', model_js)
        self.assertEqual(found, self.KEYS,
                         "Model.PARAM_SPECS must list exactly these four, in "
                         "this order")
        self.assertEqual(sorted(action.PARAM_BOUNDS), sorted(self.KEYS),
                         "colophon_action.PARAM_BOUNDS must cover the same set")

    def test_the_bounds_agree_between_javascript_and_python(self):
        model_js = read("Model.js")
        for key, (low, high, _is_int) in action.PARAM_BOUNDS.items():
            spec = re.search(
                r'key:\s*"' + re.escape(key) + r'",\s*label:[^,]+,\s*'
                r'min:\s*([0-9.]+),\s*max:\s*([0-9.]+)', model_js)
            self.assertIsNotNone(
                spec, "no min/max found for " + key + " in Model.js")
            self.assertEqual(float(spec.group(1)), float(low), key)
            self.assertEqual(float(spec.group(2)), float(high), key)

    def test_panel_qml_hardcodes_no_bound(self):
        # PR #6's equivalent guard omitted Panel.qml, so a hardcoded clamp
        # drifted from Model.js with the whole suite green. ColorPaletteTest
        # reads Panel.qml for exactly this reason.
        panel = read("Panel.qml")
        for key, (low, high, _is_int) in action.PARAM_BOUNDS.items():
            for bound in (low, high):
                # 0 and 1 are far too common in QML to assert on.
                if bound in (0, 0.0, 1, 1.0):
                    continue
                self.assertNotIn(
                    str(bound), panel,
                    "Panel.qml must not hardcode " + key + "'s bound "
                    + str(bound) + " -- bind to Model.PARAM_SPECS instead")

    def test_the_collector_surfaces_exactly_these_parameters(self):
        self.assertEqual(sorted(collect.EDITABLE_PARAMS), sorted(self.KEYS),
                         "the collector's filter must match the editable set")
```

`read(...)` and the `action` / `collect` imports already exist in this file. Read the top before writing.

- [ ] **Step 2: Run it and watch it pass, then prove it can fail**

Run: `python3 -m unittest tests.test_cross_language -v 2>&1 | tail -10`
Expected: OK — the sources already agree, so this passes immediately. That is expected and not a defect.

**Then prove it guards, because a test that cannot fail is worse than none.** Temporarily change `num_ctx`'s max in `Model.js` from `131072` to `262144`, re-run, and confirm `test_the_bounds_agree_between_javascript_and_python` **fails**. Restore it and confirm green. Quote both outcomes in your report — this is the step that makes the guard worth its lines.

- [ ] **Step 3: Run the whole suite**

Run: `./bin/test`
Expected: **166 Python + 34 JavaScript, 0 skips**, exit 0. Python up four.

- [ ] **Step 4: Commit**

```bash
git add tests/test_cross_language.py
git commit -m "test: pin the parameter set and bounds across all three surfaces"
```

---

## Task 7: Documentation

**Files:**
- Modify: `README.md` — the `## Using the panel` list; `AGENTS.md` — the standing safety rule and a new trap
- Test: none

**Interfaces:** none.

- [ ] **Step 1: Add a README bullet**

In `## Using the panel`, after the "Click an installed model" bullet:

```markdown
- **The parameter editor** opens from an installed model's row and shows the
  four values that model actually declares: context (`num_ctx`), temperature,
  `top_p` and `top_k`. Blank means the model declares nothing for it and
  Ollama's own default applies. Edit any of them and press **apply** to write
  them back to that one model — nothing else is touched, and everything else the
  model carries (its template, system message and stop sequences) is preserved.
  Context is measured in *tokens*, not bytes. A model already loaded keeps its
  old values until it is unloaded, and a newly pulled model starts with whatever
  it ships with until you open it. The editor needs the server running.
```

Then read the rest of the README with fresh eyes for any sentence that now reads as false — in particular anything claiming Colophon only reads the model store.

- [ ] **Step 2: Widen the standing safety rule**

`AGENTS.md`'s rule currently ends "and none may pull or delete a model." Overwriting a definition is neither, and this feature makes it reachable. Change it to read "**none may create, overwrite, pull or delete a model**", keeping the surrounding sentences.

- [ ] **Step 3: Add a trap**

Find the highest trap number in the "Colophon's own" table and add the next one. It records that `ollama create` with `FROM <model>` naming the model itself is **additive**, not replacing — template, system message and existing parameters all survive, verified by setting a system message and a temperature on a throwaway copy and re-creating it with a bare two-line Modelfile. And that it is metadata-only: 45ms on an 18.2 GB model, faster than on a 2 GB one, so it does not scale with model size. The guard column should say there is no test — it is an Ollama behaviour, not project code — and that the way to check it is `ollama cp` to a throwaway, compare `ollama show --parameters/--template/--system` before and after, then `ollama rm`.

Do not renumber any existing trap.

- [ ] **Step 4: Verify and commit**

Run: `./bin/test`
Expected: **166 Python + 34 JavaScript, 0 skips**, unchanged — `bin/test` lints the manifest and shell scripts, so documentation edits can still break it.

```bash
git add README.md AGENTS.md
git commit -m "docs: the parameter editor, and a widened safety rule"
```

---

## Task 8: Verify on the machine

**Files:** none.

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces: the only evidence any of the QML works. `qmllint` cannot resolve `qs.Ui`, so nothing in this repository can validate a binding.

**This task is for the owner, not an agent.** It writes real model definitions. **An implementer must not run it.**

Record the starting state first: `ollama show <model> --parameters` for whichever model you test, so you can put it back.

- [ ] **Step 1: Deploy**

```bash
cd ~/Src/colophon && bin/dev up
```

- [ ] **Step 2: The editor shows real values**

Open the panel with the server running. Expand `nomic-embed-text:latest` — it declares `num_ctx 8192` on this machine, so the context field should read `8192` and the other three should be blank. Expand `gemma3:4b`: temperature `1`, `top_k` `64`, `top_p` `0.95`, context blank.

**Blank must mean blank, not `0`.** A field reading `0` would claim the model declares a value it does not.

- [ ] **Step 3: Every character reaches the field**

Type into the context field: `16384`. Then try `1`, `6`, `k`, `j`, `h`, `l`, and a space.

**Pass:** every character appears, including lowercase `k`. **Fail:** any character vanishes — that is the key catcher not being `blocked`, and it is exactly what shipped broken in PR #6.

Then press Enter. The field should commit its value and stay put; the panel must not close.

- [ ] **Step 4: Escape abandons the edit**

Type a different value, then press Escape.

**Pass:** the field reverts to the model's stored value, the field loses focus, and **the panel stays open**. **Fail:** the panel closes.

- [ ] **Step 5: A scroll gesture scrolls the list**

Put the cursor over a parameter field and scroll the wheel.

**Pass:** the installed list scrolls. **Fail:** the field's value changes — that is a wheel-consuming control inside the Flickable's negotiation, which PR #6 hit twice.

- [ ] **Step 6: Apply writes, and writes only that model**

Pick a model you are willing to change. Note its current parameters. Change one value, press **apply**.

Expect: no error strip, and within one poll the field shows the new value. Then confirm from a terminal:

```bash
ollama show <that model> --parameters     # the new value, plus everything it had before
ollama show <a different model> --parameters   # unchanged
```

Everything the model carried before — stop sequences, template, system message — must still be there. That is the additive property, verified independently on 2026-08-23; this is confirming it through the panel.

- [ ] **Step 7: The editor is absent while the server is stopped**

Stop the service from the panel, authenticate, and confirm the parameter editor is gone rather than showing an error.

- [ ] **Step 8: Restore and report**

Put the parameters you changed back, then record each step's outcome in the spec's Testing section. **Do not mark anything verified that was not observed on screen** — an earlier check on this project was marked confirmed on a controller's word and turned out false.

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Four editable scalars, no others | 2 (specs), 3 (bounds), 6 (guard) |
| Read parameters without an API call | 1 |
| `stop` shown as a count, not editable | 5 (out of scope; count is optional polish) |
| Template / system / license out of scope | not implemented, by design |
| No global default, no sweep | nothing implements one |
| Row expands in place | 5 |
| Explicit apply, one create per apply | 4 (`commitParams`), 5 (button) |
| Write via `POST /api/create`, no temp file, no CLI | 3 |
| Click-to-type only, never wheel-adjustable | 5, verified in 8 step 5 |
| Key catcher blocked while a field has focus | 5, verified in 8 step 3 |
| `esc` reverts and defocuses, does not close | 5, verified in 8 step 4 |
| Hidden unless the server is running | 5, verified in 8 step 7 |
| Bounds validated in the script, the only writing surface | 3 |
| Edits win over a poll | 4 (clearing rule) |
| Cross-language guard incl. `Panel.qml` | 6 |
| Safety rule widened to cover create/overwrite | 7 |
| Four by-hand checks | 8 |

One gap, accepted: the spec mentions showing a **`stop` sequence count**, and no task implements it. It needs `scan_installed` to surface a count, which Task 1 does not do — its filter drops `stop` entirely. Folding it in would mean widening Task 1's filter to carry a count alongside the four values. Left out rather than half-specified; add it as a follow-up if the editor feels bare without it.

**Placeholder scan:** clean. Every code step carries real code; the two "read the existing helper first" instructions name what to look for and what to do if it differs.

**Type consistency:** `parameters` is a dict of `key -> number` in Task 1, read as `entry.parameters[key]` in Task 2, and asserted against `EDITABLE_PARAMS` in Task 6. `PARAM_SPECS` entries are `{key, label, min, max, step, decimals}` in Task 2 and consumed by `.key`/`.label` in Task 5. `paramEdits` is keyed `"<model>|<param>"` in Task 4 and only ever accessed through `paramEditKey`. `runAction` gains a fourth `extraArgs` parameter in Task 4 and is called with it in the same task.

**Test counts:** 150 → 153 (Task 1) → 162 (Task 3) → 166 (Task 6) Python; 29 → 34 (Task 2) JavaScript. Tasks 4, 5, 7 add none.
