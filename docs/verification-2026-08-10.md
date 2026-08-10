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

# Task 3 Verification — load/unload idiom

With `ollama.service` started via `systemctl --no-ask-password start ollama.service` (exit 0).

## Load: a prompt-less `generate` warms the model

```
$ curl -s http://127.0.0.1:11434/api/version
{"version":"0.32.7"}
$ curl -s http://127.0.0.1:11434/api/generate \
    -d '{"model":"llama3.2:3b","keep_alive":"5m"}' | head -c 400; echo
{"model":"llama3.2:3b","created_at":"2026-08-10T15:30:59.096221671Z","response":"","done":true,"done_reason":"load"}
$ curl -s http://127.0.0.1:11434/api/ps | python3 -m json.tool | head -40
{
    "models": [
        {
            "name": "llama3.2:3b",
            "model": "llama3.2:3b",
            "size": 2561524365,
            "digest": "a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "llama",
                "families": [
                    "llama"
                ],
                "parameter_size": "3.2B",
                "quantization_level": "Q4_K_M"
            },
            "expires_at": "2026-08-10T11:35:59.096427359-04:00",
            "size_vram": 0,
            "context_length": 4096
        }
    ]
}
```

**Verdict: CONFIRMED.** The prompt-less `POST /api/generate` returns `"done_reason": "load"`, and `/api/ps` then lists `llama3.2:3b` with `size`, `size_vram`, `expires_at`, and `details.parameter_size` present, exactly as the spec claimed.

## Unload: `keep_alive: 0` actually unloads

```
$ curl -s http://127.0.0.1:11434/api/generate \
    -d '{"model":"llama3.2:3b","keep_alive":0}' | head -c 300; echo
{"model":"llama3.2:3b","created_at":"2026-08-10T15:31:14.776593703Z","response":"","done":true,"done_reason":"unload"}
$ curl -s http://127.0.0.1:11434/api/ps   # expect: {"models":[]}
{"models":[]}
```

**Verdict: CONFIRMED.** `keep_alive: 0` returns `"done_reason": "unload"`, and the immediately following `/api/ps` returns an empty `models` array. The model is actually unloaded, not merely scheduled to expire.

## The embedding split: `generate` is the wrong verb for `nomic-embed-text`

```
$ curl -s http://127.0.0.1:11434/api/generate \
    -d '{"model":"nomic-embed-text","keep_alive":"5m"}' | head -c 300; echo
{"error":"\"nomic-embed-text\" does not support generate"}
$ curl -s http://127.0.0.1:11434/api/embed \
    -d '{"model":"nomic-embed-text","input":"","keep_alive":"5m"}' | head -c 200; echo
{"model":"nomic-embed-text","embeddings":[]}
```

**Verdict: CONFIRMED — the split is real and necessary.** `POST /api/generate` against the embedding model `nomic-embed-text` errors with `"\"nomic-embed-text\" does not support generate"`; it does not load the model. `POST /api/embed` against the same model succeeds (no error; `embeddings` is present, empty only because the probe used an empty `input` string). The design's routing decision — warm generate-capable models via `/api/generate` and embedding models via `/api/embed` — is load-bearing and should **not** be simplified to a single endpoint.
