#!/usr/bin/env python3
"""Perform one Colophon action.

  colophon_action.py start|stop|restart|enable|disable            [--dry-run]
  colophon_action.py warm   <model> [--kind K] [--keep-alive MIN] [--dry-run]
  colophon_action.py unload <model> [--kind K]                    [--dry-run]
  colophon_action.py set-params <model> --param KEY=VALUE [--param KEY=VALUE ...] [--dry-run]

Common flags: --api-base URL.

One entry point, so the panel's action surface stays data-driven and every
failure is reported the same way. Python rather than bash because `warm` is not
pure command-mapping: it starts the unit, polls the API until it answers, then
POSTs. In bash that would mean a curl dependency and a hand-rolled retry loop.

`kind` is passed in, never re-derived. The collector owns the family-to-endpoint
lookup; duplicating it here is exactly the kind of hand-copied cross-language
logic that fails silently on a one-sided edit.
"""

import http.client
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

UNIT_NAME = "ollama.service"
SYSTEMCTL = "/usr/bin/systemctl"

LIFECYCLE_VERBS = ("start", "stop", "restart")
BOOT_VERBS = ("enable", "disable")
# Every verb that shells out to systemctl. The flag guard in
# tests/test_action.py iterates this rather than LIFECYCLE_VERBS so a new verb
# category cannot ship without the --no-ask-password assertion covering it.
SYSTEMCTL_VERBS = LIFECYCLE_VERBS + BOOT_VERBS
MODEL_VERBS = ("warm", "unload")
PARAM_VERBS = ("set-params",)
KINDS = ("generate", "embed")

# key -> (min, max, is_int). Mirrored in Model.js's PARAM_SPECS; this is the
# only surface that writes, and tests/test_cross_language.py asserts the two
# agree along with Panel.qml. See AGENTS.md trap #12.
PARAM_BOUNDS = {
    "num_ctx": (4096, 131072, True),
    "temperature": (0.0, 2.0, False),
    "top_p": (0.0, 1.0, False),
    "top_k": (1, 200, True),
}

DEFAULT_API_BASE = "http://127.0.0.1:11434"
DEFAULT_KEEP_ALIVE_MIN = 5

# The dialog's patience budget, not a command timeout: the call blocks while
# Omarchy's authentication prompt is open. 30s was chosen when a prompt was
# impossible, and is short for walking back to the desk -- the process would be
# killed mid-authentication and the panel would report a timeout for something
# the user was about to approve.
SYSTEMCTL_TIMEOUT_SEC = 120
API_TIMEOUT_SEC = 5

# How long to wait for the port to bind after `systemctl start` -- genuinely
# fast, since this is only polling a TCP connect/HTTP GET in a tight loop.
API_WAIT_DEADLINE_SEC = 20

# How long the load POST itself may take. A prompt-less /api/generate only
# returns once the model is fully resident in memory -- `done_reason: "load"`
# is the completion signal, not an early ack -- and a 7B Q4 model loading from
# cold page cache routinely takes well over 20s. This must be much larger than
# API_WAIT_DEADLINE_SEC: an unbound port is a fast failure, a slow disk read
# during a real load is not a failure at all. 300s comfortably covers a large
# model on a cold cache without waiting forever on a genuinely dead server.
LOAD_POST_TIMEOUT_SEC = 300

POLL_SLEEP_SEC = 0.5

MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]+\Z")


def systemctl_command(verb):
    # No --no-ask-password. That flag sets allow_interactive_authorization to
    # false on the D-Bus call, so polkitd answers without ever consulting an
    # agent -- which is what turns Omarchy's authentication dialog into a bare
    # "Access denied". Omitting it lets polkitd raise the dialog and
    # pam_fprintd take a fingerprint -- but every call still prompts:
    # systemctl is its own short-lived polkit subject and exits within the
    # same second, so there is no auth_admin_keep grant left alive to reuse.
    # See AGENTS.md trap #31. No tty is involved at any point; polkit
    # authentication has never gone through one.
    return [SYSTEMCTL, verb, UNIT_NAME]


