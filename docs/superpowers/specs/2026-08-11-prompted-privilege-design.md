# Colophon — prompted privilege, replacing the polkit rule

**Date:** 2026-08-11
**Status:** Approved, ready for planning
**Supersedes:** the "The privilege grant" section of
`docs/superpowers/specs/2026-08-10-colophon-design.md`

## Purpose

Colophon ships a root-installed polkit rule and an installer script so that
start, stop, and restart run without a password. This replaces both with the
authentication dialog Omarchy already provides: the verbs prompt — ~~once per
login~~ **corrected 2026-08-12: on every action, see below** — take a
fingerprint, and proceed.

The rule is deleted, not made optional. It bought about one second per login
and cost the project its only root-installed artifact, a ~90-line installer, a
security-review surface, and five parked defects.

## The premise that was wrong

The original design's central privilege decision rests on one row of its
verified-environment table:

> | polkit **agent** | **none running** (only `polkitd`; no `hyprpolkitagent`,
> `polkit-gnome`, `lxqt-policykit`, `mate-polkit` installed) | `pkexec` from a
> QML `Process` has no tty and no agent — it fails outright. The Go tray's
> `pkexec systemctl` approach **does not port** |

That is false, and it was false when written. The check was
`ps -eo args | grep -i polkit`, which looks for standalone agent *binaries*.
Omarchy's agent is `omarchy.polkit`, a `service`-kind shell plugin with
`keepLoaded: true`, running **inside the shell process** — it could never have
appeared in that search. The journal has logged `omarchy polkit agent
registered` on every shell start throughout the build.

Everything downstream followed from it: `pkexec` was ruled out, a scoped rule
was written instead, `--no-ask-password` was added to every `systemctl` call to
avoid a hang that could not happen, and the boot toggle was deferred because no
rule can scope `manage-unit-files`.

## Verified, 2026-08-11

| Claim | Evidence |
|---|---|
| An agent is registered and implements a real dialog | `/usr/share/omarchy/shell/plugins/polkit/PolkitAgent.qml`, 390 lines, built on `Quickshell.Services.Polkit`; `manifest.json` declares `kinds: ["service"]`, `keepLoaded: true` |
| It handles fingerprint deliberately | The agent carries `property bool fingerprintConfigured`, commented "pam_fprintd appears in the polkit PAM stack (a sensor is enrolled)" |
| Fingerprint is wired into polkit on this machine | `/etc/pam.d/polkit-1` has `auth sufficient pam_fprintd.so` **above** `auth required pam_unix.so`; `fprintd 1.94.5-2` installed |
| polkit authorizes the user interactively | `pkcheck --action-id org.freedesktop.systemd1.manage-unit-files --process $$ -u` → `exit=0`, `polkit.result=auth_admin_keep`, `polkit.temporary_authorization_id=tmpauthz0`, `polkit.retains_authorization_after_challenge=true` |
| ~~One prompt covers the action, not each verb~~ **Corrected 2026-08-12: every verb prompts** | What was actually verified was `pkcheck --process $$`, whose subject is the long-lived invoking shell: a second identical call was silent and reused `tmpauthz11`. That does not transfer to `systemctl`, which names itself as the subject and exits within the same second — two consecutive `systemctl start` calls against an already-active unit created `tmpauthz12` and `tmpauthz13`, and **both** prompted. See trap #31. |
| A first-party plugin already escalates this way | `shell/plugins/panels/tailscale/Service.qml:353` runs `["pkexec", "tailscale", "set", …]` from a QML `Process` |

The last row is the one that should have been found first. A shipped Omarchy
plugin does the exact thing the spec called impossible.

### Corrected 2026-08-12: every verb prompts, not once per login

polkit scopes an `auth_admin_keep` temporary authorization to
`unix-process:PID:STARTTIME`; it is reusable only while that exact process is
still alive. `systemctl` names itself as that process and exits within the
same second it's authorized, so its authorization is orphaned at birth —
retention can never help it. No logind session is resolvable for the shell's
children either, because Omarchy runs the compositor under `user@1000.service`
(uwsm) rather than inside a `session-N.scope`:

```
quickshell cgroup:
/user.slice/user-1000.slice/user@1000.service/session.slice/wayland-wm@hyprland.desktop.service
login session 1: tty1, seat0, leader pid 3196 -- no session-N.scope in that path
```

Even a perfectly retained authorization would not have delivered "once per
login" regardless: the temporary authorization's own lifetime is five
minutes (observed `expires: 4 min 59 sec`), not a session. The owner measured
8 authentications in about 80 seconds of normal use; the journal shows 8
`polkit-agent-helper-1` spawns to match.

## The change

**One line carries it.** `systemctl_command` in `scripts/colophon_action.py`
stops sending `--no-ask-password`. That flag sets
`allow_interactive_authorization = false` on the D-Bus call, which is precisely
what converts a would-be dialog into `Access denied`. Without it, `polkitd`
invokes the registered agent and the dialog appears. No tty is involved at any
point — polkit authentication has never gone through one.

