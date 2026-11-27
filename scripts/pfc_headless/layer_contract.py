"""Canonical dataset layer vocabulary shared across PFC Skills.

The three Skills used incompatible layer words: Headless had
RAW_DATA/ANALYSIS_DATA/DISPLAY_DATA, Visualization omitted RAW_DATA, and the
architecture spec requires RAW/STANDARDIZED/DERIVED.  This module provides a
single, backward-compatible mapping so callers can normalise legacy labels
without rewriting stored datasets.

Legacy constants remain valid inputs; canonical names are the output.
"""
from __future__ import annotations

from typing import Dict

CANONICAL_LAYERS = ("RAW", "STANDARDIZED", "DERIVED")

LEGACY_TO_CANONICAL: Dict[str, str] = {
    "RAW": "RAW",
    "RAW_DATA": "RAW",
    "STANDARDIZED_DATA": "STANDARDIZED",
    "STANDARDIZED": "STANDARDIZED",
    "INPUT_DATA": "STANDARDIZED",
    "ANALYSIS_DATA": "DERIVED",
    "DERIVED": "DERIVED",
    "DERIVED_DATA": "DERIVED",
    "DISPLAY_DATA": "DERIVED",
}

# Ownership: who may write each canonical layer.
LAYER_OWNER = {
    "RAW": "pfc-headless",
    "STANDARDIZED": "pfc-headless",
    "DERIVED": "pfc-scientific-visualization",
}

# Which layers a Skill may consume.
LAYER_CONSUMER = {
    "RAW": ("pfc-headless",),
    "STANDARDIZED": ("pfc-scientific-visualization", "pfc-research-evidence"),
    "DERIVED": ("pfc-interaction", "pfc-research-evidence"),
}


def normalize_layer(value: str) -> str:
    """Map a legacy or canonical layer label to the canonical vocabulary."""
    key = str(value or "").strip().upper()
    if key not in LEGACY_TO_CANONICAL:
        raise ValueError(f"Unknown dataset layer: {value!r}")
    return LEGACY_TO_CANONICAL[key]


def can_write(skill: str, layer: str) -> bool:
    """Only the owning Skill may write a canonical layer."""
    return LAYER_OWNER.get(normalize_layer(layer)) == skill


__all__ = [
    "CANONICAL_LAYERS", "LEGACY_TO_CANONICAL", "LAYER_OWNER", "LAYER_CONSUMER",
    "normalize_layer", "can_write",
]