def endpoint_for(kind):
    return "/api/embed" if kind == "embed" else "/api/generate"


def load_body(model, kind, keep_alive):
    body = {"model": model, "keep_alive": keep_alive}
    if kind == "embed":
        # /api/embed requires an input field; an empty one loads or unloads
        # without computing anything.
        body["input"] = ""
    return body


def create_body(model, params):
    """The POST /api/create body that re-stamps `model` in place.

    `from` is the model's own name: that is how Ollama re-stamps a definition,
    and the create is additive -- template, system message and existing
    parameters all survive, verified on the target machine. It is metadata-only,
    so it does not scale with model size (45ms on an 18.2 GB model).
    """
    return {"model": model, "from": model, "parameters": dict(params)}


def plan(verb, target, kind, keep_alive_min, api_base, running, params=None):
    """The steps this verb would perform, as human-readable lines."""
    if params is None:
        params = {}
    if verb in SYSTEMCTL_VERBS:
        return [" ".join(systemctl_command(verb))]

    if verb in PARAM_VERBS:
        return ["POST " + str(api_base).rstrip("/") + "/api/create "
                + json.dumps(create_body(target, params), sort_keys=True)]

    base = str(api_base).rstrip("/")
    keep_alive = 0 if verb == "unload" else str(int(keep_alive_min)) + "m"
    steps = []
    if verb == "warm" and not running:
        steps.append(" ".join(systemctl_command("start")))
        steps.append("WAIT " + base + "/api/version up to "
                     + str(API_WAIT_DEADLINE_SEC) + "s")
    steps.append("POST " + base + endpoint_for(kind) + " "
                 + json.dumps(load_body(target, kind, keep_alive),
                              sort_keys=True))
    return steps


def api_reachable(api_base, timeout=API_TIMEOUT_SEC):
    url = str(api_base).rstrip("/") + "/api/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
        return True
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError, TimeoutError):
        return False


def wait_for_api(api_base, deadline_sec):
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if api_reachable(api_base, timeout=1):
            return True
        time.sleep(POLL_SLEEP_SEC)
    return False


def post_json(url, body):
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=LOAD_POST_TIMEOUT_SEC) as response:
            response.read()
        return 0
    except urllib.error.HTTPError as error:
        # Surface the API's own message: this is how a warm against the wrong
        # endpoint for an unusual model family reports itself, rather than
        # silently doing nothing.
        detail = ""
        try:
            with error:
                detail = error.read().decode("utf-8", "replace").strip()
        except (http.client.HTTPException, OSError):
            # Reading the error body can itself hit IncompleteRead, which is
            # an HTTPException and NOT an OSError -- the same gap that let a
            # raw traceback escape api_get in the collector. `with error:`
            # also makes sure the response is closed either way, instead of
            # relying on garbage collection to do it.
            pass
        sys.stderr.write("colophon: " + url + " returned " + str(error.code)
                         + (": " + detail if detail else "") + "\n")
        return 1
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError, TimeoutError) as error:
        sys.stderr.write("colophon: could not reach " + url + ": "
                         + str(error) + "\n")
        return 1


def run_systemctl(verb):
    command = systemctl_command(verb)
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=SYSTEMCTL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        sys.stderr.write("colophon: " + verb + " timed out\n")
        return 1
    except OSError as error:
        sys.stderr.write("colophon: could not run systemctl: "
                         + str(error) + "\n")
        return 1
    if completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip()
                  or ("exit " + str(completed.returncode)))
        sys.stderr.write("colophon: " + verb + " failed: " + detail + "\n")
        return 1
    return 0


def execute(verb, target, kind, keep_alive_min, api_base, params=None):
    if verb in SYSTEMCTL_VERBS:
        return run_systemctl(verb)

    if verb in PARAM_VERBS:
        return post_json(str(api_base).rstrip("/") + "/api/create",
                         create_body(target, params or {}))

    if verb == "warm" and not api_reachable(api_base):
        code = run_systemctl("start")
        if code != 0:
            return code
        if not wait_for_api(api_base, API_WAIT_DEADLINE_SEC):
            sys.stderr.write(
                "colophon: started the service but it never answered on "
                + str(api_base) + "\n")
            return 1

    keep_alive = 0 if verb == "unload" else str(keep_alive_min) + "m"
    url = str(api_base).rstrip("/") + endpoint_for(kind)
    return post_json(url, load_body(target, kind, keep_alive))


