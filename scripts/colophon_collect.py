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
