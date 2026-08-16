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
and it would block the `k` shorthand: `parseContextSize` accepts a plain
integer (`18000`) or a `k` suffix (`24k` = 24000, case-insensitive), converts
it, and returns `NaN` for anything else — including `2.4k`, `24kk`, `0x20`
(which bare `parseInt` would read as `0`), and negative values. The regex
guard exists precisely so `0x20` cannot reach `parseInt`.

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

## Testing

No new manual check is needed against the live service, and none is claimed.
Everything write-shaped here goes through `--dry-run`, per the standing safety
rule.

Testable, all green as of writing (163 Python + 31 JS):

- `--context-size` parsing: non-integer, out of range (0, 2048, 131073,
  99999999, negative), and both boundary values accepted
- an in-range, non-step value (18000) accepted and carried as-is — the typed
  path in the panel
- plan/dry-run output carries `"num_ctx": N` for generate and embed; no
  `options` block when the flag is absent; `load_body` treats a falsy 0 as
  absent
- `snapContext`/`contextIndex`/`contextAt`: index round-trips, clamping at both
  ends, NaN/null/undefined coercion, and the halfway tie resolving to the lower
  step
- `parseContextSize`: plain and `k`-shorthand integers, and the whole garbage
  class (`2.4k`, `0x20`, negatives, empty) returning `NaN`
- the cross-language guards above

Not testable in this repository, and therefore **unverified until someone
walks it against the live shell**:

1. the slider and the editable field render, and a drag or a typed commit
   both persists and does not snap back
   (`qmllint` cannot resolve `qs.Ui`, so nothing in the suite can reach it)
2. a warm posts `num_ctx` and the model loads — which would be confirmed, if
   ever, through the existing fixture-based collector and a manual warm

Both are cheap to check on the deployed dev build and should be recorded here
with the same distinction between reported and inferred that the boot-toggle
spec's verification section uses.

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