def main(argv):
    args = list(argv)
    if not args:
        sys.stderr.write("colophon_action: no verb given\n")
        return 2

    verb = args.pop(0)
    target = ""
    if args and not args[0].startswith("--"):
        target = args.pop(0)

    dry_run = False
    kind = "generate"
    keep_alive_raw = DEFAULT_KEEP_ALIVE_MIN
    api_base = DEFAULT_API_BASE
    params = {}
    while args:
        arg = args.pop(0)
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--kind" and args:
            kind = args.pop(0)
        elif arg == "--keep-alive" and args:
            keep_alive_raw = args.pop(0)
        elif arg == "--api-base" and args:
            api_base = args.pop(0)
        elif arg == "--param" and args:
            raw = args.pop(0)
            if "=" not in raw:
                sys.stderr.write(
                    "colophon_action: --param needs KEY=VALUE, got '"
                    + raw + "'\n")
                return 2
            key, _, value_text = raw.partition("=")
            if key not in PARAM_BOUNDS:
                sys.stderr.write(
                    "colophon_action: unknown parameter '" + key + "'\n")
                return 2
            low, high, is_int = PARAM_BOUNDS[key]
            try:
                value = int(value_text) if is_int else float(value_text)
            except ValueError:
                sys.stderr.write(
                    "colophon_action: " + key + " must be "
                    + ("an integer" if is_int else "a number")
                    + ", got '" + value_text + "'\n")
                return 2
            if value < low or value > high:
                sys.stderr.write(
                    "colophon_action: " + key + " must be between "
                    + str(low) + " and " + str(high) + "\n")
                return 2
            params[key] = value
        else:
            sys.stderr.write(
                "colophon_action: unknown argument '" + arg + "'\n")
            return 2

    if verb not in SYSTEMCTL_VERBS + MODEL_VERBS + PARAM_VERBS:
        sys.stderr.write("colophon_action: unknown verb '" + verb + "'\n")
        return 2
    if verb in PARAM_VERBS and not params:
        sys.stderr.write(
            "colophon_action: set-params needs at least one --param\n")
        return 2
    if kind not in KINDS:
        sys.stderr.write("colophon_action: unknown kind '" + kind + "'\n")
        return 2
    try:
        keep_alive_min = int(keep_alive_raw)
    except (TypeError, ValueError):
        sys.stderr.write(
            "colophon_action: --keep-alive must be an integer\n")
        return 2
    # The manifest constrains this to 1-120 at the panel layer, but this script
    # is the only surface that performs a write and does not get to assume the
    # caller clamped. 0 is the specific trap: Ollama reads "0m" as unload
    # immediately, the exact opposite of warm, and would do it silently.
    if keep_alive_min < 1 or keep_alive_min > 120:
        sys.stderr.write(
            "colophon_action: --keep-alive must be between 1 and 120 minutes\n")
        return 2
    # A malformed base would otherwise fail api_reachable() like an ordinary
    # refusal, and warm would go on to start the LOCAL unit because of it.
    if not str(api_base).startswith(("http://", "https://")):
        sys.stderr.write(
            "colophon_action: --api-base must start with http:// or https://\n")
        return 2

    if verb in MODEL_VERBS + PARAM_VERBS:
        if not target:
            sys.stderr.write(
                "colophon_action: " + verb + " needs a model\n")
            return 3
        if not MODEL_RE.match(target):
            sys.stderr.write(
                "colophon_action: refusing suspicious model name\n")
            return 3

    if dry_run:
        for line in plan(verb, target, kind, keep_alive_min, api_base, False,
                         params=params):
            sys.stdout.write(line + "\n")
        return 0
    return execute(verb, target, kind, keep_alive_min, api_base,
                   params=params)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
