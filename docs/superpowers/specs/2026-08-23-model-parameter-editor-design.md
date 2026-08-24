# Colophon — the per-model parameter editor

**Date:** 2026-08-23
**Status:** Approved, ready for planning
**Decomposes:** Phase 2 item 3 of
`docs/superpowers/specs/2026-08-10-colophon-design.md`
**Supersedes on landing:** PR #6 (`feat/context-window`)

## Purpose

Open an installed model in the panel, see the parameters it actually carries,
and change one. Writes go through Ollama's own API and are additive: nothing the
model already declares is lost.

The motivating case is a client that never sends `num_ctx` itself — opencode
speaks Ollama's `/v1` OpenAI endpoint and has no way to ask for a context size —
so the size has to live on the model rather than in the request.

## How Phase 2 item 3 decomposes

The original item read "Model management: pull, delete, rename," deferred "for
the progress and destructive-confirmation UI, not for permissions." Grouped by
verb, that hides the fact that the pieces have wildly different costs. Grouped by
the infrastructure each needs, it splits five ways:

| Piece | Needs | State |
|---|---|---|
| **A. Inspect** — read a model's parameters | nothing | **this spec** |
| **B. Edit** — write one back | nothing | **this spec** |
| C. Delete — `rm MODEL [MODEL...]` | a confirm dialog | not built |
| D. Rename — `cp` then `rm` | confirm dialog + text input | not built |
| E. Pull — `POST /api/pull` | a progress surface, and an answer to discovery | not built |

A and B need none of what deferred the item, which is why they come first. C and
D need `Ui/ConfirmDialog.qml`, which already ships upstream with a usable API
(`opened`, `message`, `confirmText`, `cancelText`, `selectedIndex`) and is
currently unused here.

**E carries both unsolved problems alone.** There is no progress component
anywhere in the shell — the three panels that render a `percent` are gauges
(CPU, battery, signal), not long-running tasks — and there is no way to list what
is available to download. `ollama` has no registry-search command; its full verb
set is `serve create show run stop pull push signin signout list ps cp rm launch
help`. A pull UI would need either a free-text field where the user types a name
from memory or a catalog Colophon does not have. E should not be attempted until
that question has an answer.

## Verified, 2026-08-23

Every claim the design rests on was measured on the target machine, not assumed.
All experiments ran against a `ollama cp` throwaway and removed it afterwards.

| Claim | Evidence |
|---|---|
| `create` is additive, not replacing | On a copy of `llama3.2:3b`: template byte-identical (1429 B), all three `stop` sequences preserved, `num_ctx 16384` added |
| It preserves a *user's* customisation too | Set `SYSTEM "You are a pirate…"` and `temperature 0.17` on the copy, then re-created with a bare `FROM` + `PARAMETER num_ctx` — both survived |
| It is manifest-only and does not scale with model size | 0.068s on the 2.0 GB `llama3.2:3b`; **0.045s on the 18.2 GB `muse-glimmer`**. Output reads `using existing layer` for weights, one new metadata layer |
| The HTTP API accepts parameters inline | `POST /api/create` with `{"model":X,"from":X,"parameters":{"num_ctx":16384,"temperature":0.42}}` → `{"status":"success"}`, both values applied, stop sequences preserved |
| Models carry author-set parameters worth not clobbering | `nomic-embed-text:latest` already declares `num_ctx 8192`. Across the store: `stop` on 3 models, `temperature` on 3, `top_k`/`top_p` on 2–3, `num_gpu` on none |
| The installed list is height-capped and clips | `Panel.qml`: `Layout.preferredHeight: Math.min(installedColumn.implicitHeight, Style.space(190))`, `clip: true` |

That fifth row is the design's central argument. A global sweep cannot know that
`nomic-embed-text`'s 8192 was already correct for a model trained at 2048; an
editor that shows the current value can.

## Scope

