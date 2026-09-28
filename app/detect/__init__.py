"""Bot / view-farm detection layer: pure functions, no database, no network.

Input is an expanded per-minute timeline (:mod:`app.detect.series`) plus channel
intel; output is a :class:`app.detect.score.DetectionReport` whose factors carry
the numbers that produced them. Detect, then show why.
"""
from .series import Point, deltas, expand_series, live_points, mad, median, quantile, values
from .types import Finding, clamp, scale

__all__ = [
    "Finding",
    "Point",
    "clamp",
    "deltas",
    "expand_series",
    "live_points",
    "mad",
    "median",
    "quantile",
    "scale",
    "values",
]
