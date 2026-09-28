"""Shared value types for the detection package.

The package is pure: no database access, no network, no FastAPI. Every detector
receives already-loaded numbers and returns :class:`Finding` objects that carry
the raw evidence (``observed``) next to the human explanation, so the UI can
always show *why* something fired.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    """One fired detection signal.

    ``score`` is 0..1 and describes how strongly the signal fired, ``weight`` is
    the signal's share in the aggregate index. ``observed`` holds the raw numbers
    that produced the finding and is rendered verbatim by the UI.
    """

    code: str
    score: float
    weight: float
    observed: dict
    note: str
    explanation: str = ""
    note_code: str = ""
    note_args: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a float into [low, high]; NaN collapses to ``low``."""
    if value != value:  # NaN
        return low
    return max(low, min(high, value))


def scale(value: float, low: float, high: float) -> float:
    """Linear 0..1 mapping of ``value`` from [low, high], clamped."""
    if high <= low:
        return 0.0
    return clamp((value - low) / (high - low))
