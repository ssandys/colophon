# Marketplace listing and re-verification

How Colophon is listed on the Omarchy plugin marketplace, what the automated
security baseline sees in this repository, and what has to happen after a
feature branch lands. Facts here were read from the marketplace repository and
its live `registry.json`, not from memory — an earlier round of this work was
misdiagnosed twice by trusting recollection. Written 2026-08-24 and re-checked
against the live registry on 2026-08-29; what moved in between is in "What
changed after this document was written."

## Current listing state

| | |
|---|---|
| Plugin ID | `ssandys.colophon` — **permanent**, see below |
| Source | `https://github.com/ssandys/colophon` |
| Listed | 2026-08-12 |
| `listingValidatedCommit` | `707eaec5c0e74780e149c59cc777c8f5a1dd6a8f` |
| `listingValidatedBranch` | `master` |
| Last validated | 2026-08-22 |
| Baseline outcome | `review-required` |
| Findings | **none** (`findings: []`) |
| Capabilities | `service-management`, `package-manager`, `privilege` |
| Maintainer review | `HANCORE-linux`, 2026-08-22 |
| Labels | `validated`, `security-review-required`, `plugin-update`, `approved-and-verified` |

`approved-and-verified` is the label that actually publishes. `approved-for-listing`
is retired and no longer triggers publication — that mistake cost a week of
assuming a catalog lag that was never going to clear.

Publication is pinned to an exact commit. The catalog compares the observed
upstream commit against the verification commit, so **merging to `master` does
not carry the verified state forward**: the listing keeps showing the older
verified snapshot, and the newer code displays as unverified until a new
verification runs. Note also that the Omarchy install command clones mutable
`HEAD` and is explicitly not verification-bound, so a user can install a commit
that was never verified.

## What the baseline detects here, and why

The outcome is derived only from findings and capabilities. Colophon has **no
findings** — none of the five blocking patterns apply:

| Blocking pattern | Status here |
|---|---|
| `curl-pipe-shell` | Nothing is downloaded or piped to a shell |
| `cargo-git-unpinned` | No Rust, no `cargo install` |
| `remote-git-execution-unpinned` | No external repository is fetched or executed |
| `sudoers-dangerous-passwordless-command` | No sudoers policy is written or shipped |
| `privileged-process-control-from-shared-temp` | No PID files, no `/tmp` state. The parameter editor deliberately posts JSON to the API rather than writing a Modelfile to a temp path — see the spec's "No temp file, no Modelfile, no `ollama` binary" |

The `review-required` outcome comes entirely from three detected capabilities.
Traced to their actual sources, two of the three are **documentation prose, not
behaviour**:

| Capability | Triggered by | Real? |
|---|---|---|
| `service-management` | `systemctl` in `scripts/colophon_action.py`, `scripts/colophon_collect.py`, `README.md` — **and `LICENSE`**, cited at lines 37 and 50 of the verified snapshot | **Yes.** Colophon genuinely reads and controls `ollama.service` |
| `privilege` | `sudo` in `README.md` only, at the "if you'd rather not use the switch" terminal equivalent and the systemd-override note | **No.** There is no `sudo` or `pkexec` anywhere in the code — grep the scripts and QML and you get zero hits. These are instructions telling a user what *they* may type |
| `package-manager` | `pkg add` in `README.md` only, in Prerequisites | **No.** Colophon installs nothing; this is a line telling the user how to install a missing dependency |

That distinction is worth stating in any maintainer conversation: the scanner
reports deterministic evidence, not intent, and it explicitly scans the root
README. Two thirds of Colophon's review surface is the README being helpful.

**`LICENSE` is review surface too**, and the first version of this document got
that wrong — it credited `service-management` to the scripts and the README
alone. The published baseline report on issue #1419 quotes `LICENSE:37` and
`LICENSE:50`, because Colophon's LICENSE carries an external-dependency table and
a privilege note below the MIT grant. Anything in it is prose a reviewer will be
shown as evidence, so it has to stay as accurate as the README. It went stale on
the parameter-editor branch — it still said Colophon only ever read the model
store — and was corrected before merge. When a feature changes what Colophon
does, `LICENSE` belongs on the list of documents to re-read alongside `README.md`
and `manifest.json`.

An earlier scan at commit `7b105f4f` also reported `installer`. That dropped
when `bin/install-privileges` was deleted, which is visible in the registry's
own `listingValidationHistory` — a useful demonstration that removing a
capability is observable in the record.

## What the parameter-editor branch changes

The feature adds a write path: the panel can now rewrite a model's parameters
through `POST /api/create` on the local Ollama API.

**Predicted baseline delta: none.** The capability set should be unchanged, so
the outcome should remain `review-required` with empty findings, taking the same
route as the last two verifications.

Reasoning, each point checkable:

- The new verb `set-params` lives in its own `PARAM_VERBS` tuple, entirely
  separate from `SYSTEMCTL_VERBS`. It does not route through the privileged
  path, so it adds no privilege surface. `scripts/colophon_action.py` contains
  zero occurrences of `sudo` or `pkexec`.
