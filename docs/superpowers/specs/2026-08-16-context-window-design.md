# Colophon — the context-window slider

**Date:** 2026-08-16
**Status:** Approved, ready for review
**Depends on:** `docs/superpowers/specs/2026-08-10-colophon-design.md`

## Purpose

Let the panel choose how much context a warmed model gets, instead of letting
Ollama fall back to a model-specific default. A slider that snaps to powers of
two sits above the model rows; the chosen size travels as `options.num_ctx` in
the warm request.

## The units, stated once

Ollama's `num_ctx` is measured in **tokens**, not bytes. The sizes this feature
offers — 4096, 8192, 16384, 32768, 65536, 131072 — are the same numbers the
requester asked for in bytes; they are adopted as token counts, which is the
only unit Ollama accepts. This is stated in the README so nobody treats the
slider as a memory guarantee.

`num_ctx` also does not change a model that is already loaded. It is read when
the model is loaded into memory, so the slider configures the *next* warm and
the panel says so.

## Scope

In:

- a `contextSize` setting (default 8192) in `manifest.json`, plus schema bounds
  4096–131072
- a snapping slider in `Panel.qml`, rendered from an index over a step list
- an editable number field beside the slider in `Panel.qml`, accepting any
  whole value in range
- pure snap/round-trip helpers in `Model.js` (`CONTEXT_STEPS`,
  `snapContext`, `contextIndex`, `contextAt`)
- a `--context-size N` flag on the warm verb in `scripts/colophon_action.py`,
  validated against the same 4096–131072 bounds, serialized as
  `options: { num_ctx: N }`
- `Service.qml` reading the setting and passing it on warm

Out:

- **Applying context to an already-loaded model.** `num_ctx` is a load-time
  option; re-warming would need an unload first, and silently doing that on a
  slider drag would discard a loaded model the user may be mid-generation on.
- **Changing context on unload.** An unload posts `keep_alive: 0` and nothing
  else; there is nothing for `num_ctx` to mean there.
- **A second slider for the running server.** Context is per-load, not per
  server; one control is enough.

## The control

