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
