#!/usr/bin/env python3
"""Collect one Ollama status snapshot and print it as JSON.

All read I/O lives here. Every transform is a module-level function taking
plain dicts so it can be tested without touching systemd, the network, or the
filesystem. Stdlib only, no pip -- this is what lets the collector run with
zero setup on a bare Omarchy install.
"""

UNIT_NAME = "ollama.service"

# The seven statuses, resolved here and nowhere else. Model.js only maps them
# to a glyph, a color, and a label; tests/test_cross_language.py asserts the
# two sets stay equal.
STATUSES = (
    "running",
    "starting",
    "stopping",
    "stopped",
    "failed",
    "foreign",
    "missing",
)


def resolve_status(unit, api_reachable, has_binary):
    """Fold the unit state and the API probe into one status string."""
    load_state = (unit or {}).get("loadState") or ""
    active = (unit or {}).get("activeState") or ""

    # No binary or no unit means there is nothing to control, whatever is
    # answering on the port.
    if not has_binary or load_state == "not-found":
        return "missing"
    if active == "activating":
        return "starting"
    if active == "deactivating":
        return "stopping"
    # `reloading` is not in the design spec's table; folding it in with
    # `active` is the honest reading -- the service is up either way.
    if active in ("active", "reloading"):
        return "running" if api_reachable else "starting"
    # Something is serving on the port while systemd says the unit is down:
    # a hand-run `ollama serve`, or anything else bound to it.
    if api_reachable:
        return "foreign"
    if active == "failed":
        return "failed"
    return "stopped"


import datetime
import glob
import json
import os
import re
import shlex

DEFAULT_MODELS_ROOT = "/var/lib/ollama"

# systemd's "this property has no value" sentinel for unsigned integers.
UINT64_MAX = 18446744073709551615

SHOW_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "UnitFileState",
    "ExecMainStartTimestampMonotonic",
    "NRestarts",
    "MemoryCurrent",
    "Environment",
)

# Families that answer on /api/embed rather than /api/generate. Verified on the
# target machine: nomic-embed-text reports model_family "nomic-bert".
EMBED_FAMILIES = ("bert", "nomic-bert", "xlm-roberta")

_FRACTION_RE = re.compile(r"\.(\d+)")


def parse_show(text):
    """`systemctl show` output to a flat dict, splitting on the first `=`."""
    result = {}
    for line in str(text or "").splitlines():
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key] = value
    return result


def models_root(show):
    """Where the model store lives, per the unit's own Environment."""
    raw = (show or {}).get("Environment", "")
    try:
        tokens = shlex.split(raw)
    except ValueError:
        # Unbalanced quotes must not take the whole poll down.
        return DEFAULT_MODELS_ROOT
    for token in tokens:
        if token.startswith("OLLAMA_MODELS="):
            return token.split("=", 1)[1]
    return DEFAULT_MODELS_ROOT


def memory_bytes(show):
    raw = (show or {}).get("MemoryCurrent", "")
    if not str(raw).isdigit():
        return None
    value = int(raw)
    return None if value >= UINT64_MAX else value


def started_at(show, uptime_sec, now_sec):
    """Epoch seconds the unit's main process started, or None.

    Uses ExecMainStartTimestampMonotonic (integer microseconds since boot)
    rather than ExecMainStartTimestamp, which is a locale-dependent human
    string that would need date parsing to read.
    """
    raw = (show or {}).get("ExecMainStartTimestampMonotonic", "")
    if not str(raw).isdigit():
        return None
    micros = int(raw)
    if micros <= 0:
        return None
    ago = float(uptime_sec) - (micros / 1000000.0)
    if ago < 0:
        return None
    return int(round(float(now_sec) - ago))


def unit_from_show(show, uptime_sec, now_sec):
    show = show or {}
    restarts = show.get("NRestarts", "0")
    return {
        "name": UNIT_NAME,
        "loadState": show.get("LoadState", ""),
        "activeState": show.get("ActiveState", ""),
        "subState": show.get("SubState", ""),
        "unitFileState": show.get("UnitFileState", ""),
        "result": show.get("Result", ""),
        "startedAt": started_at(show, uptime_sec, now_sec),
        "nRestarts": int(restarts) if str(restarts).isdigit() else 0,
        "memoryBytes": memory_bytes(show),
    }


def processor(size, vram):
    """Derive the ollama-ps PROCESSOR column from size and size_vram."""
    total = int(size or 0)
    in_vram = int(vram or 0)
    if total <= 0 or in_vram <= 0:
        return ("cpu", 0)
    if in_vram >= total:
        return ("gpu", 100)
    return ("split", int(round(100.0 * in_vram / total)))