**Deleted:**

- `polkit/49-colophon-ollama.rules`
- `bin/install-privileges`
- The README's "Grant it privilege" section, and the `--check` and `--remove`
  documentation with it

**`SYSTEMCTL_TIMEOUT_SEC` rises from 30 to 120.** It was chosen when a prompt
was impossible; it is now the user's patience budget while the dialog is open.
Thirty seconds is short for walking back to the desk, and the failure mode is
bad — the action process is killed mid-authentication and the panel reports a
timeout for something the user was about to approve. The button self-heals
either way: `Service.qml` clears `actionInProgress` on process exit, which the
`onRunningChanged` guard guarantees fires.

**`Model.actionErrorText` stops naming a script that no longer exists.** It
currently maps polkit's refusal to `permission denied — the polkit rule is
missing; run bin/install-privileges (see README)`. A dismissed dialog is not a
missing setup step; the message should say the action was not authorized.

## Guards

The four assertions that pin the old model invert, and the inverted guard is
the most valuable artifact of this change:

| Location | Now | Becomes |
|---|---|---|
| `tests/test_action.py:27` | `plan()` output contains `--no-ask-password` | contains no such flag |
| `tests/test_action.py:34` | flag present on every lifecycle verb | flag absent from every lifecycle verb |
| `tests/test_action.py:105` | dry-run string carries the flag | carries no flag |
| `tests/test_cross_language.py:271` | flag present in the action script | absent from the action script |

Re-adding `--no-ask-password` does not fail loudly. It silently converts every
prompt into `permission denied` — this project's signature failure mode, and
one copy-paste from galley away. The inverted assertions carry failure messages
naming that consequence.

`tests/test_cross_language.py:264` reads `polkit/49-colophon-ollama.rules` to
cross-check the unit name. That file is deleted, so the rule half of the guard
goes and the Python half stays.

## Corrections to the design record

Dated notes, not silent rewrites — the convention this project has followed
every other time it was wrong.

- **The 2026-08-10 spec's verified-environment table.** The polkit-agent row is
  corrected, and the correction states *how* the check failed: it searched for
  standalone agent processes, and the agent is a QML service inside the shell.
- **That spec's "The privilege grant" section** is replaced by a pointer to
  this document.
- **`AGENTS.md` trap 16** (polkit refuses `--detail` from an unprivileged
  caller) remains true and useful; keep it.
- **Trap 17** (`manage-units` gates every per-unit operation, not just the
  lifecycle verbs) remains true and worth knowing for anyone who later writes a
  rule, but loses its "this is why our rule is verb-scoped" framing.
- **Trap 28** (enable/disable cannot be scoped) stops being a blocker. It
  becomes a note that the boot toggle is a follow-up, unblocked by this change.
- A new trap records the premise failure itself: an agent embedded in another
  process is invisible to a process-list search, so absence of evidence in `ps`
  is not evidence of absence.

## Out of scope

- **The boot toggle.** Unblocked by this change — `enable`/`disable` would
  simply prompt — but deliberately deferred to its own spec so this one lands
  and is verified alone. The panel already reports boot state; the feature is
  mostly making that line clickable.
- **Migration.** The repository is public but has no install base beyond its
  author, whose machine already has no rule installed. No removal instructions
  ship.
- **`pkexec`.** The tailscale precedent shows it works, but `systemctl` over
  D-Bus is the better mechanism here: it reaches the same agent without running
  a second binary as root.

## Testing

The dialog cannot be tested in this repository. It needs a live agent, a
registered session, and a human finger. What is testable:

- `--dry-run` assertions over every verb's constructed command, which is where
  the flag's absence is pinned.
- The inverted guards above.
- The existing suite must stay green: 119 Python, 24 JavaScript, 0 skips.

What must be verified by hand, and stated as unverified until it is:

1. With no rule installed, clicking **start** raises the Omarchy dialog and
   offers fingerprint.
2. After authenticating, clicking **stop** in the same session is silent.
3. Dismissing the dialog surfaces a sensible message in the panel's error
   strip, not a script name.

## Known limitations

- A dismissed or ignored dialog fails the action after 120 seconds, during
  which the button is disabled. With every verb now prompting (see below),
  this is a routine wait, not a rare one — the 120-second budget is spent on
  every start, stop, and restart, not just a once-per-login first click.
- If the shell's polkit agent is ever not running — plugin disabled, shell
  crashed — the verbs fail rather than prompting. That is the same failure as
  today, so no regression, but it is now the only failure mode rather than one
  of two.
- **Corrected 2026-08-12: every start, stop, and restart raises the dialog.**
  `auth_admin_keep` retention is real, but it is scoped to the exact process
  that requested it, and each `systemctl` invocation is its own short-lived
  polkit subject — it is gone before the authorization could ever be reused.
  This is a per-action fingerprint (or password) touch, not a per-login one.
  It is the accepted trade for shipping no root-installed artifact.