- The write is an HTTP POST to `127.0.0.1`, using the same `post_json` helper
  that `warm` and `unload` already used. Network access to a local API is not
  one of the seven review capabilities.
- No temp file, no Modelfile, no invocation of the `ollama` binary. This was a
  design decision made for other reasons, and it happens to avoid the
  `privileged-process-control-from-shared-temp` pattern entirely.
- No new executable, no bundled binary, no dependency. The Python side remains
  stdlib-only.

**The one thing that could change the answer is documentation.** The baseline
scans the root README and `LICENSE`, and `privilege` and `package-manager` are
already triggered from the README. Adding a new `sudo` example, or a new
package-install instruction, would not change the outcome (both capabilities are
already present) — but removing the existing ones would not clear the review
either, because `service-management` is real and independently requires review.
Do not contort either document to chase a `passed` outcome; it is unreachable
while Colophon controls a systemd unit, which is the entire point of the plugin.
Accuracy is the goal, not a lower capability count.

## Re-verification procedure, after merging to master

1. Merge the branch to `master` and push.
2. Get the **full 40-character** SHA of the new `master` HEAD:
   `git rev-parse master` — the short form is rejected.
3. File a `verify-plugin` issue on `HANCORE-linux/omarchy-plugin-marketplace`,
   choosing the action **"Verify and publish a newer upstream commit."**
   Required fields: plugin ID (`ssandys.colophon`), repository root URL, the
   40-character target SHA, and the acknowledgment checkbox.
4. The workflow runs the Automated Security Baseline against that exact commit.
   Expect `review-required` with no findings, which adds
   `security-review-required` and remains eligible for exact capability
   acceptance.
5. A maintainer applies `approved-and-verified`. Only then does the listing
   move to the new commit.

A scan that cannot complete **fails closed** — approval is impossible without a
complete baseline result. That includes truncated trees, exceeded limits, and
unavailable snapshots, so the target commit must be pushed and public before
filing.

## Not gates, but they decide whether the listing looks maintained

Neither of these blocks verification. Both bit the previous submission.

- **`preview.png` is the listing's primary visual** and currently predates the
  parameter editor — it shows no `config` control. The image and the README's
  alt text are a **coupled pair**: retaking one requires rewriting the other.
  Only the owner can retake it.
- **Both `manifest.json` description strings are listing copy** — the top-level
  `description` and `barWidget.description`. They are the first thing a stranger
  reads, and no test asserts on either, so nothing catches an omission. The
  previous submission was held up because both still listed only
  start/stop/restart.

## What changed after this document was written

Four marketplace changes landed between 2026-08-24 and 2026-08-29, read from the
marketplace repository's own `SECURITY.md`, `VERIFICATION.md` and merged pull
requests. None of them blocks the re-verification above, but the first one
retires an assumption this document originally made.

- **Verification is revocable.** A `maintainer-verified` label applied in error
  and then removed publishes an exact event-bound revocation, and the affected
  snapshot projects back to `Unverified`. The original review and the revocation
  are both preserved in the registry and listing history. Re-review then needs a
  fresh eligible bot report *and* a new label event. Read this document's
  "verified once, pinned until superseded" framing with that in mind: the pin
  can be undone as well as replaced.
- **The scan's file boundary widened.** Paths named `install`, `installer`,
  `setup` or `uninstall` are now candidates even when their extension is a
  recognised binary asset, checked with bounded probes inside a 1 MiB budget and
  capped at 256 candidates. A complete binary asset with a setup-like name cannot
  be excluded and fails closed. **No effect here** — `git ls-files | grep -iE
  "install|setup|uninstall"` returns nothing, and the only tracked binary is
  `preview.png`.
- **Delisting is now a workflow.** Owner-only, `workflow_dispatch` on `main`,
  capped at 20 exact plugin IDs, and it appends every removed ID to
  `retiredPluginIds` permanently.
- **Standard installation can be requested.** The verification form carries a
  guarded action that removes a listing's manual-installation override, gated on
  an exact listed commit, a *passing* automated baseline, and a
  `standard-installation-approved` label — and a maintainer review explicitly
  cannot substitute for that passing baseline. Colophon carries no manual
  override, so there is nothing to request; note the shape of the gate anyway,
  because `review-required` would not satisfy it.

## Limits worth restating

The marketplace's own words: these are "limited automated compatibility and
security-baseline checks on identified plugin commits" and are "not a security
audit, certification, endorsement, or guarantee." The baseline does not execute
plugin code and does not perform data-flow analysis. A passing validator says
nothing about whether the privilege model is sound.

## The irreversible part

The validator distinguishes `plugin-id-listed` from `plugin-id-retired`, and a
retired ID can never be reused. Delisting would not free `ssandys.colophon`.
This is enforced rather than theoretical, and the enforcement is not rare: the
registry listed five retired IDs on 2026-08-24 and **21** on 2026-08-29 — thirteen
of them retired in a single day, through the delisting workflow described above.
`ssandys.colophon` is not among them.
