"""SQLAlchemy models for profiles, tokens, observations and operations."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .clock import utcnow
from .db import Base


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(128), default="Профиль")
    unlimited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_channels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class AccessToken(Base):
    __tablename__ = "access_tokens"
    __table_args__ = (
        UniqueConstraint("lookup_hash", name="uq_access_tokens_lookup_hash"),
        Index("ix_access_tokens_kind", "kind", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="profile", nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="Ключ", nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AccountSession(Base):
    __tablename__ = "account_sessions"
    __table_args__ = (Index("ix_account_sessions_token", "token_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(String(40), ForeignKey("access_tokens.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("lookup_hash", name="uq_api_keys_lookup_hash"),
        Index("ix_api_keys_parent", "parent_token_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    parent_token_id: Mapped[str] = mapped_column(String(40), ForeignKey("access_tokens.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="API key", nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=lambda: ["read"], nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    requests_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (Index("ix_channels_active", "is_active", "login"),)

    login: Mapped[str] = mapped_column(String(25), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    track_reason: Mapped[str] = mapped_column(String(32), default="profile", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_polled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    twitch_stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stream_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    stream_observed_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    stream_ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    latest_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_chatters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latest_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_game: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ProfileChannel(Base):
    __tablename__ = "profile_channels"
    __table_args__ = (UniqueConstraint("profile_id", "channel_login", name="uq_profile_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="profile", nullable=False)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Sample(Base):
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("channel_login", "observed_at", "is_live", name="uq_sample_dedup"),
        Index("ix_samples_channel_time", "channel_login", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    viewer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chatters_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    game: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chatters_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SampleAggregate(Base):
    __tablename__ = "sample_aggregates"
    __table_args__ = (UniqueConstraint("channel_login", "bucket", "bucket_start", name="uq_sample_aggregate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    bucket: Mapped[str] = mapped_column(String(8), nullable=False)
    bucket_start: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    avg_viewers: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_chatters: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    poll_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Spike(Base):
    __tablename__ = "spikes"
    __table_args__ = (Index("ix_spikes_channel_time", "channel_login", "peak_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    peak_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    baseline_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amplitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    shape: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    is_instant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_method: Mapped[str] = mapped_column(String(32), default="median_mad", nullable=False)
    baseline_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (Index("ix_scores_channel_time", "channel_login", "computed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(4), default="nd", nullable=False)
    factors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    warning_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    samples_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    channels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_profile_time", "profile_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_login: Mapped[str | None] = mapped_column(String(25), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ChatterSnapshot(Base):
    """One sampled CommunityTab roster.

    The roster is a randomised alphabetical slice of at most 100 logins, not the
    channel population, so these rows support distribution statistics (account
    age, follower counts across the sample) and nothing else.
    """

    __tablename__ = "chatter_snapshots"
    __table_args__ = (Index("ix_chatter_snapshots_channel_time", "channel_login", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sampled: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roster: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    roles: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ChatterAccount(Base):
    """Cached ``users(logins:)`` enrichment, keyed by login.

    Enrichment costs one batched HTTP call per 100 logins, so results live here
    and are refreshed at most once every ``chatter_enrich_hours`` per channel.
    """

    __tablename__ = "chatter_accounts"

    login: Mapped[str] = mapped_column(String(25), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    twitch_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_broadcast_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    enriched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="gql", nullable=False)


class ChannelIntel(Base):
    """Change-aware channel-level observations (followers, title, game, stream).

    Like ``Sample`` this row is extended in place while nothing changes, so the
    follower history keeps exactly the points where the channel actually moved.
    """

    __tablename__ = "channel_intel"
    __table_args__ = (
        UniqueConstraint("channel_login", "observed_at", name="uq_channel_intel_dedup"),
        Index("ix_channel_intel_channel_time", "channel_login", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_login: Mapped[str] = mapped_column(ForeignKey("channels.login", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    game: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stream_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_broadcast_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ServerMetric(Base):
    __tablename__ = "server_metrics"
    __table_args__ = (Index("ix_server_metrics_time", "metric_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_time: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_profiles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p50_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    p95_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    poller_polls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    poller_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    poller_backlog: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    twitch_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