def parse_rfc3339(value):
    """RFC 3339 to epoch seconds, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")

    # Ollama emits nanosecond fractions; fromisoformat accepts at most six
    # digits, so an untruncated value raises instead of parsing.
    def trim(match):
        return "." + match.group(1)[:6]

    text = _FRACTION_RE.sub(trim, text, count=1)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    # Ollama uses 0001-01-01 to mean "no expiry"; .timestamp() on it either
    # raises or returns a nonsense negative depending on the platform.
    if parsed.year < 1970:
        return None
    try:
        return int(parsed.timestamp())
    except (ValueError, OSError, OverflowError):
        return None


def model_kind(family):
    return "embed" if str(family or "") in EMBED_FAMILIES else "generate"


def model_label(namespace, name, tag):
    if namespace == "library":
        return name + ":" + tag
    return namespace + "/" + name + ":" + tag


def normalize_loaded(payload):
    models = ((payload or {}).get("models") or [])
    result = []
    for entry in models:
        details = entry.get("details") or {}
        kind_source, percent = processor(entry.get("size"),
                                        entry.get("size_vram"))
        result.append({
            "name": entry.get("name") or entry.get("model") or "",
            "sizeBytes": int(entry.get("size") or 0),
            "vramBytes": int(entry.get("size_vram") or 0),
            "processor": kind_source,
            "gpuPercent": percent,
            "expiresAt": parse_rfc3339(entry.get("expires_at")),
            "parameterSize": details.get("parameter_size") or "",
            "quantization": details.get("quantization_level") or "",
            "kind": model_kind(details.get("family")),
        })
    return result


def _read_json(path):
    """Read a JSON *object* from path, or None.

    Returns None for anything that is not a dict. A truncated or corrupted
    write can parse cleanly as a list, string, or number, and every caller
    here wants a dict -- without this check one bad manifest raises
    AttributeError and takes down the whole inventory instead of being
    skipped.
    """
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def scan_installed(root):
    """Read the model inventory straight off disk.

    Deliberately not /api/tags, even when the server is reachable: two code
    paths producing two possibly-different counts for the same list is a worse
    property than one path that behaves identically in every state.

    Returns (entries, unique_bytes). Per-entry sizeBytes sums that model's own
    layers; unique_bytes sums each blob digest once, because models share
    blobs. The rows can therefore add up to more than the total.
    """
    pattern = os.path.join(root, "manifests", "*", "*", "*", "*")
    entries = []
    seen = {}
    for path in sorted(glob.glob(pattern)):
        manifest = _read_json(path)
        if not manifest:
            continue
        parts = path.split(os.sep)
        if len(parts) < 4:
            continue
        namespace, name, tag = parts[-3], parts[-2], parts[-1]

        size = 0
        # Each shape is checked rather than assumed: a corrupted manifest that
        # still parses must cost us that one model, not the whole inventory.
        config = manifest.get("config")
        if not isinstance(config, dict):
            config = {}
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            layers = []
        for layer in [config] + layers:
            if not isinstance(layer, dict):
                continue
            digest = layer.get("digest")
            layer_size = int(layer.get("size") or 0)
            size += layer_size
            if digest:
                seen[digest] = layer_size

        blob = _read_json(os.path.join(
            root, "blobs", str(config.get("digest", "")).replace(":", "-")))
        blob = blob or {}
        family = blob.get("model_family") or ""

        try:
            modified = int(os.path.getmtime(path))
        except OSError:
            modified = None

        entries.append({
            "name": model_label(namespace, name, tag),
            "sizeBytes": size,
            "family": family,
            "parameterSize": blob.get("model_type") or "",
            "quantization": blob.get("file_type") or "",
            "kind": model_kind(family),
            "modifiedAt": modified,
        })

    entries.sort(key=lambda entry: entry["name"])
    return (entries, sum(seen.values()))


import http.client
import subprocess
import shutil
import sys
import time
import urllib.error
import urllib.request

SCHEMA_VERSION = 1
DEFAULT_API_BASE = "http://127.0.0.1:11434"
SYSTEMCTL = "/usr/bin/systemctl"
OLLAMA = "ollama"

SHOW_TIMEOUT_SEC = 5
API_TIMEOUT_SEC = 2
VERSION_TIMEOUT_SEC = 3

_VERSION_RE = re.compile(r"version is ([0-9][0-9A-Za-z.\-+]*)")


class CollectError(Exception):
    """A failure to find out, as distinct from a service that is merely down."""


def uptime_seconds():
    try:
        with open("/proc/uptime") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def api_get(api_base, path, timeout):
    """Returns (payload, latency_ms), or (None, None) if it did not answer."""
    url = str(api_base).rstrip("/") + path
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError, TimeoutError):
        return (None, None)
    return (payload, int(round((time.monotonic() - started) * 1000)))


def parse_client_version(text):
    match = _VERSION_RE.search(str(text or ""))
    return match.group(1) if match else None


class LiveSource(object):
    def __init__(self, api_base):
        self.api_base = api_base
        self._show = None

    def show_text(self):
        if self._show is not None:
            return self._show
        command = [SYSTEMCTL, "show", UNIT_NAME,
                   "--property=" + ",".join(SHOW_PROPERTIES), "--no-pager"]
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=SHOW_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            raise CollectError("systemctl show timed out")
        except OSError as error:
            raise CollectError("could not run systemctl: " + str(error))
        if completed.returncode != 0:
            detail = completed.stderr.strip() or ("exit " +
                                                 str(completed.returncode))
            raise CollectError("systemctl show failed: " + detail)
        self._show = completed.stdout
        return self._show

    def has_binary(self):
        return shutil.which(OLLAMA) is not None

    def api_version(self):
        return api_get(self.api_base, "/api/version", API_TIMEOUT_SEC)

    def api_ps(self):
        payload, _ = api_get(self.api_base, "/api/ps", API_TIMEOUT_SEC)
        return payload

    def client_version(self):
        binary = shutil.which(OLLAMA)
        if not binary:
            return None
        try:
            completed = subprocess.run([binary, "--version"],
                                       capture_output=True, text=True,
                                       timeout=VERSION_TIMEOUT_SEC)
        except (OSError, subprocess.SubprocessError):
            return None
        # `ollama --version` warns on stderr and reports the client version
        # anyway, which is why this works with the server down.
        return parse_client_version((completed.stdout or "") + " " +
                                    (completed.stderr or ""))

    def models_root(self, show):
        return models_root(show)


class FixtureSource(object):
    """Replay a recorded state instead of touching systemd, the network, or
    the real model store. Selected by COLOPHON_FIXTURE=<dir>.

    The *absence* of version.json is the "API refused" signal, so a stopped
    fixture is simply a directory without one rather than one carrying a
    special marker.
    """

    def __init__(self, directory, api_base):
        self.directory = directory
        self.api_base = api_base

    def _path(self, name):
        return os.path.join(self.directory, name)

    def show_text(self):
        try:
            with open(self._path("systemctl.txt")) as handle:
                return handle.read()
        except OSError:
            raise CollectError(
                "fixture has no systemctl.txt: " + str(self.directory))

    def has_binary(self):
        return not os.path.exists(self._path("no-binary"))

    def api_version(self):
        payload = _read_json(self._path("version.json"))
        return (payload, 1) if payload is not None else (None, None)

    def api_ps(self):
        return _read_json(self._path("ps.json"))

    def client_version(self):
        try:
            with open(self._path("ollama-version.txt")) as handle:
                return parse_client_version(handle.read())
        except OSError:
            return None

    def models_root(self, show):
        # A state directory may carry its own tree; otherwise every state
        # shares tests/fixtures/models, so the inventory is not duplicated
        # once per state.
        own = self._path("models")
        if os.path.isdir(own):
            return own
        parent = os.path.dirname(str(self.directory).rstrip(os.sep))
        return os.path.join(parent, "models")


def collect(source, now_sec, uptime_sec):
    show = parse_show(source.show_text())
    unit = unit_from_show(show, uptime_sec, now_sec)

    version_payload, latency = source.api_version()
    reachable = version_payload is not None
    server_version = (version_payload or {}).get("version") if reachable else None

    status = resolve_status(unit, reachable, source.has_binary())
    loaded = normalize_loaded(source.api_ps()) if reachable else []
    installed, unique_bytes = scan_installed(source.models_root(show))

    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "error": None,
        "unit": unit,
        "api": {
            "base": source.api_base,
            "reachable": reachable,
            "serverVersion": server_version,
            "clientVersion": None if reachable else source.client_version(),
            "latencyMs": latency,
        },
        "loaded": loaded,
        "installed": installed,
        "summary": {
            "loadedCount": len(loaded),
            "loadedBytes": sum(entry["sizeBytes"] for entry in loaded),
            "installedCount": len(installed),
            "installedBytes": unique_bytes,
        },
    }


def main(argv):
    api_base = DEFAULT_API_BASE
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--api-base" and args:
            api_base = args.pop(0)
        else:
            sys.stderr.write(
                "colophon_collect: unknown argument '" + arg + "'\n")
            return 2

    fixture = os.environ.get("COLOPHON_FIXTURE", "")
    source = (FixtureSource(fixture, api_base) if fixture
              else LiveSource(api_base))
    try:
        snapshot = collect(source, time.time(), uptime_seconds())
    except CollectError as error:
        sys.stderr.write("colophon: " + str(error) + "\n")
        return 1
    json.dump(snapshot, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
