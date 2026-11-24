"""Versioned, allow-listed embedded data-collection plans."""
from __future__ import annotations

import re
from typing import Any

from .common import HeadlessError


PLAN_VERSION = "1.0.0"
BASE_CHANNELS = {
    "ball.position",
    "ball.radius",
    "wall.geometry",
}
EXTRA_CHANNELS = {
    "ball.velocity",
    "ball.spin",
    "wall.contact_force",
    "contact.id",
    "contact.endpoints",
    "contact.force",
    "fracture.event",
}
HISTORY_PATTERN = re.compile(r"^history\.[A-Za-z0-9_.:-]+$")
SUPPORTED_EVENTS = {"cycle", "time", "solve", "fracture"}


def _channel_record(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"id": value, "enabled": True, "required": False}
    if not isinstance(value, dict):
        raise HeadlessError("Collection channel entries must be strings or objects")
    channel_id = str(value.get("id") or "").strip()
    if not channel_id:
        raise HeadlessError("Collection channel requires id")
    return {
        "id": channel_id,
        "enabled": bool(value.get("enabled", True)),
        "required": bool(value.get("required", False)),
    }


def normalize_collection_plan(
    value: dict[str, Any] | None,
    *,
    dimension: int,
    sampling: dict[str, Any] | None = None,
    add_sampling_extras: bool = True,
    case_config: dict[str, Any] | None = None,
    seed_from_case: bool = False,
) -> dict[str, Any]:
    """Normalize a plan without silently dropping case-level capture switches.

    A case config may declare ``capture_contacts``, ``fracture_observer`` and
    ``history_names``.  An explicit plan always wins; when no explicit plan is
    supplied those declarations seed the allow-list so that later
    ``apply_plan_to_config`` cannot overwrite them with defaults.
    """
    source = dict(value or {})
    sampling = dict(sampling or {})
    case_config = dict(case_config or {})
    mode = str(source.get("mode", sampling.get("mode", "cycle")))
    interval = float(source.get("interval", sampling.get("interval", 1)))
    explicit_channels = "channels" in source
    channels = [_channel_record(item) for item in source.get("channels", [])]
    ids = {item["id"] for item in channels}
    for channel_id in BASE_CHANNELS:
        if channel_id not in ids:
            channels.append(
                {"id": channel_id, "enabled": True, "required": True}
            )
            ids.add(channel_id)

    def seed(channel_id: str, *, required: bool = False) -> None:
        if channel_id not in ids:
            channels.append(
                {"id": channel_id, "enabled": True, "required": required}
            )
            ids.add(channel_id)

    contacts_requested = bool(
        sampling.get("capture_contacts", case_config.get("capture_contacts", False))
    )
    fracture_requested = bool(
        sampling.get("fracture_observer", case_config.get("fracture_observer", False))
        or source.get("fracture_observer", False)
    )
    history_names = sampling.get("history_names")
    if history_names is None:
        history_names = case_config.get("history_names") or []
    if explicit_channels is False or add_sampling_extras or seed_from_case:
        if contacts_requested:
            for channel_id in ("contact.id", "contact.endpoints", "contact.force"):
                seed(channel_id)
        for name in history_names:
            seed(f"history.{name}")
    if seed_from_case and fracture_requested:
        seed("fracture.event")

    events = [str(item) for item in source.get("events", [])]
    if mode == "event" and not events:
        events = ["solve"]
    if (seed_from_case or source.get("fracture_observer", False)) and fracture_requested:
        if "fracture" not in events:
            events.append("fracture")
    plan = {
        "plan_version": str(source.get("plan_version", PLAN_VERSION)),
        "mode": mode,
        "interval": interval,
        "channels": channels,
        "events": sorted(set(events)),
        "dimension": int(dimension),
    }
    validate_collection_plan(plan)
    return plan


def validate_collection_plan(plan: dict[str, Any]) -> None:
    if plan.get("plan_version") != PLAN_VERSION:
        raise HeadlessError(
            f"collection_plan.plan_version must be {PLAN_VERSION!r}"
        )
    if plan.get("mode") not in {"cycle", "time", "event"}:
        raise HeadlessError("Unsupported collection plan mode")
    interval = float(plan.get("interval", -1))
    if interval < 0 or (plan.get("mode") in {"cycle", "time"} and interval <= 0):
        raise HeadlessError("Collection plan interval must be positive")
    if int(plan.get("dimension", 0)) not in {2, 3}:
        raise HeadlessError("Collection plan dimension must be 2 or 3")
    events = {str(item) for item in plan.get("events", [])}
    unknown_events = sorted(events - SUPPORTED_EVENTS)
    if unknown_events:
        raise HeadlessError(f"Unsupported collection events: {unknown_events}")
    if plan.get("mode") == "event" and not events:
        raise HeadlessError("Event collection requires a registered event")
    seen = set()
    for item in plan.get("channels", []):
        channel_id = str(item.get("id") or "")
        if channel_id in seen:
            raise HeadlessError(f"Duplicate collection channel: {channel_id}")
        seen.add(channel_id)
        supported = (
            channel_id in BASE_CHANNELS
            or channel_id in EXTRA_CHANNELS
            or HISTORY_PATTERN.fullmatch(channel_id) is not None
        )
        if not supported and bool(item.get("required", False)):
            raise HeadlessError(
                f"Required collection channel is not supported: {channel_id}"
            )
    if any(
        item.get("id") == "contact.force"
        and item.get("required", False)
        and not any(
            other.get("id") in {"contact.id", "contact.endpoints"}
            and other.get("enabled", True)
            for other in plan.get("channels", [])
        )
        for item in plan.get("channels", [])
    ):
        raise HeadlessError("contact.force requires contact identity channels")


def plan_channel_ids(plan: dict[str, Any]) -> set[str]:
    return {
        str(item["id"])
        for item in plan.get("channels", [])
        if item.get("enabled", True)
    }


def apply_plan_to_config(
    config: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    result = dict(config)
    channels = plan_channel_ids(plan)
    result["collection_plan"] = plan
    result["sample_mode"] = plan["mode"]
    result["sample_interval"] = plan["interval"]
    if plan["mode"] == "cycle":
        result["sample_stride_cycles"] = max(1, int(plan["interval"] or 1))
    elif plan["mode"] == "time":
        result["sample_interval_time"] = float(plan["interval"])
    if plan["mode"] == "event":
        result["sample_on_events"] = True
    result["capture_contacts"] = bool(
        {"contact.id", "contact.endpoints", "contact.force"} & channels
    )
    result["fracture_observer"] = (
        "fracture.event" in channels or "fracture" in plan.get("events", [])
    )
    result["history_names"] = sorted(
        item.split(".", 1)[1]
        for item in channels
        if item.startswith("history.")
    )
    result["field_status_plan"] = {
        item["id"]: (
            "REAL_PFC"
            if item.get("enabled", True)
            else "NOT_CAPTURED"
        )
        for item in plan.get("channels", [])
    }
    return result
