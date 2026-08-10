# Task 2 Verification — 2026-08-10

With the polkit rule installed and `ollama.service` inactive.

## The grant works

```bash
$ systemctl --no-ask-password stop ollama.service
$ echo "exit=$?"
exit=0
```

Stopping an already-inactive unit is a true no-op that still runs the polkit check in earnest. No password prompt; the polkit grant accepted the request.

## The verb allow-list is effective

```bash
$ systemctl --no-ask-password freeze ollama.service
Access denied as the requested operation requires interactive authentication.
```

The `freeze` verb is not in the allow-list (only `start`, `stop`, `restart`). This proves that polkit is enforcing the rule and rejecting unauthorized verbs, and that success is not vacuous. Alongside the `stop` success above, this confirms the verb scoping is working.

Note: `systemctl --no-ask-password kill ollama.service` returned "Unit ollama.service not loaded" before reaching polkit, so it proves nothing.

## `pkcheck` is unusable unprivileged

When `--check` was first implemented using `pkcheck --action-id org.freedesktop.systemd1.manage-units --detail unit ollama.service --detail verb start`:

```
Error checking for authorization org.freedesktop.systemd1.manage-units: GDBus.Error:org.freedesktop.PolicyKit1.Error.NotAuthorized: Only trusted callers (e.g. uid 0 or an action owner) can use CheckAuthorization() and pass details
exit=127
```

polkit forbids unprivileged callers from passing `--detail` arguments. A detail-less query cannot match a rule that scopes by unit and verb. Running `pkcheck` as root would ask whether *root* is authorized, which is not the question. Therefore, `--check` probes with `systemctl --no-ask-password` using a no-op verb instead.

## `manage-unit-files` scoping: UNVERIFIED, deliberately

The design spec defers the boot toggle (enable/disable) on the claim that `manage-unit-files` is invoked with no `unit` detail, making it impossible to scope a rule to one unit.

Distinguishing "systemd passes no unit detail" from "a detail is passed but our rule does not cover that action" requires installing a temporary root rule that *does* grant `manage-unit-files` scoped by unit, and observing whether it matches. Cheap proxies cannot separate the two hypotheses, and `pkcheck` is unavailable for this (per above).

We chose not to install a deliberately over-broad rule on a working machine to test this.

**The MVP decision is unaffected:** the grant demonstrably excludes everything outside its verb allow-list (`start`, `stop`, `restart`), per the freeze/stop test above. Whether `manage-unit-files` can be scoped is a separate design question and does not change the current scope or safety of the deployed grant.
