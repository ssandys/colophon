# Colophon — the boot toggle

**Date:** 2026-08-12
**Status:** Approved, ready for planning
**Unblocks:** Phase 2 item 1 of
`docs/superpowers/specs/2026-08-10-colophon-design.md`
**Depends on:** `docs/superpowers/specs/2026-08-11-prompted-privilege-design.md`

## Purpose

Make Colophon's boot-state line settable. The panel already reports whether
`ollama.service` starts at boot; this adds a switch that changes it, so the
one-time `sudo systemctl enable ollama.service` the README currently prescribes
stops being necessary.

## Why this is possible now

`Panel.qml:212-214` carries this comment directly above the boot line:

```qml
// The one thing systemd tells us that this widget deliberately cannot
// change: enable/disable goes through manage-unit-files, which polkit
// cannot scope to a single unit. README gives the one-time command.
```

Every clause was true when written and every clause is now moot. `enable` and
`disable` do go through `org.freedesktop.systemd1.manage-unit-files`, which
systemd invokes with no `unit` detail, so no polkit *rule* could scope it to one
unit — but Colophon no longer installs a rule. It prompts. Prompted
authorization has nothing to scope, so it does not care that the action carries
no unit detail. See `AGENTS.md` trap #28, corrected 2026-08-11.

**Deleting that comment is the feature.** Everything below is small.

## Scope

In:

- `enable` and `disable` verbs in `scripts/colophon_action.py`
- a switch on the existing boot line in `Panel.qml`
- boot-state presentation logic in `Model.js`
- the boot branch of `runAction` in `Service.qml`
- corrections to `README.md` and `AGENTS.md` trap #28

Out:

- **`enable --now` / `disable --now`.** Ruled out: it would conflate two
  decisions in one control and cost a second authentication. The panel's start
  and stop buttons already exist a few pixels away.
- **Reconciling boot state with run state.** Enabling at boot on a stopped
  service changes nothing about the running service, and the panel will not
  explain that beyond a tooltip. The two states are already separate lines; that
  separation is the point of the feature, not a gap in it.
- **Masking and unmasking.** `masked` is reported (see below) and never set.

## The control

A bare `ToggleSwitch` from `qs.Ui`, placed beside the existing boot `Text` in a
`RowLayout`. The existing line keeps its exact wording, dim colour
(`Qt.darker(fg, 1.45)`), caption size (10px), and `Style.space(14)` left margin.
Nothing else in the panel moves.

Chosen over the two alternatives after seeing all three drawn at scale:

| Option | Why not |
|---|---|
| `Ui/Toggle.qml` as shipped | `implicitHeight: Math.max(54, …)` with a bold 13px label and a bordered surface. It becomes the largest element in the panel and renders boot state louder than the running state above it. |
| Bare switch with the label promoted to 12px body and reworded to "Start at boot" | Reads more clearly as a control, but rewords a line that is already correct and forces `bootLabel` to be rewritten rather than extended. |

`ToggleSwitch` is the right component for reasons its own header comment states:

