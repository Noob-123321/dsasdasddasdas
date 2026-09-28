"""Retention cleanup for raw observations, fine aggregates and detection data."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..clock import utcnow
from ..models import ChannelIntel, ChatterAccount, ChatterSnapshot, Sample, SampleAggregate


def prune(
    db: Session,
    *,
    raw_days: int = 30,
    aggregate_days: int = 14,
    intel_days: int = 30,
    roster_days: int = 30,
    account_days: int = 90,
) -> dict[str, int]:
    now = utcnow()
    raw_cutoff = now - dt.timedelta(days=raw_days)
    aggregate_cutoff = now - dt.timedelta(days=aggregate_days)
    intel_cutoff = now - dt.timedelta(days=intel_days)
    roster_cutoff = now - dt.timedelta(days=roster_days)
    account_cutoff = now - dt.timedelta(days=account_days)
    raw = db.execute(delete(Sample).where(Sample.observed_at < raw_cutoff)).rowcount or 0
    fine = db.execute(delete(SampleAggregate).where(SampleAggregate.bucket == "5m", SampleAggregate.bucket_start < aggregate_cutoff)).rowcount or 0
    intel = db.execute(delete(ChannelIntel).where(ChannelIntel.observed_at < intel_cutoff)).rowcount or 0
    rosters = db.execute(delete(ChatterSnapshot).where(ChatterSnapshot.observed_at < roster_cutoff)).rowcount or 0
    accounts = db.execute(delete(ChatterAccount).where(ChatterAccount.enriched_at < account_cutoff)).rowcount or 0
    db.commit()
    return {
        "raw_samples": raw,
        "fine_aggregates": fine,
        "channel_intel": intel,
        "chatter_snapshots": rosters,
        "chatter_accounts": accounts,
    }