A `PanelSlider` from the shell's `Ui` (`/usr/share/omarchy/shell/Ui/
PanelSlider.qml`), the same component the audio panel uses for volume, placed
between the lifecycle action row and the error strip in `Panel.qml`. The slider
moves over the **index** of `Model.CONTEXT_STEPS`, not the values:

```qml
minimum: 0
maximum: Model.contextCount() - 1
step: 1
integer: true
tickCount: Model.contextCount()
value: Model.contextIndex(service.contextSize)
onMoved: function (index) {
  root.setContextSize(Model.contextAt(index))
}
```

Stepping by index is what makes the snap a snap. A value-based slider over a
log or linear range would have to round anyway; an index-based one *cannot*
land off a step.

### The editable number

Beside the slider sits a compact `TextField` (the `qs.Ui` one, a QQC
TextField) holding the actual setting — not the snapped step. Click it, type
a size, and on `editingFinished` (Enter or focus loss) the text is parsed by
`Model.parseContextSize`, clamped to the bounds, and persisted through
`setContextSize`; a value that fails to parse — an emptied field, garbage — 
reverts to the current setting.

There is deliberately **no `IntValidator`**. A validator blocks keystrokes,
and it would block the `k` shorthand. `parseContextSize` distinguishes two
input kinds:

- **Plain integers** (`18000`) are taken exactly — the field is the exact
  control, the slider is the snapping one.
- **`k` shorthand** (`16k`, `16K`) is always a binary thousand, ×1024 — the
  size those names denote in practice. `16k` is 16384 and `8k` is 8192, and
  a non-power-of-two k stays exact too: `24k` is 24576, `18k` is 18432. It is
  never snapped or rounded to a preset step.

Anything else — `2.4k`, `24kk`, `0x20` (which bare `parseInt` would read as
`0`), negatives, an emptied field — returns `NaN` and reverts the field to
the current setting. The regex guard exists precisely so `0x20` cannot reach
`parseInt`.

The field re-binds `text` to the setting after every commit, so a slider drag
or the shell's settings panel keeps it live when it is not being edited.
Typed values are sent to Ollama exactly; only the slider knob approximates to
the nearest step, and the spec's cross-language guard still pins the slider's
steps to the parse/validator range.

The manifest schema's step is `1` (any whole value in range), matching the
field; the slider's own steps remain powers of two.

`PanelSlider`'s `value` binding plus its `onValueChanged: if (!dragging)
liveValue = value` guard already prevents the persisted setting from fighting
the knob mid-drag: the `moved` handler updates the setting, the setting
re-binds `value` to the same index, and nothing snaps back on release.

## Persistence

The power panel's pattern, verbatim in mechanics:

```qml
function setContextSize(value) {
  root.settings = Object.assign({}, root.settings, { contextSize: value })
  if (root.bar && root.bar.shell)
    root.bar.shell.updateEntryInline(root.moduleName, root.settings)
}
```

`updateEntryInline` writes the widget's inline settings to the `shell.json` bar
layout entry (which hot-reloads on save) and diffs first, so an unchanged value
does not dirty the file. Reassigning `root.settings` in the same breath re-runs
`Service.qml`'s `settings:` binding, so `contextSize` updates without waiting
for a reload.

## Constants, and the guard that pins them

The bounds cross three authorities and a wrong value on any one of them fails
silently:

| Value | Model.js | colophon_action.py | manifest.json schema |
|---|---|---|---|
| min | `CONTEXT_MIN = 4096` | `CONTEXT_MIN = 4096` | `min: 4096` |
| max | `CONTEXT_MAX = 131072` | `CONTEXT_MAX = 131072` | `max: 131072` |
| steps | `CONTEXT_STEPS` | — (range only) | — |
| default | `CONTEXT_DEFAULT = 8192` | — | `defaultValue: 8192` |

`tests/test_cross_language.py`'s new `ContextWindowTest` asserts:

- the steps are powers of two, ascending, and stay inside the min/max
- the first and last steps equal `CONTEXT_MIN`/`CONTEXT_MAX` — a slider that
  extended past the validator's range would offer sizes the action script
  refuses; one that started above the minimum would hide sizes the script
  accepts
- Python's constants equal Model.js's, parsed from each file
- the manifest schema's bounds sit inside Python's, and its default is a value
  the slider can actually produce

`SettingsDefaultTest` already covers `Service.qml`'s `setting("contextSize",
8192)` against the manifest default, and `test_manifest.py`'s
`test_every_default_key_is_expected` required `contextSize` to be added to its
exact key list.

## Where the value travels

`Service.qml` appends `--context-size <value>` only in the `warm` branch of
`runAction`, mirroring the existing `--keep-alive`. `colophon_action.py`
validates it as an integer in [4096, 131072] — the script is the only surface
that performs a write and cannot assume the caller clamped, for the same reason
`--keep-alive` does not assume it — then `load_body` adds
`"options": {"num_ctx": <value>}` when one is present. The body shape is
otherwise unchanged, so both `/api/generate` and `/api/embed` warms carry the
option, and an unload never does. The panel only ever sends a step, but the
flag stays honest for any future caller, including the shell's settings panel.

## Committing also applies the default to every installed model

`--context-size` only helps callers that send the option. opencode — the
reason this feature exists — never does: it talks to Ollama only through the
OpenAI-compatible `/v1/chat/completions` endpoint, and Ollama 0.17.5 drops
`num_ctx` from that endpoint's request entirely (the forwarding landed in
ollama/ollama#16825, unmerged as of writing). So for opencode, the only lever
is the model's own default, set at creation via a Modelfile `PARAMETER
num_ctx`.

The commit action closes that gap. Releasing the slider or finishing a number
field edit runs a new `apply-context <size>` verb:

- the panel freezes the committed size, persists it as `contextSize`, and calls
  `service.runAction("apply-context", String(size), "")`
- `colophon_action.py apply-context <size>` lists installed models via GET
  `<api-base>/api/tags`, then for each runs `ollama create <model> -f <temp
  Modelfile>` whose contents are `FROM <model>` plus `PARAMETER num_ctx
  <size>`. Naming the model itself as FROM re-stamps a definition in place,
  metadata-only — sub-second per model, no weight copy, blobs stay shared —
  and it is what lets a client that sends no `num_ctx` load at the panel's
  chosen size. Verified live against Ollama 0.17.5.
- the size travels positionally, never via `--context-size`: the frozen value
  doubles as the dedup key, so a settings change racing the rebuild cannot
  corrupt the marker `Service.qml` compares. Passing both is refused (exit 2),
  as is a missing or out-of-range size.
- `Service.qml` skips the action when `target` equals the last size that
  *succeeded* (`lastAppliedContextSize`, set in `actionProc.onRunningChanged`
  only when the exit was clean) — a no-move slider release is the main repeat
  case, and re-running an 11-model sweep for nothing is not worth it. A failed
  apply leaves the marker stale so the next commit retries.
- `apply-context` deliberately never starts the service. A down server means
  there is nothing to rewrite, and auto-starting on a settings commit would be
  a surprise. The panel shows the failure in its error strip.
- the applied default does not touch a loaded model; it governs the next load.
  This is the same load-time semantics as `num_ctx` itself.

### The commit trigger is release, not every drag tick

`PanelSlider` emits `moved` on every drag step and `released` on release (and
`onWheel` fires both). `onMoved` keeps persisting the size live — that is how
the number field tracks a drag — but only `onReleased` (and the field's
`onEditingFinished`) commits the sweep, so one drag is one apply.

## Testing

No new manual check is needed against the live service, and none is claimed.
Everything write-shaped here goes through `--dry-run`, per the standing safety
rule. (The apply-context sweep was, however, exercised once against the live
machine during this review, as a deliberate logged manual check: all 12
installed models re-stamped to 24000 in ~0.7s, and a bare
`/v1/chat/completions` request — no `num_ctx` in the body, the exact opencode
path — loaded `qwen3.5:9b` at CONTEXT 24000.)

Testable, all green as of writing (180 Python + 33 JS):

- `--context-size` parsing: non-integer, out of range (0, 2048, 131073,
  99999999, negative), and both boundary values accepted
- an in-range, non-step value (18000) accepted and carried as-is — the typed
  path in the panel
- plan/dry-run output carries `"num_ctx": N` for generate and embed; no
  `options` block when the flag is absent; `load_body` treats a falsy 0 as
  absent
- `apply-context`: plan is exactly two lines (list `/api/tags`, re-create
  every model with `num_ctx N`); dry-run performs no I/O; missing size, an
  out-of-range size, and a duplicated `--context-size` all exit 2; in-range
  sizes exit 0
- `installed_models` returns every named entry and refuses a refused, truncated,
  or malformed response with None (trap #25's `IncompleteRead` included)
- `create_with_context` builds the self-referencing Modelfile, runs
  `ollama create <model> -f <temp>`, removes the temp file in every path, and
  reports a non-zero exit
- `apply_default_context` visits every installed model, stops on the first
  failure, exits 1 on an unreachable server without starting it, and skips a
  name `MODEL_RE` refuses
- `snapContext`/`contextIndex`/`contextAt`: index round-trips, clamping at both
  ends, NaN/null/undefined coercion, and the halfway tie resolving to the lower
  step
- `parseContextSize`: plain integers exact; `k` shorthand always a binary
  thousand (`8k`→8192, `16k`→16384, `24k`→24576, `18k`→18432); and the whole
  garbage class (`2.4k`, `0x20`, negatives, empty) returning `NaN`
- the cross-language guards above

Not testable in this repository, and therefore **unverified until someone
walks it against the live shell**:

1. the slider and the editable field render, and a drag or a typed commit
   both persists and does not snap back
   (`qmllint` cannot resolve `qs.Ui`, so nothing in the suite can reach it)
2. a warm posts `num_ctx` and the model loads — which would be confirmed, if
   ever, through the existing fixture-based collector and a manual warm
3. releasing the slider runs `apply-context` with the right size, and the
   dedup skips a repeat — QML wiring, only reachable by hand

Both are cheap to check on the deployed dev build and should be recorded here
with the same distinction between reported and inferred that the boot-toggle
spec's verification section uses. (Item 2 was effectively retired on 2026-08-16
when the apply-context manual check above confirmed the `/v1` path; items 1 and
3 remain open for the interactive slider check.)

## Known limitations

- **The slider and the typed value can disagree about position.** A typed
  size like 18000 is sent exactly, while the knob sits at the nearest step
  (16384). The field shows the real value, so this reads as intended rather
  than as a rounding error, but the knob is an approximation for non-step
  values by design.
- **A model with a smaller context maximum than the slider's 131072 caps the
  effective context silently.** That is Ollama's behavior, not a bug Colophon
  can see from outside the process.
- **`num_ctx` does not bound memory.** Token count, KV-cache size, and model
  size are different things; the README says so rather than letting the panel
  imply a relationship it does not have.
- **The applied default lives in each model's definition, not in Colophon.**
  A re-pulled model starts at its own default (typically 2048 or 4096) until
  the next commit. Nothing in Colophon keeps the sweep state beyond the
  in-session dedup marker, so a pull followed by a commit is the recovery —
  and the commit of the current size is a single slider release away.
- **`ollama create` targets the server the CLI talks to.** apply-context runs
  the `ollama` binary on PATH, which speaks to the default local server; a
  custom `apiBase` that differs from that is enumerated but not rewritten.
  Colophon's own warm path has no such constraint, since it POSTs to
  `apiBase` directly.