> The caller owns the value: bind `checked` to real state and flip it in
> response to `toggled()`. Services that already track a desired state
> optimistically (see the Tailscale service's `_desired`) get an instant knob
> throw for free, because `checked` is already the optimistic value.
>
> `busy` marks an operation in flight and swallows further clicks, but leaves
> hover, cursor, and tooltips alone so the control does not flicker every time a
> background refresh runs.

Both behaviours Colophon needs are therefore bindings, not new code:
`checked` ← optimistic boot state, `busy` ← `actionInProgress`.

**No confirmation step.** Omarchy's authentication dialog is the confirmation:
it names the action and requires a deliberate touch. A second "are you sure?"
would be two confirmations for one intent.

**Tooltip:** `Start ollama.service at boot — does not start it now.` This is
where the boot/run distinction is stated, and the only place.

## Boot states beyond enabled and disabled

`bootLabel` currently returns `""` for anything that is not exactly `enabled`
or `disabled`, and the `Text` is hidden when empty. `UnitFileState` has many more
values: `enabled`, `enabled-runtime`, `linked`, `linked-runtime`, `alias`,
`masked`, `masked-runtime`, `static`, `indirect`, `disabled`, `generated`,
`transient`, `bad`. A user who has run `systemctl mask ollama` currently sees the
line vanish, which reads as a bug, and `enable` on a masked unit fails anyway.

Those states **render their state and offer no switch.** Two pure functions in
`Model.js`:

`bootLabel(unitFileState)` — extended, with this exact mapping. The first two
strings are unchanged from today:

| `UnitFileState` | Label |
|---|---|
| `enabled` | `enabled at boot` |
| `disabled` | `disabled at boot` |
| `enabled-runtime` | `enabled until reboot` |
| `masked`, `masked-runtime` | `masked` |
| `static` | `no boot setting` |
| `generated` | `generated unit` |
| `transient` | `transient unit` |
| `alias`, `linked`, `linked-runtime`, `indirect` | the raw value |
| `bad` | the raw value |
| `""` | `""` (line stays hidden) |

Any value not in that table renders the raw systemd string. A state this spec
did not anticipate must be visible rather than silent — the current
disappearing-line behaviour is precisely the bug being fixed, and reintroducing
it for unknown values would be the same mistake one layer down.

`static` deserves its wording: it means the unit has no `[Install]` section, so
there is nothing to enable or disable. "no boot setting" says that without
implying a state the user could change.

`bootIsToggleable(unitFileState)` — new. Returns true for exactly `enabled` and
`disabled`, false for everything else including empty and including every value
in the table above.

The string `transient` appears only as a *value* here, never as an identifier.
Per `AGENTS.md` trap #15 it is a reserved word in QML's JS grammar and must not
become a property or variable name.

The switch's `visible` binds to `bootIsToggleable`. This deliberately keeps the
toggle to the pair it understands, rather than offering a click that systemd is
known to refuse.

## The guard, which is the load-bearing decision

`tests/test_action.py`'s `test_the_prompt_is_never_suppressed` iterates
`LIFECYCLE_VERBS`:

```python
for verb in ("start", "stop", "restart"):
    self.assertNotIn("--no-ask-password", action.systemctl_command(verb), …)
```

The 2026-08-11 final review mutation-tested the flag guards and found this
family is what stands between the project and its signature failure mode:
re-adding `--no-ask-password` does not fail loudly, it silently converts every
authentication dialog into `permission denied`.

`enable` and `disable` do not belong in `LIFECYCLE_VERBS`. They are not
lifecycle operations, and both `plan()` and `optimisticStatusFor()` branch on
that tuple. But giving them their own tuple would let them **silently escape the
guard** — the guard would keep passing while two unguarded `systemctl` verbs
shipped beside it.

Therefore:

```python
LIFECYCLE_VERBS = ("start", "stop", "restart")
BOOT_VERBS = ("enable", "disable")
SYSTEMCTL_VERBS = LIFECYCLE_VERBS + BOOT_VERBS
```

`BOOT_VERBS` carries the semantics. `SYSTEMCTL_VERBS` is what the flag guard
iterates, and its contract is *everything that shells out to `systemctl`* rather
than *the lifecycle verbs*. A third verb category added later cannot slip past
it without deliberately editing the definition.

`systemctl_command` itself needs no change: it already accepts any verb and
returns `[SYSTEMCTL, verb, UNIT_NAME]` with no flag. `SYSTEMCTL_TIMEOUT_SEC` at
120 already budgets for a human reaching a fingerprint sensor.

## Optimistic feedback, and the trap it must not repeat

`AGENTS.md` trap #19 records that `optimisticStatus` and `expectedStop` look
like the same kind of bridge state but have **opposite failure costs**, and that
sharing one clearing rule broke one of them. The boot toggle adds a third such
value, so its failure cost is stated here rather than inferred later.

`runAction` gains a boot branch that must:

- **not** set `expectedStop`. Neither verb stops anything; setting it would arm
  the stopped-unexpectedly suppression for an event that cannot occur.
- **not** set `optimisticStatus`. That property holds a *run* status, and
  `optimisticStatusFor` must return `""` for both boot verbs.
- set a new `optimisticBootState`, which the switch's `checked` reads in
  preference to the polled value.

**`optimisticBootState`'s clearing rule follows `optimisticStatus`, not
`expectedStop`.** Clearing it early costs a brief knob snap-back to the previous
position — cheap and self-correcting — so it fails safe toward reality and
clears on the first authoritative snapshot after the action exits. Clearing it
late would leave the switch lying about system state, which is the expensive
direction. This is the opposite of `expectedStop`, whose early-clear cost is a
false critical alert and which therefore persists through a fixed ramp.

## Error handling

Unchanged and reused. A dismissed dialog produces the same
`Interactive authentication required` stderr as any other verb, which
`Model.actionErrorText` already maps to `not authorized — the authentication
prompt was dismissed or denied`. `Service.qml` clears `actionInProgress` in
`onRunningChanged`, which the existing spawn-failure guard guarantees fires, so
the switch recovers from a dismissal without a wedge.

`enable` on a `static` or `masked` unit cannot be reached through the UI, since
the switch is hidden in those states. Reached another way — a stale snapshot
racing a `systemctl mask` in a terminal — systemd's stderr falls through
`actionErrorText`'s passthrough branch to the error strip, truncated at 160
characters like any other unmapped failure.

## Documentation

- **`README.md` "Boot start"** (lines 112–131) currently prescribes
  `sudo systemctl enable ollama.service` and states the widget "cannot change it
  from the panel." Both invert. The manual command stays as a footnote for
  anyone who wants it, but stops being the instruction.
- **`README.md` Troubleshooting** line 229 — "Boot state is reported, not
  settable, from the widget" — is deleted.
- **`AGENTS.md` trap #28** gets a dated note recording that the follow-up it
  described has landed, keeping the trap itself, which is still a true
  polkit/systemd fact.
- **The `Panel.qml` comment** quoted at the top of this document is deleted, not
  amended. It documents a constraint that no longer exists anywhere.

## Testing

The standing safety rule holds: **no test may enable or disable
`ollama.service`.** Both verbs are asserted through `--dry-run` only, exactly as
the lifecycle verbs are.

Testable, roughly 6–8 new cases:

- `bootLabel` for `enabled`, `disabled`, `masked`, an unrecognised value, and
  empty input.
- `bootIsToggleable` true for exactly the two toggleable states, false for
  `masked`, `static`, unknown, and empty.
- Both boot verbs' constructed argv through `--dry-run`.
- `optimisticStatusFor` returns `""` for both boot verbs — this is the assertion
  that pins the trap #19 reasoning above, and it should fail loudly if someone
  later routes boot verbs through the run-status path.
- The widened flag guard, iterating `SYSTEMCTL_VERBS`.

Not testable in this repository, and to be stated as unverified until observed
on screen:

1. Flipping the switch raises the Omarchy dialog and, on authentication, the
   switch stays in its new position and the label updates on the next poll.
2. Dismissing the dialog returns the switch to its original position and puts
   the not-authorized message in the error strip.
3. A masked unit shows its state with no switch.

The 2026-08-11 spec recorded a hand-verification claim that turned out false and
had to be corrected; these three stay marked pending until someone looks.

## Known limitations

- Each toggle raises an authentication dialog, per trap #31. There is no
  retention to inherit — `systemctl` is its own short-lived polkit subject.
- Boot state is polled, not watched. A `systemctl enable` run in a terminal
  takes up to one poll interval to appear on the switch. This is the same
  limitation as run state and closing it is the same phase-2 item (D-Bus
  `PropertiesChanged`).
- `enabled-runtime` — enabled until reboot, via `systemctl enable --runtime` —
  is reported as its own state and is not toggleable, because flipping it would
  have to choose between making it permanent and clearing it, and neither is
  obviously what a click means.
