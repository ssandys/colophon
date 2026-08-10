# Colophon — Ollama server status and control for the Omarchy shell

**Date:** 2026-08-10
**Status:** Approved, ready for planning
**Plugin ID:** `ssandys.colophon`
**Repo:** `~/Src/colophon/` → deploys to `~/.config/omarchy/plugins/ssandys.colophon/`

## Purpose

A bar widget for the Omarchy shell that shows whether the local Ollama server is
running, starts and stops it, and loads a model on demand.

The problem it solves: Ollama is a 19 GB service that peaked at ~650 MB of
memory over its last 14-hour run, and you want it up only while you're actually
using a model. Its unit is disabled on this
machine, so today "use a local model" means opening a terminal, remembering the
unit name, authenticating, waiting for the port to bind, and then warming the
model from a second command. Colophon makes that one click, and makes "is it on,
and what is it holding?" answerable at a glance.

**Primary job: an on-demand switch.** Every design tie is broken in favor of
that. Health monitoring, resource accounting, and model launching all appear,
but they are consequences of the switch, not co-equal goals.

Predecessors: `ssandys/ollama-system-tray` (a Go/systray waybar tray doing the
same three verbs) and `ssandys/galley` (the CUPS bar widget this borrows its
architecture, conventions, and hard-won traps from).

## Verified environment

Every claim below was checked on the target machine on 2026-08-09/10, not
assumed. Several of them overturned an earlier design assumption.

| Fact | Value | Consequence |
|---|---|---|
| `ollama` binary | `/usr/bin/ollama`, client `0.32.6` at spec time, upgraded to `0.32.7` mid-implementation (pacman, 2026-08-10 11:18) | `ollama --version` reports the client version **even with the server down** — the header is never blank. Nothing in the design keys off the version, so the upgrade changed nothing but these examples |
| Unit | `/usr/lib/systemd/system/ollama.service`, `User=ollama` | It is a **system** unit; every lifecycle verb needs privilege. Galley needed none — `cupsdisable` worked unauthenticated |
| Unit state | `disabled`, `inactive (dead)` | Not meant to run at boot. This is the usage signal behind "on-demand switch" |
| polkit `manage-units` | `auth_admin_keep` | Start/stop/restart require authentication by default |
| polkit **agent** | **none running** (only `polkitd`; no `hyprpolkitagent`, `polkit-gnome`, `lxqt-policykit`, `mate-polkit` installed) | `pkexec` from a QML `Process` has no tty and no agent — it fails outright. The Go tray's `pkexec systemctl` approach **does not port** |
| polkit `manage-unit-files` | separate action, no `unit` detail from systemd | enable/disable **cannot** be scoped to one unit by a polkit rule. This removed the boot toggle from the MVP |
| `journalctl -u ollama.service` | works unprivileged (user is in `wheel`) | Log tail is *available* — deferred by scope, not blocked |
| `systemctl show` properties | `UnitFileState`, `Result`, `ExecMainStartTimestamp`, `NRestarts`, `MemoryCurrent` all readable unprivileged | Boot state, failure reason, uptime, and RSS come from **one** call — no `is-enabled`, no `journalctl` |
| `/var/lib/ollama/manifests`, `blobs` | world-readable, 39 blobs, 19 GB, 9 models | The installed-model list works with the server **stopped** and without root |
| Manifest JSON | carries per-layer `size` | Model sizes need no `stat` calls |
| Config blob JSON | `model_family`, `model_type`, `file_type` | Parameter size, quantization, and family all readable from disk. `nomic-embed-text` → `model_family: nomic-bert`, which makes embedding-vs-generate routing a lookup, not a guess |
| API when stopped | `connect(127.0.0.1:11434)` refused in **0 ms** | Probing the API every poll is free, so foreign-instance detection costs nothing |
| GPU | AMD Radeon 880M/890M integrated; no `nvidia-smi` | GPU-vs-CPU split must come from `/api/ps`, not a GPU tool |
| systemd | 261 | — |

## Architecture

Five files, each independently readable. The layer map:

```
scripts/colophon_collect.py   I/O only: systemctl show, HTTP GET, manifest scan → one JSON
scripts/colophon_action.py    I/O only: verbs + --dry-run
Model.js                      pure: status → glyph/color/label, bytes, countdowns
Service.qml                   non-visual: properties, Process objects, timers, optimistic state
Panel.qml                     render only
```

Data flows one direction. `colophon_collect.py` prints one JSON object;
`Service.qml` spawns it as a `Process` and exposes the parsed result as
properties; `Panel.qml` binds to those properties and to pure `Model.js`
helpers. Nothing downstream reaches back upstream.

### Three deliberate deviations from galley

