# AGENTS.md — extending Colophon

Colophon is an Ollama server status and control bar widget for the Omarchy
shell (Quickshell). This file is for an agent (or a human) changing the
code, not installing it — see `README.md` for that. Read
`docs/superpowers/specs/2026-08-10-colophon-design.md` first if you haven't;
it's the authoritative design record. `docs/verification-2026-08-10.md`
records what was actually checked empirically against the live target
machine, as distinct from what the spec merely asserts.

Both of the spec's originally-flagged-unverified claims were settled during
implementation: the prompt-less `/api/generate` load idiom and `keep_alive:
0` unload were confirmed against ollama 0.32.7 (`pacman` upgraded it from
0.32.6 mid-session), and `POST /api/generate` genuinely errors with HTTP 400
against an embedding model, which is why the two-endpoint routing exists at
all. The `manage-unit-files` scoping claim behind deferring the boot toggle
remains **deliberately unverified** — see trap #28, below, and the
verification doc's own section on it. Two findings recorded in the SDD
ledger but missing from the verification doc as of this file's writing have
since been added there: the post-`--check` `systemctl is-active`
confirmation that the probe is a genuine no-op, and the finding that
systemd resets `ExecMainStartTimestampMonotonic` and `MemoryCurrent` on
stop (trap #21, below) — which is why the `stopped` fixture legitimately
has both unset rather than being a stale capture.

## Layer map

```
colophon_collect.py   I/O only: systemctl show, HTTP GET, manifest scan -> one JSON
colophon_action.py    I/O only: verbs + --dry-run, no shell, no globbing
Model.js               pure: status -> glyph/color/label, bytes, countdowns
Service.qml            non-visual: properties, Process objects, timers, optimistic state
Panel.qml              render only: binds to Service and to Model.js output
```

Data flows one direction. `colophon_collect.py` prints one JSON object;
`Service.qml` spawns it as a `Process` and exposes the parsed result as
properties; `Panel.qml` binds to those properties and to pure `Model.js`
helpers. Nothing downstream reaches back upstream. Unlike galley, there is
no separate `*_normalize.py` module — `systemctl show` is `key=value` and
the Ollama API is clean JSON, so the pure transform functions live directly
in `colophon_collect.py`, taking plain dicts, and test identically without
a module boundary that would carry no weight.

**Two invariants, both load-bearing:**

1. **Python stays stdlib-only.** Permitted imports across both scripts:
   `datetime`, `glob`, `http.client`, `json`, `os`, `re`, `shlex`, `shutil`,
   `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`. No pip,
   ever — this is what lets the collector run with zero setup on a bare
   Omarchy install. `http.client` is there specifically for
   `http.client.HTTPException` (see trap #25); do not reach for `requests`
   or anything else that would need a virtualenv.
2. **`Model.js` stays pure and QML-safe.** No I/O, no QML imports, no
   timers, no state between calls. It is loaded by `Panel.qml` (`import
   "Model.js" as Model`) *and* by `node --test`, and the two engines do not
   accept the same syntax. Everything at top level must be a `var` or
   `function` declaration. Do **not** introduce: arrow functions (`=>`),
   spread (`...`), template literals (`` ` ``), `let`/`const`,
   `Object.assign`, `.includes(`, or `.endsWith(`. `tests/model.test.js` is
   exempt — it only ever runs under node, which is why you'll see modern JS
   there and nowhere in `Model.js` itself. `tests/test_cross_language.py`'s
   `ModelJsSyntaxTest` enforces both halves of this rule mechanically.

## Traps

These are the things that will cost you real time if you don't know
they're there. Where a guard test exists, it's named — if you're touching
related code and its guard isn't red, you probably haven't reintroduced the
bug. Several of these have no guard at all, because they're QML runtime
behavior or live-system facts outside what either test suite can reach; for
those, the guard is reading the comment at the site before you change it.

### Inherited from galley

| # | Trap | Guard |
|---|---|---|
| 10 | Quickshell's `Process` never emits `exited()` when the process fails to *spawn* (bad interpreter path, missing script) — only `runningChanged()` fires. A handler that only implements `onExited` latches whatever state it was tracking forever the first time a helper's path is wrong; this shipped as a Critical defect in galley, permanently disabling every action button. | The `onRunningChanged` handlers on `collectProc` and `actionProc` in `Service.qml`, plus the `actionExited` flag that lets `onRunningChanged` tell a normal exit from a failed spawn. No automated test reaches this — it's QML runtime behavior outside both suites. |
| 11 | Assigning `Process.command` while that `Process` is still `running` is a silent no-op — it doesn't queue, doesn't error, doesn't warn. Colophon has only one place that could fire this back-to-back today (the death-notification `notify-send`), but the failure mode if a second notification type is ever added is exactly galley's: the first call wins and the rest vanish silently. | `pendingNotification` + `sendNotification()` in `Service.qml` — a single pending slot, refilled from `notifyProc.onRunningChanged` only once the process has actually stopped. Deliberately not a queue, since one notification type can't produce a burst; add galley's full queue if you add a second type. |
| 12 | Values hand-duplicated across the Python/JS/QML boundary fail *silently* on a one-sided edit — a color that stops matching, a status string one side doesn't recognize, a setting whose fallback disagrees with the manifest. | `tests/test_cross_language.py` is the home for all of them: `StatusSetTest` (the status set Python emits vs. what `Model.js` maps), `ColorPaletteTest` (`Model.js`'s `COLOR_*` constants vs. the inlined hex literals in `Panel.qml`/`Service.qml`), `SettingsDefaultTest` (`Service.qml`'s `setting()` fallbacks vs. the manifest defaults), `KindRoutingTest` (the embed-family list exists only in Python), `UnitNameTest`, and `ShowPropertyTest`. Add to this file; don't start a second one. |
| 13 | Caller-owned diff state: `Model.js` holds nothing between calls, so anything needing memory across polls — "did I ask for this stop?" — has to live in the caller. | `expectedStop` in `Service.qml`. No automated guard exists; it survived three review rounds in this project (twice for a race that fired a false "stopped unexpectedly" alert on a stop the user had just clicked — see #18/#19 below). Read the comments around `settleTimer` and `handleOutput` before changing either. |

### Colophon's own

| # | Trap | Guard |
|---|---|---|
| 14 | The bar glyph (``, a Nerd Font microchip) sits in the Unicode Private Use Area. A PUA character does not survive every editing path — this project shipped a `Panel.qml` whose `barIcon` had silently become an empty string. The result: the file parsed, the component instantiated, its IPC handler registered, nothing logged a warning, and 131 tests passed, because nothing asserted the string was non-empty. The bar widget was simply invisible. | `BarGlyphTest.test_bar_icon_is_a_nonempty_escape` in `tests/test_cross_language.py`. It checks the escape's *format* only (non-empty `\uXXXX`), so it would pass just as happily on the wrong glyph — it guards against loss, not against a typo'd codepoint. Always write the glyph as a `\uXXXX` escape; never paste the literal character into either file. |
| 15 | `transient` — an entirely reasonable property or variable name — is a syntax error in QML's JS grammar, because QQmlJS still reserves the full ECMAScript 3 future-reserved-word list (`transient`, `volatile`, `synchronized`, `native`, `throws`, `goto`, `implements`, and others) as both identifiers *and* property names. Worse: **`qmllint` 1.0, as installed here, reports every parse error — this one and any other — as a bare exit 255 with no message at all.** `bin/test`'s QML gate tells you a file failed to parse; it never tells you why. | No guard test — this is a language-grammar fact, not a bug to pin. If `qmllint` fails with exit 255 and no output, bisect by commenting out blocks of the changed file, or reach for `qmlformat`, which reports parse errors with an actual message where `qmllint` here does not. |
| 16 | polkit refuses `--detail` arguments (`unit`, `verb`) from an unprivileged caller (`NotAuthorized: Only trusted callers ... can use CheckAuthorization() and pass details`), and a detail-less query can't match a rule scoped by both — it just reports the action's bare default. Running `pkcheck` as root doesn't help either: it answers whether *root* is authorized, a different question than whether the invoking user is. | `bin/install-privileges --check` doesn't use `pkcheck` at all; it exercises the grant for real with whichever verb is a safe no-op for the unit's current state. No automated test — it needs a live rule and root to install one — but confirmed live in `docs/verification-2026-08-10.md`: `stop` on an inactive unit succeeds with no prompt, `freeze` (not in the allow-list) is refused. |
| 17 | `org.freedesktop.systemd1.manage-units` gates *every* per-unit systemd D-Bus operation, not just the three lifecycle verbs — a rule scoped by `unit` alone also grants `kill` (an arbitrary signal to every process in the unit's cgroup), `set-property`, `reset-failed`, `freeze`/`thaw`, and `clean`. An earlier draft of the polkit rule scoped by unit only and called that "as narrow as polkit can express" — wrong, and caught by review before the rule was ever installed. | The rule's `verb` allow-list (`polkit/49-colophon-ollama.rules`) — systemd passes a `verb` detail alongside `unit`, so the rule checks both. No unit test covers a live polkit rule; guarded by the rule file itself plus the manual verification in `docs/verification-2026-08-10.md` (`freeze` refused while `stop` succeeds). |
| 18 | Concluding anything about `expectedStop` from a status *read* races the action that set it. Two distinct variants were found in sequence: reading `root.status` in the same tick as an async `refresh()` call only ever sees the *previous* poll; and gating on "any poll landed after the action" is satisfied by a poll already in flight when the action started, whose data predates it. Both cleared `expectedStop` before the real stop was ever observed, so the confirming poll fired a false "stopped unexpectedly" critical alert for a stop the user had just clicked. | No automated guard — the fix is architectural: the settle ramp reads no status at all, it just re-polls a fixed 6 times over 6 seconds and then unconditionally clears both flags. Race-free by construction, at the cost of `expectedStop` always persisting the full ~6s (a genuine death inside that window is suppressed — a stated, bounded trade). Read the comment above `settleTimer` in `Service.qml` before reintroducing any early-exit condition. |
| 19 | `expectedStop` and `optimisticStatus` look like the same kind of bridge-state but have opposite failure costs, and sharing one clearing rule broke one of them. Clearing `expectedStop` too early produces a false critical alert, so it must fail safe toward *suppression* — it only clears at the end of the fixed ramp. Clearing `optimisticStatus` too early costs at most a ~1s flicker back to the previous label, so it must fail safe toward *reality* — it clears on the first authoritative snapshot after the action completes. (It can never clear by "matching" the optimistic value: `colophon_action.py`'s lifecycle verbs block until systemd has already settled, so the transient `activating`/`deactivating` state is gone before Colophon ever polls it.) | No automated guard — two `Service.qml` properties with deliberately different clearing sites (`handleOutput` for `optimisticStatus`; `settleTimer`'s tick-6 branch and the action-error path for `expectedStop`). If you find yourself unifying their clearing logic "for consistency," don't — that's exactly the bug this trap exists to prevent. |
| 20 | `MemoryCurrent` has two distinct "unknown" sentinels from `systemctl show`, not one: the property can be entirely absent, or the literal string `[not set]` (memory accounting off in both cases), and separately the numeric value `18446744073709551615` (`UINT64_MAX`) means "accounting is on but nothing charged yet." Treating any of these as a real byte count renders a nonsense multi-exabyte figure. | `tests/test_collect.py`'s `MemoryBytesTest`: `test_absent_means_unknown`, `test_not_set_means_unknown`, `test_uint64_max_means_unknown`, `test_reads_a_real_value`. |
| 21 | `ExecMainStartTimestamp` is a locale-dependent, human-formatted date string — parsing it would mean depending on machine locale in a stdlib-only script. `ExecMainStartTimestampMonotonic` is the same fact as microseconds since boot, locale-free, combined here with `/proc/uptime` to get a wall-clock epoch. It's also reset to `0` by systemd on stop, along with `MemoryCurrent` going back to `[not set]` — confirmed directly on the target machine with a real start/stop cycle — which is why the `stopped` fixture legitimately has both fields unset rather than being a stale pre-start capture. | `tests/test_collect.py`'s `StartedAtTest` (four cases) and `UnitFromShowTest.test_shapes_the_stopped_fixture`; the start/stop confirmation is recorded in `docs/verification-2026-08-10.md`. |
| 22 | Ollama emits `expires_at` with nanosecond fractional seconds (nine digits); Python's `datetime.fromisoformat` accepts at most six, so an untruncated value raises instead of parsing. | `tests/test_collect.py`'s `ParseRfc3339Test.test_truncates_nine_digit_fractions`. |
| 23 | Per-model `sizeBytes` sums that model's own layers; `summary.installedBytes` sums each blob digest exactly once. Models share blobs (a base weight file reused across tags or quantizations), so the rows can — correctly — add up to more than the total. "Fixing" the totals to match the rows would remove the one property that makes the total meaningful. | `tests/test_collect.py`'s `ScanInstalledTest.test_unique_total_never_exceeds_the_sum_of_rows`. Documented in `README.md`'s Troubleshooting so it doesn't read as a bug to a user either. |
| 24 | Bytes are formatted in SI units (base 1000, `formatBytes` in `Model.js`), matching `ollama list`/`ollama ps` — but `du`/`df` and most file managers default to binary units (base 1024). The same byte count prints two different numbers depending which tool reports it; neither is wrong. | `tests/model.test.js`: `"formatBytes uses SI units so rows and totals are comparable"`. |
| 25 | `http.client.IncompleteRead` — what a server dying mid-response raises — is a subclass of none of `OSError`, `URLError`, `ValueError`, or `TimeoutError`. Catching only those lets a raw multi-line traceback escape to stderr, which the panel pipes straight into the error strip. This existed independently at three call sites (the collector's `api_get`, and the action script's `api_reachable` and `post_json`) and was closed at all three simultaneously so it couldn't be reintroduced at a fourth. | `tests/test_collect.py`'s `ApiGetFailureTest.test_a_truncated_response_does_not_raise` and `tests/test_action.py`'s `PostJsonTest.test_a_truncated_error_body_does_not_raise`, both against a real loopback `http.server` that truncates its body mid-write. |
| 26 | The model-name validator must anchor with `\Z`, not `$` — Python's `$` also matches immediately before a single trailing newline, so `"../../etc/passwd\n"` passed a `$`-anchored `MODEL_RE` that every other malicious case correctly rejected. Found by the test written specifically to assert the rejection, which failed against the first draft. | `tests/test_action.py`'s `ArgumentTest.test_a_shell_metacharacter_in_a_model_name_is_refused`, which includes the trailing-newline case explicitly. |
| 27 | `ollama.service` ships with `Restart=on-failure` and `RestartSec=3`. A crash can open and close a `failed` window narrower than the poll interval — the unit dies, systemd restarts it 3 seconds later, and a poll landing outside that gap never observes `failed` at all. | No guard — a real, inherent gap in a polling design, not a bug with a fix available today. Closing it is phase-2 item 4 (D-Bus `PropertiesChanged`), which replaces the timer trigger with a signal. |
| 28 | Extending the lifecycle actions to include `enable`/`disable` looks exactly as easy as `start`/`stop`/`restart` — same unit, same `systemctl`. It isn't: enable/disable go through `org.freedesktop.systemd1.manage-unit-files`, a *different* polkit action that systemd invokes with **no `unit` detail at all**. No rule can scope that action to `ollama.service`; granting it grants password-free enable/disable of *every* unit on the system. This is why the boot toggle is deferred to phase-2 item 1 rather than folded into the existing grant — and why that scoping claim is the one thing in this project still deliberately left unverified (see the verification doc). | No guard — a polkit/systemd fact, not project code. Read the design spec's "Why the boot toggle is not in the MVP" before attempting to add this. |

## How to add an action verb

The action surface is data-driven on purpose. To add one:

1. Add the verb to `LIFECYCLE_VERBS` or `MODEL_VERBS` in
   `scripts/colophon_action.py`.
2. Extend `plan()` so `--dry-run` prints the right steps for it.
3. Add a `--dry-run` assertion in `tests/test_action.py` (see the existing
   `PlanTest`/`DryRunTest` cases for the pattern).
4. Add a `Button` in `Panel.qml`, wired to
   `service.runAction(verb, target, kind)`.

Nothing else changes. `runAction` in `Service.qml` already owns
`actionInProgress`, `actionError`, the spawn-failure guard (trap #10), and
the post-action settle ramp (traps #18/#19).

## How to add a fixture state

Each state under `tests/fixtures/<name>/` is a directory, not a single
file:

- `systemctl.txt` — raw `systemctl show` output, parsed the same way the
  live collector parses it.
- `version.json` — present means the API answered `/api/version` (its
  contents become `api.serverVersion`); **its absence is the "API refused"
  signal**, not a special marker inside an otherwise-present file. A
  `stopped` fixture is simply a directory with no `version.json`.
- `ps.json` — the `/api/ps` response; only read when `version.json` is
  present.
- `models/` — a manifest tree for `scan_installed`, in the same layout as
  the real `/var/lib/ollama` (`manifests/<registry>/<namespace>/<name>/<tag>`
  files plus a `blobs/` directory). Optional per-state: if a state's own
  directory has no `models/`, `FixtureSource.models_root` falls back to the
  shared `tests/fixtures/models/`, so the inventory isn't duplicated once
  per state.
- `ollama-version.txt` — text containing `... version is X.Y.Z ...` for the
  client-version fallback; only consulted when `version.json` is absent.
- `no-binary` — an empty marker file whose mere *existence* means "no
  `ollama` binary on PATH," driving the `missing` status.

To drive the *live* panel through a fixture rather than a test: set
`COLOPHON_FIXTURE=tests/fixtures/<state>` in the environment that launches
the shell (Quickshell's `Process` inherits the parent environment, and
`Service.qml` never overrides it), then `omarchy restart shell`. Unset it
and restart again to go back to touching the real system.

## How to run things

- `./bin/test` runs everything: `jq` manifest validation, `bash -n` on the
  shell scripts, `qmllint` on every `*.qml`, `python3 -m unittest discover`,
  and `node --test tests/model.test.js`. As of this writing the Python
  suite is 109 tests and the JavaScript suite is 23, with 0 skips in
  either — read the counts off the actual output rather than trusting a
  number here, since both grow over time.

  **A green `./bin/test` proves `Panel.qml` and `Service.qml` *parse*, and
  nothing more.** `qmllint` cannot resolve Quickshell or Omarchy imports
  (`qs.Commons`, `qs.Ui`, `WidgetButton`, and so on are all unknown to it),
  so an unknown component, a typo'd property, or a reference to something
  that doesn't exist on `root.bar` all pass silently. QML *correctness* is
  verified by hand against the live shell, not by this suite. (See trap
  #15 for what a QML parse failure actually looks like here.)

- `./bin/dev-watch` installs once, then watches the source tree with
  `inotifywait` and reinstalls on every save, so
  `~/.config/omarchy/plugins/ssandys.colophon-dev/` always matches your
  working tree. It runs alongside a published `ssandys.colophon` install
  rather than fighting it, by rewriting the manifest id and `Panel.qml`'s
  `moduleName`/`ipcTarget` to `ssandys.colophon-dev` in the *deployed copy
  only* — the source tree stays canonical. Full reasoning in the design
  spec's "Repo layout" section.

- `COLOPHON_FIXTURE=tests/fixtures/<state> python3 scripts/colophon_collect.py`
  replays a recorded snapshot instead of touching systemd, the network, or
  the real model store — see "How to add a fixture state," above, for the
  live-panel version of this trick.

- `omarchy-shell shell rescanPlugins` forces the shell to rediscover
  plugins on disk. Use it after `bin/install` deploys a plugin id the
  shell hasn't seen before (a fresh dev install, or right after
  reinstalling from scratch) — the file watcher alone doesn't always catch
  a brand-new plugin directory. Note that `bin/install` itself never
  touches `shell.json`; the widget won't appear on the bar until you also
  enable and place it (`omarchy bar put ssandys.colophon-dev`, or the
  shell's settings panel).

- `omarchy restart shell` is the fix for the structure gotcha:
  Quickshell hot-reloads a plugin's *code* on save, but if you changed the
  widget's *structure* — a new property, a new binding, a new top-level QML
  element — the already-instantiated widget is not recreated to match, and
  you'll keep looking at the stale shape no matter how many times
  `dev-watch` reinstalls the files underneath it. This restarts the whole
  shell, not just Colophon, so expect the whole bar to flicker.

## The standing safety rule

**No test, script, or manual check may ever start, stop, or restart the
real `ollama.service`, and none may pull or delete a model.** Every
privileged verb is asserted through `--dry-run` only in the automated
suites. The one exception in this project's history is a small number of
explicit, logged manual checks — recorded in the SDD ledger under Tasks 2,
3, 7, and 11 — needed to settle the two claims the design spec originally
flagged as unverified (the polkit grant's real-world behavior, and the
load/unload API idiom). Those are done; don't add more without the same
level of deliberateness, and never as a side effect of "just checking
something works."

## Never edit `/usr/share/omarchy/`

It's overwritten wholesale on `omarchy update`. Anything you put there
disappears without warning at the next update. Reading it to understand how
the shell's `PluginRegistry`, `WidgetButton`, or other shared components
work is fine, and often the fastest way to answer a "how does this actually
behave" question — just don't write there.

## Phase 2 — documented, not built

The design spec's "Phase 2" section lists what was deliberately left out of
this MVP:

1. **Boot toggle** (`enable`/`disable`). Needs a second privilege mechanism
   — a sudoers drop-in scoped to two exact command strings — because
   polkit cannot scope `manage-unit-files` (trap #28).
2. **Journal log tail.** `journalctl -u ollama.service` is readable
   unprivileged, so this is scope, not capability. The failure *reason* is
   already in the MVP via `Result`.
3. **Model management: pull, delete, rename.** Feasible with **no** extra
   privilege — the server does the writing as user `ollama`. Deferred for
   the progress and destructive-confirmation UI, not for permissions.
4. **D-Bus `PropertiesChanged`** on the unit, replacing the systemd half of
   polling with a signal. Closes the gap in trap #27.
5. **Idle nudge** — notify when the server has run with zero models loaded
   for N minutes. Considered for the MVP and cut; the most likely first
   addition.
6. **`/api/tags` for the installed list** when the server is reachable, if
   the disk scan ever disagrees with it.
7. **Middle-click toggle-to-stop**, if the asymmetric binding proves more
   confusing in practice than it reads on paper.

If you're fixing a bug and reach for one of these as part of the fix, stop
— it's very likely the bug has been misdiagnosed as a missing feature.
These were deferred deliberately, not accidentally.
