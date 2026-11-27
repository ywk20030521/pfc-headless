"""Execution authorization gate for formal PFC Headless Runs.

A formal Run is only allowed when a user-approved ``pfc-interaction``
authorization is bound to it.  There is one explicit, auditable exception:
``--pilot`` creates a technical pilot that is marked
``UNACCEPTED_TECHNICAL_PILOT`` and can never be treated as a formal experiment.

This module is deliberately dependency-free so both the CLI and the library
entry points call exactly the same gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .common import HeadlessError

FORMAL = "FORMAL_AUTHORIZED"
PILOT = "UNACCEPTED_TECHNICAL_PILOT"
_MISSING = object()


@dataclass(frozen=True)
class RunAuthorization:
    """Metadata copied from a pfc-interaction ``AuthorizationRecord``."""

    authorization_id: str = ""
    research_task_id: str = ""
    decision_id: str = ""
    model_version: str = ""
    parameter_version: str = ""
    matrix_version: str = ""
    assumption_version: str = "v1"
    context_version: str = ""
    pilot: bool = False
    pilot_reason: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "RunAuthorization":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise HeadlessError("authorization must be a mapping or RunAuthorization")
        allowed = {
            "authorization_id", "research_task_id", "decision_id", "model_version",
            "parameter_version", "matrix_version", "assumption_version",
            "context_version", "pilot", "pilot_reason",
        }
        # ``status`` is derived by ``to_record`` and may be present when a
        # persisted record is fed back in; never trust it as an input.
        value = {k: v for k, v in value.items() if k != "status"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise HeadlessError(f"Unknown authorization fields: {unknown}")
        return cls(**value)

    def validate(self) -> None:
        if self.pilot:
            if self.authorization_id:
                raise HeadlessError("--pilot cannot be combined with --authorization-id")
            if not self.pilot_reason.strip():
                raise HeadlessError("--pilot requires an explicit --pilot-reason")
            return
        for name in (
            "authorization_id", "research_task_id", "decision_id",
            "model_version", "parameter_version", "matrix_version",
        ):
            if not str(getattr(self, name) or "").strip():
                raise HeadlessError(
                    f"Formal Run requires user authorization: missing {name}. "
                    "Obtain an authorization from pfc-interaction or pass --pilot "
                    "for a technical pilot."
                )
        if not re.fullmatch(r"auth-[A-Za-z0-9._-]+", self.authorization_id):
            raise HeadlessError(f"Invalid authorization_id format: {self.authorization_id!r}")

    def to_record(self) -> dict[str, Any]:
        """Metadata stored on the immutable Run record."""
        self.validate()
        status = PILOT if self.pilot else FORMAL
        return {
            "status": status,
            "pilot": self.pilot,
            "authorization_id": self.authorization_id or None,
            "research_task_id": self.research_task_id or None,
            "decision_id": self.decision_id or None,
            "model_version": self.model_version or None,
            "parameter_version": self.parameter_version or None,
            "matrix_version": self.matrix_version or None,
            "assumption_version": self.assumption_version or "v1",
            "context_version": self.context_version or None,
            "pilot_reason": self.pilot_reason or None,
        }


def resolve_authorization(value: Any = _MISSING, **kwargs: Any) -> RunAuthorization:
    """Resolve and validate an authorization from CLI args or a mapping.

    No authorization object means no formal Run.  The caller must opt into a
    technical pilot explicitly (``pilot=True`` plus a reason).
    """
    if value is _MISSING:
        value = kwargs or {}
    if value is None:
        raise HeadlessError(
            "Formal Run rejected: no execution authorization. "
            "Pass --authorization-id with research_task_id/decision_id/version "
            "bindings, or pass --pilot with --pilot-reason for a technical pilot."
        )
    auth = RunAuthorization.from_mapping(value)
    auth.validate()
    return auth


def gate_run_record(record: dict[str, Any]) -> dict[str, Any]:
    """Re-check authorization from a persisted Run record before submission.

    Blocks legacy Runs and any Run whose authorization block was removed or
    downgraded after preparation.
    """
    auth = record.get("authorization")
    if not isinstance(auth, dict):
        raise HeadlessError(
            f"Run {record.get('run_id')} has no execution authorization; "
            "refusing to submit an unauthorized formal Run."
        )
    status = auth.get("status")
    if status == PILOT:
        if not auth.get("pilot_reason"):
            raise HeadlessError("Technical pilot is missing its explicit reason")
        return auth
    if status != FORMAL:
        raise HeadlessError(f"Run authorization status {status!r} is not accepted")
    for name in (
        "authorization_id", "research_task_id", "decision_id",
        "model_version", "parameter_version", "matrix_version",
    ):
        if not auth.get(name):
            raise HeadlessError(
                f"Run authorization is incomplete: missing {name}; refusing submission"
            )
    return auth


__all__ = [
    "FORMAL", "PILOT", "RunAuthorization", "resolve_authorization", "gate_run_record",
]