> **Amended 2026-08-24, after the editor was seen running.** The parameter set
> below was narrowed from four scalars to two — `num_ctx` and `temperature` —
> and the rationale in this section turned out to be wrong. See
> [Amendment: two parameters, explained](#amendment-2026-08-24--two-parameters-explained)
> at the end of this document, which supersedes the paragraph immediately below.

**In:** ~~four~~ editable scalars — `num_ctx`, `temperature`, ~~`top_p`, `top_k`~~ —
plus a read-only count of `stop` sequences. Chosen because they are exactly the
parameters models on this machine actually set, so a model you open shows
populated fields rather than blanks.

**Out, deliberately:**

- **Template, system message and license.** `llama3.2:3b`'s template is 43 lines
  of Jinja and special tokens; it is a model-author artifact, not something a bar
  widget should paginate. `ollama show llama3.2:3b --template` is the right tool.
  This narrows "inspect" from `ollama show`'s full surface to its parameters, and
  it is what lets the editor live inline instead of requiring a detail screen.
- **`stop` sequence editing.** It is a list, not a scalar, and the panel has no
  list-editing idiom. Shown as a count.
- **Any global default, and any sweep over multiple models.** A newly pulled
  model keeps whatever it ships with until you open it. This is an accepted gap,
  stated in Known limitations, and it is the single largest difference from PR #6.
- **`num_gpu`.** The panel already visualises its effect (the GPU/CPU split), but
  nothing on this machine sets it, and its default — as many layers as fit — is
  usually right.

## The control

**Layout: the row expands in place.** Click an installed model and its row grows
to show the four fields directly beneath it. Chosen over a per-model detail
screen after drawing both.

The deciding argument was not layout but key handling. A detail screen makes
`esc` mean two things depending on where you are, and this shell's key handling
is `Keys.priority: Keys.BeforeItem` with signal-based movement — the place where
PR #6 broke its own headline feature. Inline expansion adds no navigation state.

The scroll concern that argued against inline expansion turned out not to apply:
the installed list already scrolls within a capped 190 height, so expanding a row
grows `installedColumn` inside a container that does not grow. **The panel's
height does not change and nothing else moves.**

**Commit: an explicit apply, one `create` per apply.** Not per-field, and not
debounced. Speed is not the reason — a create is 45ms on an 18 GB model — these
are:

- A create rewrites the *model's* manifest. Every other control in Colophon
  changes Colophon's own settings. A write that persists outside the application
  deserves a deliberate moment.
- `top_p` and `top_k` are a sampling pair; setting one without the other is often
  meaningless. Per-field commit produces four manifest revisions for one intent,
  three of them configurations nobody wanted.
- It gives failure one place to land. With per-field commit, a mid-edit server
  stop leaves an unclear question of which field applied. PR #6's
  "benign stderr wedges the feature forever" bug came from exactly this: unclear
  ownership of error state across a multi-write operation.

The cost, stated plainly: this introduces dirty state to a panel that has none.
Everything in Colophon today commits on click.

**Fields are click-to-type only, never wheel-adjustable.** `Panel.qml` already
carries a hand-tuned binding governing when the inner Flickable claims wheel
input (`interactive: loadedColumn.implicitHeight > loadedScroll.height`,
"otherwise a short list still swallows scroll events the panel's outer view
should get"). Putting a wheel-consuming control inside that negotiation is how
you get a field that eats a scroll you meant for the list. PR #6 hit the wheel
path twice. Sidestep it rather than tune it.

**`esc` while a field has focus reverts and defocuses; it does not close the
panel.** And the key catcher must set `blocked` while any field has focus —
`PanelKeyCatcher`'s own documentation requires it, and three first-party panels
do it (`network:996`, `clock:250`, `weather:501`). Omitting it is what made PR
#6's `k` shorthand work only in uppercase.

**The whole section is hidden unless the server is running.** Both `show` and
`create` need the daemon. Every other control in the panel already gates on
status, and PR #6's context row not doing so is why adjusting a preference could
paint "Connection refused".

## Data flow

Reading needs no new mechanism. `colophon_collect.py` already walks
`/var/lib/ollama` for the installed list; parameters come from the same manifest
tree, so the four values ride in the existing snapshot rather than requiring a
new call. Nothing new polls.

Writing is one new verb in `colophon_action.py`, following the shape of `warm`
and `unload` exactly: build a JSON body, `post_json` it. `POST /api/create` with
`from` set to the model's own name and a `parameters` object.

**No temp file, no Modelfile, no `ollama` binary.** This is the largest
divergence from PR #6, and it dissolves three of that PR's findings rather than
fixing them: there is no `/tmp` path to be symlinked, no `OLLAMA` PATH
dependency, and no mismatch between the host enumerated and the host written to —
the create goes to the same `apiBase`, by construction.

## Error handling

Reuses what exists. A failed create returns non-zero with stderr, which
`Service.qml` already routes to the error strip via `Model.actionErrorText`. The
apply is a single operation, so `actionInProgress` latches and clears exactly as
it does for a lifecycle verb, and the existing `onRunningChanged` guard
guarantees it clears even if the helper fails to spawn.

Two failure modes need naming rather than new machinery:

- **A value the server rejects.** Bounds are validated in
  `colophon_action.py` before the request, mirroring `--keep-alive`'s existing
  validation. The script is the only surface that writes.
- **Dirty state when the snapshot changes underneath.** If a refresh lands while
  fields are edited, the edits win — the user's in-progress intent is never
  overwritten by a poll. This mirrors `optimisticBootState`'s rule: prefer the
  local intent, clear it once the action completes.

## Testing

The standing safety rule needs widening. It currently reads "none may pull or
delete a model," which does not cover *overwriting a definition* — and this
feature makes that reachable. **No test may create, overwrite, pull or delete a
model.** The write verb is asserted through `--dry-run` only, as every privileged
verb already is.

Testable:

- Bounds validation per parameter, and rejection of out-of-range values.
- The constructed request body for each parameter, through `--dry-run`.
- A cross-language guard, in `tests/test_cross_language.py` per trap 12, pinning
  the parameter names and their bounds across `Model.js`, `colophon_action.py`,
  the manifest schema **and `Panel.qml`**. PR #6's equivalent guard omitted
  `Panel.qml` and so let a hardcoded clamp drift silently; `ColorPaletteTest`
  already reads `Panel.qml` for exactly this reason.
- Parameter parsing and display formatting in `Model.js`.

Not testable here, and to be stated as unverified until observed on screen:

1. The row expands, the four fields show the model's real values, and apply
   writes them.
2. `esc` in a focused field reverts and defocuses without closing the panel, and
   every character reaches the field — lowercase included.
3. A scroll gesture over a field scrolls the list rather than changing the value.
4. The section is absent while the server is stopped.

`qmllint` cannot resolve `qs.Ui`, so it proves only that the file parses, and per
trap 15 it reports failures as a bare exit 255 with no message. Item 2 is the one
PR #6 got wrong; item 3 is the one it got wrong twice.

## Relationship to PR #6

PR #6 solves the same motivating problem with a global slider that sweeps every
installed model via the `ollama` CLI. It is a fuller answer to "new models get
the right context" and a much larger blast radius: its own review found the
sweep stamps chat contexts onto embedding models, aborts partway leaving a mixed
store, and can hold the panel disabled for 24 minutes.

Those are not independent bugs. They follow from sweeping rather than editing.

**PR #6 stays open, with changes requested, until this lands.** It is not closed
in advance: if its blockers are fixed before this ships, that is a decision worth
making deliberately rather than by default. On landing, it closes with a pointer
here.

## Known limitations

- **A newly pulled model keeps its shipped defaults** until you open it. The
  opencode case is solved per model, not automatically. Deliberate: the
  alternative is a global mechanism that rewrites models you never chose to
  touch.
- **Editing requires the server running.** Both halves need the daemon; the
  section is hidden otherwise.
- **Parameters are read from the manifest tree**, so a change made outside
  Colophon appears after the next poll rather than immediately.
- **`stop` sequences are shown but not editable**, and template, system message
  and license are not shown at all.

## Amendment 2026-08-24 — two parameters, explained

The four-parameter set shipped, was deployed, and was rejected by the owner on
sight: *"the ui is difficult here... there are options that don't apply... it's
not clear what are valid values it would also be useful to give an indication of
what each parameter does. we may want to scope config to temp and context
window."*

### The rationale above was measurably wrong

Scope claimed the four were "exactly the parameters models on this machine
actually set, so a model you open shows populated fields rather than blanks."
Measured against all 11 installed models on the target machine:

| | declares `num_ctx` | `temperature` | `top_p` | `top_k` | declares nothing |
|---|---|---|---|---|---|
| 10 `generate` models | **0** | 6 | 5 | 4 | 4 |
| 1 `embed` model | 1 | meaningless | meaningless | meaningless | — |

The Verified table's fifth row counted parameters *across* the store and read
that as coverage. What matters is what a single opened model shows, and there
the answer is mostly blanks. Worse, the one parameter the feature exists for —
`num_ctx`, because a client on Ollama's OpenAI `/v1` endpoint cannot ask for a
context size — is declared by **no generative model at all**. The blank field
was the main case, not an edge case, and the design had no answer for it.

This is a specific reasoning error worth naming: an aggregate over a collection
was used to predict a property of one member. The same table would have
justified adding `stop`, which is set on three models and useless to edit here.

### What changed

- **`num_ctx` and `temperature` only.** `top_p` and `top_k` are never set alone
  on this store — always alongside `temperature`, as an author-tuned set.
  Exposing half of a sampling pair in a bar widget invites making output worse.
  This spec had already argued that "setting one without the other is often
  meaningless" and drew only the conclusion that commits should be batched; the
  stronger conclusion was available and was missed.
- **An unset field shows its valid range as placeholder text** — `4096–131072`,
  `0–2`. This answers "what values are valid" and repairs the empty box, which
  read as a failed load rather than as "not set".
- **A dim caption under each field says what the parameter does.** Deliberately
  not a tooltip: the owner had already overruled a right-click trigger on the
  grounds that an invisible affordance has no discovery, and a tooltip would
  repeat that mistake. Cutting two parameters is what pays for the vertical
  space the captions need — the editor is shorter than the four-field version it
  replaces.
- **Parameters that do not apply to a model's kind are hidden, not disabled.**
  Every installed row already carries `kind` (`generate` or `embed`) from the
  collector's `EMBED_FAMILIES`, so this needs no new data. `nomic-embed-text`
  shows `context` and nothing else.

### Consequences elsewhere in this document

- **Testing** — the cross-language guard now pins two names, and only
  `num_ctx`'s bounds survive as assertable literals against `Panel.qml`;
  temperature's `0` and `2` are too common in QML to assert on. The guard is not
  airtight and its tests now say so.
- **Known limitations** — one is added: `131072` is a fixed ceiling, but a model
  trained at 8192 will accept a larger window and quietly degrade. The real
  trained maximum lives in GGUF metadata the manifest tree does not carry, so
  Colophon cannot warn about it.
- **Relationship to PR #6** — unchanged. PR #6 stays open with changes
  requested until this lands, then closes with a pointer here.
