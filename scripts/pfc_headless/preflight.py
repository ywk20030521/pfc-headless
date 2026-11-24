"""Static preflight checks for PFC case configurations.

These checks run at ``run prepare`` time and never execute PFC.  They catch
the two most expensive failure modes observed in practice:

1. Invalid PFC command keywords (e.g. ``xvelocity`` instead of
   ``velocity-x``) that previously only surfaced deep in a failed run's
   ``metadata/result.json``.
2. Impossible timestep budgets (a tiny timestep with a large target time)
   that previously turned a run into a multi-hour, uninterruptible hang.
"""
from __future__ import annotations

import re
from typing import Any

from .common import HeadlessError


# Attribute keywords accepted by ``ball attribute`` / ``wall attribute``.
# PFC uses hyphenated component names; the v-name aliases (xvelocity etc.)
# are NOT valid and are a common authoring mistake.
_BALL_ATTRIBUTE_TOKENS = {
    "acceleration", "acceleration-x", "acceleration-y", "acceleration-z",
    "density", "displacement", "displacement-x", "displacement-y", "displacement-z",
    "damp", "euler", "euler-x", "euler-y", "euler-z",
    "force-applied", "force-applied-x", "force-applied-y", "force-applied-z",
    "force-contact", "force-contact-x", "force-contact-y", "force-contact-z",
    "fragment", "moment-applied", "moment-applied-x", "moment-applied-y",
    "moment-applied-z", "moment-contact", "moment-contact-x", "moment-contact-y",
    "moment-contact-z", "position", "position-x", "position-y", "position-z",
    "radius", "spin", "spin-x", "spin-y", "spin-z",
    "velocity", "velocity-x", "velocity-y", "velocity-z",
    "xvelocity", "yvelocity", "zvelocity",  # tracked below as invalid aliases
}
_INVALID_ATTRIBUTE_ALIASES = {
    "xvelocity": "velocity-x", "yvelocity": "velocity-y", "zvelocity": "velocity-z",
    "xforce": "force-applied-x", "yforce": "force-applied-y", "zforce": "force-applied-z",
}

_SOLVE_TIME_RE = re.compile(r"^\s*model\s+solve\s+time\s+([0-9.eE+-]+)", re.I)
_SOLVE_CYCLES_RE = re.compile(r"^\s*model\s+solve\s+cycles\s+([0-9]+)", re.I)


def preflight_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a report with ``warnings`` and raise on hard errors."""
    errors: list[str] = []
    warnings: list[str] = []
    commands: list[str] = []
    for key in ("setup", "post_solve"):
        commands.extend(str(c) for c in (config.get(key) or []))
    solve = str(config.get("solve") or "").strip()
    if solve:
        commands.append(solve)
    save = str(config.get("save") or "").strip()
    if save:
        commands.append(save)

    for index, command in enumerate(commands):
        # Invalid attribute aliases
        match = re.match(
            r"^\s*(?:ball|wall)\s+attribute\s+(.+)$", command, re.I
        )
        if match:
            tokens = re.split(r"\s+", match.group(1).strip())
            for token in tokens:
                alias = _INVALID_ATTRIBUTE_ALIASES.get(token.lower())
                if alias:
                    errors.append(
                        f"Command {index}: invalid attribute keyword '{token}' "
                        f"(use '{alias}') in: {command!r}"
                    )
        # Unknown ball/wall attribute tokens (warn only; PFC evolves)
        if match:
            # Only inspect tokens before a PFC `range` selector.
            attr_part = re.split(r"\s+range\s+", match.group(1).strip(), maxsplit=1, flags=re.I)[0]
            tokens = re.split(r"\s+", attr_part.strip())
            for token in tokens:
                if re.fullmatch(r"[a-z-]+", token.lower()) and token.lower() not in _BALL_ATTRIBUTE_TOKENS:
                    warnings.append(
                        f"Command {index}: unrecognised attribute keyword '{token}' "
                        f"in: {command!r}"
                    )

    # Timestep budget estimation (informational; cannot know timestep here)
    time_match = _SOLVE_TIME_RE.match(solve) if solve else None
    cycles_match = _SOLVE_CYCLES_RE.match(solve) if solve else None
    budget: dict[str, Any] = {"available": False}
    if solve:
        budget = {
            "available": True,
            "mode": "time" if time_match else ("cycles" if cycles_match else "other"),
            "target_time": float(time_match.group(1)) if time_match else None,
            "target_cycles": int(cycles_match.group(1)) if cycles_match else None,
            "segmented": bool(config.get("solve_segment_cycles", 0)),
        }
        if time_match and not budget["segmented"]:
            warnings.append(
                "Long 'model solve time' is not segmented. Set "
                "solve_segment_cycles (e.g. 500) to keep the bridge "
                "responsive and tasks interruptible."
            )

    if errors:
        raise HeadlessError("PFC command preflight failed:\n  - " + "\n  - ".join(errors))

    return {
        "status": "PASS" if not warnings else "PASS_WITH_WARNINGS",
        "checked_commands": len(commands),
        "errors": errors,
        "warnings": warnings,
        "timestep_budget": budget,
    }