**1. `Service.qml` exists from day one.** Galley put its state machine —
mutable properties, three `Process` objects, timers, and every accumulated bug
fix — in the first ~245 lines of a 777-line `Panel.qml`, and now carries
[galley#1](https://github.com/ssandys/galley/issues/1) to extract it. Colophon
is born split, so the hard part of the widget can be read and reviewed without
scrolling past layout.

In-tree precedent is `/usr/share/omarchy/shell/plugins/panels/dropbox/`, which
is structurally what Colophon is: `status.py` (128 lines) + `Service.qml` (277)
+ `Model.js` (137) + `Panel.qml` (539). Two of its patterns port directly:

- **Optimistic state** (its `_desired` property) — the UI reacts the instant you
  click rather than waiting for the daemon to settle. Correct for a Start/Stop
  button on a service that takes ~1s to bind its port.
- **`settleTimer`** — re-poll a few times after an action instead of waiting for
  the next scheduled tick.

And one thing it does that Colophon must **not** inherit: all three of its
`Process` objects handle only `onExited`. That is galley trap #10 — Quickshell's
`Process` never emits `exited()` when the process fails to *spawn*, only
`runningChanged()`, which in galley permanently disabled every action button the
first time a helper path was wrong. Colophon's `Service.qml` carries galley's
`onRunningChanged` guard from the start.

**2. No `colophon_normalize.py`.** Galley needs a separate pure-transform module
because CUPS plists carry nine documented quirks. `systemctl show` is
`key=value` and the Ollama API is clean JSON. The pure functions live inside the
collector taking plain dicts, so they test identically without a module
boundary that carries no weight.

**3. Actions in Python, not bash.** `galley_action.sh` was pure command-mapping.
Colophon's are not: `warm <model>` must start the unit, poll `/api/version`
until it answers, then POST. In bash that means a `curl` dependency plus a
hand-rolled retry loop; in Python it is `urllib`, stdlib-only, and `--dry-run`
still exercises the whole verb. Keeping the multi-step orchestration inside one
*blocking* script — rather than chaining `Process` objects in QML — means the
panel shows `starting…` until one process exits, with no QML state machine.

### Two invariants, both load-bearing

Carried over from galley for the same reasons.

1. **Python stays stdlib-only.** Permitted imports across both scripts:
   `datetime`, `glob`, `json`, `os`, `re`, `shlex`, `shutil`, `subprocess`,
   `sys`, `time`, `urllib.error`, `urllib.request`. (`re`, `shlex`, and `time`
   were added during implementation — `re` for the RFC 3339 fraction truncation
   and the model-name validator, `shlex` for the unit's quoted `Environment=`,
   `time` for the API timeout and the warm deadline. All stdlib, so the
   no-pip invariant is intact.) No pip, ever — this is what lets the collector
   run with zero setup on a bare Omarchy install.
2. **`Model.js` stays pure and QML-safe.** No I/O, no QML imports, no timers, no
   state between calls. It is loaded by `Panel.qml` (`import "Model.js" as
   Model`) *and* by `node --test`, and the two engines do not accept the same
   syntax. Everything at top level must be `var` or `function`. Do **not**
   introduce: arrow functions, spread, template literals, `let`/`const`,
   `Object.assign`, `.includes(`, or `.endsWith(`. The test file is exempt — it
   only runs under node.

## Collector

`scripts/colophon_collect.py` is a short-lived process that prints one JSON
object to stdout and exits. Per poll:

1. `systemctl show ollama.service -p LoadState,ActiveState,SubState,Result,UnitFileState,ExecMainStartTimestamp,NRestarts,MemoryCurrent,Environment`
   — **one** call, 5s timeout. `UnitFileState` supplies boot state (no separate
   `is-enabled`), `Result` supplies the failure reason (no `journalctl`), and
   `Environment` supplies `OLLAMA_MODELS` so the model store is discovered from
   the unit rather than hardcoded (fallback `/var/lib/ollama`).
2. `GET {apiBase}/api/version`, 2s timeout. Refused-in-0ms when stopped.
3. `GET {apiBase}/api/ps` — only when step 2 answered.
4. Scan `$OLLAMA_MODELS/manifests/**` and read each manifest plus its config
   blob. Nine small files here; sub-millisecond.
5. `ollama --version`, 3s timeout — only when step 2 did **not** answer, so the
   header can show a client version instead of a blank.
6. Resolve `status`, emit JSON.

Its interface: `colophon_collect.py [--api-base URL]`, plus the
`COLOPHON_FIXTURE` environment variable (below). `Service.qml` passes the
manifest's `apiBase` through as `--api-base`; the default lives in exactly one
place, the manifest, and the script's own fallback matches it.

**The installed list always comes from disk, never from `/api/tags`,** even when
the server is running. `/api/tags` is arguably more authoritative, but two code
paths producing two possibly-different counts for the same list is a worse
property than one path that is identical in every state. Switching to
`/api/tags` when reachable is a phase-2 refinement if the disk scan ever proves
wrong.

`MemoryCurrent` is unset or `18446744073709551615` when memory accounting is
off; treat both as unknown and omit the figure rather than rendering a
nonsense number.

### Output schema

```json
{
  "schema": 1,
  "status": "running | starting | stopping | stopped | failed | foreign | missing",
  "error": null,
  "unit": {
    "name": "ollama.service",
    "loadState": "loaded",
    "activeState": "inactive",
    "subState": "dead",
    "unitFileState": "disabled",
    "result": "success",
    "startedAt": null,
    "nRestarts": 0,
    "memoryBytes": null
  },
  "api": {
    "base": "http://127.0.0.1:11434",
    "reachable": false,
    "serverVersion": null,
    "clientVersion": "0.32.6",
    "latencyMs": null
  },
  "loaded": [{
    "name": "llama3.2:3b",
    "sizeBytes": 3400000000,
    "vramBytes": 3400000000,
    "processor": "gpu",
    "gpuPercent": 100,
    "expiresAt": 1786228376,
    "parameterSize": "3.2B",
    "quantization": "Q4_K_M"
  }],
  "installed": [{
    "name": "deepseek-r1:latest",
    "sizeBytes": 5225375512,
    "family": "qwen3",
    "parameterSize": "8.2B",
    "quantization": "Q4_K_M",
    "kind": "generate",
    "modifiedAt": 1739646000
  }],
  "summary": {
    "loadedCount": 0,
    "loadedBytes": 0,
    "installedCount": 9,
    "installedBytes": 20401094656
  }
}
```

`processor` is derived the way the `ollama ps` CLI derives its `PROCESSOR`
column: `size_vram == 0` → `cpu`; `size_vram == size` → `gpu`; otherwise
`split` with `gpuPercent = round(100 * size_vram / size)`. `expires_at` arrives
from the API as RFC 3339 and is converted to an epoch here so `Model.js` stays
free of date parsing.

`kind` is `embed` when `model_family` is in a known embedding set (`bert`,
`nomic-bert`, `xlm-roberta`), else `generate`. See "Warming and unloading".

`summary.installedBytes` sums **unique blob digests**; per-model `sizeBytes`
sums that model's own layers. Models share blobs, so the rows can add up to
more than the total. That is correct, and it is documented in the README
because it looks like a bug otherwise.

## Status resolution

Resolved **once**, in Python. Galley trap #12 is hand-duplicated logic across
Python and JS failing silently on a one-sided edit; `Model.js` therefore only
maps a `status` string to a glyph, color, and label, and a cross-language test
asserts the JS map covers exactly the set Python can emit.

| `ActiveState` | `/api/version` | `status` |
|---|---|---|
| `active` | answers | `running` |
| `active` | refused | `starting` |
| `activating` | either | `starting` |
| `deactivating` | either | `stopping` |
| `inactive` | **answers** | `foreign` |
| `failed` | **answers** | `foreign` |
| `inactive` | refused | `stopped` |
| `failed` | refused | `failed` |
| `LoadState=not-found`, or no `ollama` binary | either | `missing` |

`foreign` is the load-bearing state — a hand-run `ollama serve`, or anything
else bound to `:11434`. Stop and Restart are **disabled** in it, with the reason
shown, so the widget never claims to have stopped something it cannot.

`active` + refused is usually the ~1s bind window, but it is also what a wedged
server looks like. Rather than invent a collector state for that,
`Service.qml` tracks time-in-state and `Model.js` relabels `starting` to
"started, but not answering on :11434" past 15 seconds. Presentation-only; the
collector stays honest.

## Actions

`scripts/colophon_action.py` always emits a fully-qualified, fixed-shape
command — no shell, no globbing, and no user-interpolated argument except a
model name validated against `^[A-Za-z0-9._:/-]+$`.

| Verb | What it does | Privileged |
|---|---|---|
| `start` | `systemctl start ollama.service` | yes |
| `stop` | `systemctl stop ollama.service` | yes |
| `restart` | `systemctl restart ollama.service` | yes |
| `warm <model>` | `start` if not running → poll `/api/version` to a 20s deadline → load (below) | only the implicit start |
| `unload <model>` | `POST /api/generate {model, keep_alive: 0}` | no |

Every verb accepts `--dry-run`, which prints the plan and exits 0 without
performing it, and `--api-base URL`, matching the collector.

`systemctl` is invoked **non-interactively** so a missing grant fails
immediately rather than hanging on a password prompt with no tty. The panel maps
that specific stderr ("Interactive authentication required") to
`permission denied — the polkit rule is missing; run bin/install-privileges (see
README)`, not a raw dump. The message deliberately carries **no absolute path**:
`bin/` ships in a published `omarchy plugin add` clone but is excluded from the
dev rsync, so the script lives in a different place in each case and the README
gives both.

### Warming and unloading

Ollama has no dedicated load endpoint. A prompt-less generate is the documented
idiom, and `keep_alive: 0` is the unload:

```
POST /api/generate  {"model": M, "keep_alive": "<keepAliveMinutes>m"}   # load
POST /api/generate  {"model": M, "keep_alive": 0}                       # unload
POST /api/embed     {"model": M, "input": "", "keep_alive": ...}        # kind == "embed"
```

**Verified against 0.32.7 on this machine, 2026-08-10.** (The table above records 0.32.6 because that was the installed version when this spec was written; pacman upgraded it to 0.32.7 at 11:18, before the verification ran. The idiom was therefore confirmed against 0.32.7.) All three claims held:
a prompt-less `POST /api/generate` returns `done_reason: "load"` and the model
then appears in `/api/ps`; `keep_alive: 0` returns `done_reason: "unload"` and
`/api/ps` goes back to `{"models":[]}`; and `POST /api/generate` against
`nomic-embed-text` **does** error while `POST /api/embed` succeeds for it. The
two-endpoint routing below is therefore necessary, not defensive.

Embedding models take `/api/embed`, not `/api/generate` (`nomic-embed-text` is
installed here, so this is a live case, not a hypothetical). Routing uses the
`kind` field the collector derives from `model_family`. An unrecognized family
falls through to `generate`, and the API's own error is surfaced inline on the
row rather than failing silently.

### The privilege grant

One file, `polkit/49-colophon-ollama.rules`, installed to
`/etc/polkit-1/rules.d/` by `bin/install-privileges` with the invoking user's
name interpolated:

```javascript
polkit.addRule(function (action, subject) {
  if (subject.user !== "USER") return;
  if (action.id !== "org.freedesktop.systemd1.manage-units") return;
  if (action.lookup("unit") !== "ollama.service") return;
  var verb = action.lookup("verb");
  if (verb === "start" || verb === "stop" || verb === "restart") {
    return polkit.Result.YES;
  }
});
```

`manage-units` carries both a `unit` and a `verb` detail, so this grants exactly
one user password-free start/stop/restart of exactly one unit, and nothing else.
Every other path returns `undefined`, so the rule abstains rather than blocking —
it never overrides a system default for anything it does not permit.

**Correction, 2026-08-10.** An earlier draft of this section scoped by `unit`
alone and claimed that was "as narrow as polkit can express." That was wrong, and
a code review caught it before the rule was installed. `manage-units` is the
single action gating *every* per-unit systemd D-Bus operation, so a unit-only
rule also permits `kill` (an arbitrary signal to every process in the unit's
cgroup), `set-property`, `reset-failed`, `freeze`/`thaw`, and `clean` on that
unit. Verified on this machine: `clean` is inert here, because
`StateDirectory`, `CacheDirectory`, `RuntimeDirectory`, `LogsDirectory`, and
`ConfigurationDirectory` are all empty on `ollama.service` and the 19 GB model
store is reachable only through `WorkingDirectory`, which `clean` does not
touch — but `kill` is not inert, and none of it belongs in a grant whose stated
purpose is three verbs. The `verb` allow-list is what makes the description true.

`bin/install-privileges` requires root, refuses to run if `$SUDO_USER` is unset
(otherwise it would grant to `root`), and prints what it wrote.

### `--check` cannot use `pkcheck`

**Corrected 2026-08-10, empirically.** Two earlier drafts of this section
specified a `pkcheck`-based `--check` needing no root. That is not
implementable. polkit refuses details from an unprivileged caller:

```
NotAuthorized: Only trusted callers (e.g. uid 0 or an action owner)
can use CheckAuthorization() and pass details
```

So `--check` is trapped: to match a detail-scoped rule it must pass `unit` and
`verb` details, and passing details requires uid 0. A detail-less query cannot
match the rule and merely reports the action's default. Running it as root does
not help either — it would ask whether *root* is authorized, not the user.

`--check` therefore **exercises the grant for real, using the verb that is a
no-op for the unit's current state**: `stop` when the unit is already
`inactive`, `start` when it is already `active`. The polkit check runs in
earnest while the unit's state is unchanged. From any other state
(`activating`, `deactivating`, `failed`) no verb is a safe no-op, so `--check`
reports that it could not verify rather than probing.

Verified on this machine after installing the rule, with the unit inactive:

| Command | Result | What it proves |
|---|---|---|
| `systemctl --no-ask-password stop ollama.service` | exit 0, no prompt, still inactive | the grant works, and the probe is a true no-op |
| `systemctl --no-ask-password freeze ollama.service` | refused: "requires interactive authentication" | the verb allow-list really excludes non-listed verbs, and the probe is sensitive to polkit rather than passing vacuously |

**Why the boot toggle is not in the MVP.** `enable`/`disable` go through
`org.freedesktop.systemd1.manage-unit-files`, a different action that systemd
invokes with **no unit detail** — a polkit rule cannot scope it, so granting it
would grant password-free enable/disable of every unit on the system. That is
materially broader than the grant above. The alternatives (a sudoers drop-in
scoped by exact command string, or moving all verbs to sudoers) were considered
and rejected for the MVP in favour of keeping the grant provably narrow. The
panel therefore **reports** boot state from `UnitFileState` but cannot change
it; the README gives the one-time `sudo systemctl enable ollama` command.

**Status of that claim, 2026-08-10: still unverified, and deliberately so.**
Distinguishing "systemd passes no `unit` detail with `manage-unit-files`" from
"a detail is passed but our rule does not cover that action" requires
installing a temporary root-owned rule that *does* grant `manage-unit-files`
scoped by unit, and seeing whether it matches. The cheap proxies cannot tell
the two apart, and `pkcheck` is unavailable for this as an unprivileged caller
for the reason given above. That test was judged not worth installing a
deliberately over-broad rule on a working machine.

The MVP decision does not depend on it. The installed grant demonstrably
excludes everything outside its verb allow-list — `freeze` is refused while
`stop` succeeds — so `enable`/`disable` are not reachable through it either
way. If someone later wants the boot toggle, running that experiment is the
first step, not a formality.

## UI

### Bar widget

Glyph `` — U+F2DB, Nerd Font microchip — always visible. Deliberately a BMP
codepoint so it is a plain QML escape (`""`) like galley's U+F02F `` — the nicer
`nf-md-brain` is U+F09D1 and would need a surrogate pair in QML.

| `status` | Glyph color | Badge |
|---|---|---|
| `running` | `bar.foreground` | loaded-model count, when > 0 |
| `stopped` | dimmed (`Qt.darker(fg, 1.45)`) | none |
| `starting` / `stopping` | amber | none |
| `foreign` | amber | loaded-model count |
| `failed` / `missing` | red | none |

Galley's rule holds: the badge color never varies, severity is carried by the
glyph color. A red glyph with a badge means "models loaded, and something is
wrong".

Tooltip: `ollama 0.32.6 · up 14m · llama3.2:3b loaded (GPU)` when running,
`ollama stopped · 9 models, 19 GB` when not.

Click opens the panel. **Middle-click is asymmetric: it starts Ollama when
stopped, and refreshes otherwise.** Galley and `docker-monitor` both bind
middle-click to refresh, but the primary job here is a switch, and a start is
harmless where a stop could kill a running generation on a stray click. Revisit
if the asymmetry is more confusing in practice than it reads on paper.

### Panel

Running, and stopped:

```
  Colophon                          ollama 0.32.6        │  Colophon                    ollama 0.32.6 client
 ─────────────────────────────────────────────────       │ ─────────────────────────────────────────────────
   ● running · up 14m · 4.1 GB            1 loaded       │   ○ stopped                    disabled at boot
   [ stop ]  [ restart ]           disabled at boot      │   [ start ]
 ─────────────────────────────────────────────────       │ ─────────────────────────────────────────────────
  LOADED                                                 │  INSTALLED · 9 · 19 GB      click a model to run
   llama3.2:3b     3.4 GB   GPU   expires 4:12   ✕       │   deepseek-r1:latest                    5.2 GB
 ─────────────────────────────────────────────────       │   gemma3:4b                             3.3 GB
  INSTALLED · 9 · 19 GB                                  │   qwen3:0.6b                            522 MB
   deepseek-r1:latest                      5.2 GB        │   nomic-embed-text:latest               274 MB
   gemma3:4b                               3.3 GB        │   …
 ─────────────────────────────────────────────────       │ ─────────────────────────────────────────────────
           r refresh · esc closes                        │           r refresh · esc closes
```

Foreign, failed, and missing:

```
  ◐ running — not managed by systemd        ✕ failed · exit-code · stopped 3m ago
  Started outside ollama.service.           [ start ]  [ restart ]
  [ stop ]  [ restart ]  ← dim, disabled
                                            ✕ ollama.service not found
                                            Install it: omarchy pkg add ollama
```

- `LOADED` is **hidden** when stopped (nothing true to say) and reads a dim "No
  models loaded" when running with none.
- `INSTALLED` is always present. It comes from disk, so it survives the server
  being down — which is what makes the stopped panel useful rather than an empty
  box with one button. It scrolls within a capped height, like galley's queue.
- Clicking an installed row **warms** it, starting the server first if needed.
  That can take up to 20s: `Service.qml` sets
  `actionInProgress = "warm:<model>"`, the row reads `warming…`, and the status
  line reads `starting…`.
- The `expires` countdown ticks from a 1-second `Timer` that runs **only while
  the panel is open**, so it re-renders without re-polling anything.
- `failed` names its reason from `Result` (`exit-code`, `signal`, `oom-kill`,
  `timeout`, `core-dump`). The deferred part is the log *text*, not the reason.
- Row detail (`family`, `parameterSize`, `quantization`) is in the schema and
  available from disk; the row shows name and size, and the rest goes in its
  tooltip.

Keyboard: `r` refreshes, `esc` closes. No shortcut is bound to a privileged
verb.

## Polling

Three regimes, where galley has two — "closed but running" needs to track the
badge, while "closed and stopped" needs nothing.

| Condition | Interval |
|---|---|
| Panel open | `pollIntervalOpenSec` (2) |
| Closed, `running` or `foreign` | `pollIntervalRunningSec` (10) |
| Closed, `stopped` / `failed` / `missing` | `pollIntervalIdleSec` (30) |
| Closed, `starting` / `stopping` | `pollIntervalRunningSec` — the transient will resolve, and it is not worth a fourth key |
| Immediately after an action | 1s ramp, up to 6 ticks or until `status` leaves a transient state |

No startup ramp. Dropbox needs one because `dropboxd` respawns at boot; this
unit is disabled, so a single poll at shell start is the truth. A widget that
starts while the unit happens to be `activating` converges within one
running-cadence tick.

## Error handling

The key distinction: `stopped`, `failed`, and `missing` are **states**, not
errors. They render normally with no error styling. An error strip means the
widget itself could not find out.

| Condition | Behavior |
|---|---|
| Collector exits non-zero | Error strip with stderr tail; **last-known snapshot retained** |
| Malformed JSON | Same; never clears a good previous snapshot |
| `systemctl show` fails | Error strip — D-Bus being broken is genuinely wrong |
| API times out or refuses | `api.reachable = false`, feeds status resolution; not an error |
| Action denied | Mapped to `permission denied — run sudo ./bin/install-privileges` |
| Action fails otherwise | Inline error under the action row, with stderr |
| Helper fails to spawn | `onRunningChanged` guard clears `actionInProgress` (galley trap #10) |
| `warm` on a mis-routed model | The API's own error, inline on the row |

The retain-last-known rule matters for the same reason it does in galley: a
transient failure must not blank the panel.

## Notifications

One event, one toggle.

| Event | Trigger | Default |
|---|---|---|
| Service died | `status` became `failed`, **or** went `running` → `stopped` with no stop in flight | on |

`foreign` → `stopped` deliberately does **not** notify. Someone quitting their
own hand-run `ollama serve` is not our service dying, and the transition is
excluded because the rule requires the previous status to be `running`.

Distinguishing "it died" from "I stopped it" needs caller-owned state:
`Service.qml` sets an `expectedStop` flag when a stop or restart is issued and
clears it when the settle ramp ends. That state deliberately lives in
`Service.qml`, not `Model.js`, because `Model.js` holds nothing between calls —
this is galley trap #13's lesson applied up front.

Suppressed on first load, so shell startup is silent. Galley trap #11
(assigning `Process.command` while it is still running is a silent no-op) is
guarded with a single pending slot rather than galley's full queue, since one
notification type cannot produce a burst.

## Configuration (manifest schema)

| Key | Type | Default | Range | Effect |
|---|---|---|---|---|
| `pollIntervalOpenSec` | integer | 2 | 1–30 | Poll cadence while the panel is open |
| `pollIntervalRunningSec` | integer | 10 | 5–120 | Cadence while closed and the server is up |
| `pollIntervalIdleSec` | integer | 30 | 5–300 | Cadence while closed and the server is down |
| `keepAliveMinutes` | integer | 5 | 1–120 | `keep_alive` sent when warming a model |
| `apiBase` | string | `http://127.0.0.1:11434` | — | Where to probe for the API |
| `showInstalledModels` | boolean | true | — | Show the installed-model list |
| `notifyServiceDied` | boolean | true | — | Notify when the service dies unexpectedly |

`apiBase` exists because a custom `OLLAMA_HOST` would otherwise make a live
server read as `stopped`. The README states that the two must be kept in sync.

## Testing

**Standing rule, no exceptions** — the analogue of galley's "no test may submit
a job that reaches paper": **no test, script, or manual check may start, stop,
or restart the real `ollama.service`, and none may pull or delete a model.**
Every privileged verb is asserted through `--dry-run` only.

- **Status table test.** Every (`ActiveState`, `SubState`, api-reachable) triple
  mapped to its expected `status`. That table is the widget's core logic and
  gets tested as a table, not as scattered cases.
- **Fixture replay.** `COLOPHON_FIXTURE=tests/fixtures/<state>` makes the
  collector read `systemctl.txt`, `version.json`, `ps.json`, and a `manifests/`
  tree from a directory instead of performing any I/O. This is the main reason
  the collector is a standalone process: it drives the live panel through
  `failed`, `foreign`, `starting`, and `missing` without touching the real
  service. Fixture states to author: `running`, `stopped`, `starting`,
  `stopping`, `failed`, `foreign`, `missing`, and `wedged`. The last is a
  *fixture* name, not an eighth status — it is `active` with the API refused, so
  the collector still emits `starting` and it exercises the 15-second relabel in
  `Model.js`.
- **`foreign` has a real capture path.** `ollama serve` in a terminal as your
  own user reads `/var/lib/ollama` fine (blobs are world-readable), so that
  state can be reproduced live rather than only synthesized — worth doing once
  to confirm the disabled Stop/Restart buttons behave.
- **Derivation tests** on plain dicts: `processor`/`gpuPercent` from
  `size`/`size_vram`, unique-digest size summing, `kind` from `model_family`,
  RFC 3339 → epoch, and the `MemoryCurrent` unknown sentinels.
- **Action `--dry-run` assertions** for every verb, following galley's
  `DryRunTest` pattern, including that `warm` on an `embed`-kind model targets
  `/api/embed`.
- **Cross-language guard** (`tests/test_cross_language.py`): the `status` set
  Python can emit must equal the set `Model.js` maps, and the color constants in
  `Model.js` must match the hex literals in `Panel.qml`. Both fail silently on a
  one-sided edit, which is exactly galley trap #12.
- **`node --test tests/model.test.js`** for byte formatting, countdown
  formatting, tooltip strings, the 15s `starting`-relabel, and glyph/color
  mapping.
- **`bin/test`** runs `jq` manifest validation, `python3 -m unittest discover`,
  `node --test`, and `qmllint` on every `*.qml`, carrying galley's caveat
  verbatim: `qmllint` cannot resolve Quickshell or Omarchy imports, so a green
  run proves the QML *parses* and nothing more. QML correctness is verified by
  hand against the live shell.

## Repo layout

```
~/Src/colophon/
├── manifest.json
├── Panel.qml
├── Service.qml
├── Model.js
├── scripts/
│   ├── colophon_collect.py
│   └── colophon_action.py
├── polkit/
│   └── 49-colophon-ollama.rules
├── bin/
│   ├── install              # dev deploy → …/plugins/ssandys.colophon-dev/
│   ├── install-privileges   # root; writes the polkit rule; --check verifies
│   ├── dev-watch            # install once, then inotifywait + reinstall on save
│   └── test
├── tests/
│   ├── test_collect.py
│   ├── test_status.py
│   ├── test_action.py
│   ├── test_cross_language.py
│   ├── model.test.js
│   └── fixtures/{running,stopped,starting,stopping,failed,foreign,missing,wedged}/
├── docs/
├── README.md
├── AGENTS.md
└── LICENSE                  # MIT
```

### The dev install, reused from galley

Colophon adopts galley's dev-install pattern verbatim, because it solves a
problem that will otherwise bite in exactly the same way. Users install the
published plugin with `omarchy plugin add <git url> --enable`; `bin/install`
exists **only** to deploy the working tree under a separate dev identity, so it
runs alongside the published copy instead of fighting it.

1. `rsync -a --delete` the source tree to
   `~/.config/omarchy/plugins/ssandys.colophon-dev/`, excluding `.git`,
   `tests/`, `bin/`, `docs/`, `polkit/`, `__pycache__`, and the markdown files.
2. Rewrite, **in the deployed copy only**, `ssandys.colophon` →
   `ssandys.colophon-dev` in `manifest.json` and `Panel.qml` (which is where
   `moduleName` and `ipcTarget` live), plus the display name → `Colophon (dev)`.
   The source tree stays canonical and `git status` stays clean.
3. Both substitutions must **tolerate already-rewritten input**, so a run that
   finds stale output in the destination cannot compound it into `-dev-dev`.
4. **Verify the rewrite landed** — re-read the deployed manifest id and `grep`
   for `ipcTarget: "ssandys.colophon-dev"`, failing loudly if either is wrong. A
   no-op `sed` would deploy a second plugin claiming the published id, which is
   the exact silent collision this whole dance exists to avoid: the registry
   keys plugins by manifest id, and a third-party plugin claiming another's id
   overwrites it in the map rather than warning.

`bin/dev-watch` runs `bin/install` once, then `inotifywait -m -r` on the source
tree and reinstalls on every event.

Two Colophon-specific notes. The rewrite set stays `manifest.json` +
`Panel.qml`: `Service.qml` must **not** acquire `moduleName`/`ipcTarget`, and
helper script paths are resolved from `Qt.resolvedUrl` rather than the plugin id,
so nothing else needs rewriting. And the polkit rule is keyed to
`ollama.service`, not to the plugin id, so the dev and published installs share
one grant — there is no dev-specific privilege step.

**Why a deploy script rather than developing in place.** The shell's
`PluginRegistry` hot-reloads via `inotifywait -m -r` on
`~/.config/omarchy/plugins` and rejects any path not literally under that
prefix. A symlinked source tree would be *discovered* but would not hot-reload,
so the copy is what buys both a source tree outside the plugin directory and
instant reload.

Hot-reload does **not** solve the restart gotcha: Quickshell reloads a plugin's
*code*, but a changed widget *structure* (a new property or binding) does not
recreate the already-instantiated widget, so you keep looking at the stale shape
no matter how many times `dev-watch` reinstalls underneath it. `omarchy restart
shell` is the fix, and it has already cost real debugging time on galley.

## Documentation deliverables (MVP)

Both ship with v1, not after.

**`README.md`** — prerequisites (`ollama`, `systemd`, `python3`, `libnotify`,
Omarchy shell) and the fact that Colophon does not verify them at startup;
install, including the `sudo bin/install-privileges` step, what exactly it
grants, and where the script lives for both a published clone and a dev
checkout; how to read every bar color and badge; the full config table; the
one-time `sudo systemctl enable ollama` for boot start and why the widget cannot
do it; troubleshooting (permission denied, `apiBase` vs `OLLAMA_HOST`, a live
server reading as `foreign`, per-row sizes exceeding the total, running the
collector by hand to see raw JSON); known limitations; uninstall, including
removing the polkit rule.

**`AGENTS.md`** — the layer map and the two invariants; a traps table seeded
with the galley traps carried forward (#10 spawn failure, #11 `Process.command`
while running, #12 cross-language duplication, #13 caller-owned diff state) plus
Colophon's own (the `manage-unit-files` scoping limit, the embedding-endpoint
split, unique-digest size summing, `MemoryCurrent` sentinels); how to add an
action verb; how to add a fixture state; how to run things; **never edit
`/usr/share/omarchy/`**, which is overwritten on `omarchy update`; and a pointer
to this spec's phase-2 boundary.

## Phase 2 — documented, not built

1. **Boot toggle** (`enable`/`disable`). Needs a second privilege mechanism —
   a sudoers drop-in scoped to two exact command strings — because polkit cannot
   scope `manage-unit-files`. Reasoned about above; the panel already reports the
   state it would toggle.
2. **Journal log tail.** `journalctl -u ollama.service` is readable
   unprivileged, so this is scope, not capability. The failure *reason* is
   already in the MVP via `Result`.
3. **Model management: pull, delete, rename.** Feasible with **no** extra
   privilege — the server does the writing as user `ollama`, so `POST
   /api/pull` and `DELETE /api/delete` work from an unprivileged client.
   Deferred for the progress and destructive-confirmation UI, not for
   permissions. Delete is the one that reclaims real space (19 GB here).
4. **D-Bus `PropertiesChanged`** on the unit, replacing the systemd half of
   polling with a signal. Changes only what *triggers* a refresh, not the data
   path, so it drops in without touching the schema or UI.
5. **Idle nudge** — notify when the server has run with zero models loaded for
   N minutes. Considered for the MVP and cut; it fits the on-demand-switch job
   and is the most likely first addition.
6. **`/api/tags` for the installed list** when the server is reachable, if the
   disk scan ever disagrees with it.
7. **Middle-click toggle-to-stop**, if the asymmetric binding proves more
   confusing than helpful.

If you are fixing a bug and reach for one of these as part of the fix, stop —
it is very likely the bug has been misdiagnosed as a missing feature. These were
deferred deliberately.

## Known limitations

- One local instance only. Remote or multiple `OLLAMA_HOST` targets are out of
  scope.
- Boot state is reported, not settable — see phase 2 item 1.
- `foreign` cannot distinguish a hand-run `ollama serve` from a container bound
  to `:11434`. It reports "not managed by systemd", which is true either way.
- Per-model sizes sum that model's own layers while the total sums unique
  digests, so shared blobs make the rows add up to more than the total.
- Warming routes on a `model_family` lookup; an exotic family unknown to the
  set falls through to `/api/generate` and surfaces the API's error rather than
  guessing again.
- No preflight dependency check. A missing binary surfaces as an ordinary
  collector error, and the README lists the prerequisites.
