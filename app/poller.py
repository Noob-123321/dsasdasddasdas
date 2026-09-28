"""Background Twitch poller with change-aware observation deduplication."""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .analytics import _sample_dict, detect_spikes, score_rows
from .clock import as_utc, utcnow
from .config import Settings, get_settings
from .models import (
    AlertEvent,
    AlertRule,
    Channel,
    ChannelIntel,
    ChatterAccount,
    ChatterSnapshot,
    Profile,
    ProfileChannel,
    Sample,
    SampleAggregate,
    ScoreSnapshot,
    Spike,
)
from .services.delivery import deliver_event
from .services.twitch import TwitchClient

log = logging.getLogger("tvs.poller")


class Poller:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings | None = None, client=None):
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.client = client or TwitchClient(self.settings)
        self._stop = threading.Event()
        self.stats = {
            "cycles": 0,
            "polls": 0,
            "samples": 0,
            "deduped": 0,
            "errors": 0,
            "intel": 0,
            "rosters": 0,
            "enriched": 0,
            "last_run_at": None,
            "last_success_at": None,
        }
        self._retry_at: dict[str, float] = {}
        self._retry_delay: dict[str, float] = {}

    def stop(self) -> None:
        self._stop.set()

    def run(self, max_cycles: int | None = None) -> dict:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self.poll_once()
                except Exception:
                    self.stats["errors"] += 1
                    log.exception("Ошибка цикла poller")
                self.stats["cycles"] += 1
                if max_cycles is not None and self.stats["cycles"] >= max_cycles:
                    break
                elapsed = time.monotonic() - started
                self._stop.wait(max(self.settings.poll_interval_seconds - elapsed, 0))
        finally:
            self.shutdown()
        return self.stats

    def poll_once(self, now: dt.datetime | None = None) -> int:
        moment = now or utcnow()
        polled = 0
        with self.session_factory() as db:
            channels = list(db.scalars(select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.login)))
            for channel in channels:
                if self._stop.is_set():
                    break
                if time.monotonic() < self._retry_at.get(channel.login, 0):
                    continue
                try:
                    with db.begin_nested():
                        self._poll_channel(db, channel, moment)
                    polled += 1
                    self._retry_at.pop(channel.login, None)
                    self._retry_delay.pop(channel.login, None)
                except Exception as exc:
                    self._on_error(db, channel, exc, moment)
            db.commit()
        return polled

    def poll_channel(self, login: str, now: dt.datetime | None = None) -> bool:
        """Take one immediate observation for a newly added channel."""
        moment = now or utcnow()
        with self.session_factory() as db:
            channel = db.get(Channel, login)
            if channel is None:
                return False
            self._poll_channel(db, channel, moment)
            db.commit()
            return True

    def _poll_channel(self, db: Session, channel: Channel, moment: dt.datetime) -> None:
        stats = self.client.get_channel_stats(channel.login)
        if not isinstance(stats, dict):
            raise RuntimeError("Twitch adapter returned a non-dict")
        is_live = bool(stats.get("is_live"))
        viewers = stats.get("viewer_count") if is_live else None
        chatters = stats.get("chatters_count") if is_live else None
        previous = db.scalar(select(Sample).where(Sample.channel_login == channel.login).order_by(Sample.observed_at.desc()).limit(1))
        changed = previous is None or bool(previous.is_live) != is_live or previous.viewer_count != viewers or previous.chatters_count != chatters
        if previous and not changed:
            previous.last_seen_at = moment
            previous.repeat_count = (previous.repeat_count or 1) + 1
            self.stats["deduped"] += 1
        else:
            if previous is not None:
                previous.interval_seconds = max(0.0, (moment - previous.last_seen_at).total_seconds())
            sample = Sample(
                channel_login=channel.login,
                observed_at=moment,
                last_seen_at=moment,
                repeat_count=1,
                is_live=is_live,
                viewer_count=viewers,
                chatters_count=chatters,
                title=stats.get("title"),
                game=stats.get("game"),
                chatters_error=stats.get("chatters_error"),
            )
            db.add(sample)
            self.stats["samples"] += 1
        channel.latest_is_live = is_live
        channel.latest_viewers = viewers
        channel.latest_chatters = chatters
        channel.latest_title = stats.get("title")
        channel.latest_game = stats.get("game")
        channel.latest_observed_at = moment
        channel.last_polled_at = moment
        channel.last_error = None
        channel.error_streak = 0
        channel.twitch_stream_id = str(stats.get("stream_id")) if stats.get("stream_id") else None
        if is_live:
            channel.stream_observed_until = None
        else:
            channel.stream_ended_at = channel.stream_ended_at or moment
            channel.stream_observed_until = moment
        self.stats["polls"] += 1
        self.stats["last_run_at"] = moment
        self.stats["last_success_at"] = moment
        self._record_intel(db, channel.login, stats, moment)
        self._record_roster(db, channel.login, stats, moment)
        self._enrich_chatters(db, channel.login, moment)
        self._recompute_score(db, channel.login, moment)
        self._rollup_aggregates(db, channel.login, moment)
        self._evaluate_alerts(db, channel, stats, previous, moment)

    def _record_intel(self, db: Session, login: str, stats: dict, now: dt.datetime) -> None:
        """Persist channel-level observations with the same change-aware dedup.

        Follower/title/game history only grows where the channel actually moved,
        which is what the follower-burst detector needs.
        """
        values = {
            "is_live": bool(stats.get("is_live")),
            "followers_count": stats.get("followers_count"),
            "channel_created_at": as_utc(stats.get("channel_created_at")),
            "game": stats.get("game"),
            "title": stats.get("title"),
            "stream_id": str(stats["stream_id"]) if stats.get("stream_id") else None,
            "stream_created_at": as_utc(stats.get("stream_created_at")),
            "last_broadcast_at": as_utc(stats.get("last_broadcast_at")),
        }
        previous = db.scalar(select(ChannelIntel).where(ChannelIntel.channel_login == login).order_by(ChannelIntel.observed_at.desc()).limit(1))
        unchanged = previous is not None and all(getattr(previous, key) == value for key, value in values.items())
        if unchanged:
            previous.last_seen_at = now
            previous.repeat_count = (previous.repeat_count or 1) + 1
        else:
            db.add(ChannelIntel(channel_login=login, observed_at=now, last_seen_at=now, repeat_count=1, **values))
        self.stats["intel"] += 1

    def _roster_interval_seconds(self) -> float:
        every = max(int(self.settings.chatter_roster_every), 1)
        return every * max(float(self.settings.poll_interval_seconds), 1.0)

    def _record_roster(self, db: Session, login: str, stats: dict, now: dt.datetime) -> None:
        """Store the sampled roster on a slower cadence than the viewers.

        The roster is a random slice of at most 100 logins, so polling it more
        often would not sharpen it; ``CHATTER_ROSTER_EVERY`` (default: every 10th
        poll) bounds both the writes and the later enrichment cost.
        """
        if not stats.get("is_live") or not stats.get("chatters_roster"):
            return
        last = db.scalar(select(ChatterSnapshot).where(ChatterSnapshot.channel_login == login).order_by(ChatterSnapshot.observed_at.desc()).limit(1))
        if last is not None and (now - last.observed_at).total_seconds() < self._roster_interval_seconds():
            return
        db.add(
            ChatterSnapshot(
                channel_login=login,
                observed_at=now,
                stream_id=str(stats["stream_id"]) if stats.get("stream_id") else None,
                count=stats.get("chatters_count"),
                sampled=stats.get("chatters_sampled") or len(stats.get("chatters_roster") or []),
                roster=list(stats.get("chatters_roster") or []),
                roles=dict(stats.get("chatters_roles") or {}),
            )
        )
        self.stats["rosters"] += 1

    def _enrich_chatters(self, db: Session, login: str, now: dt.datetime) -> None:
        """Enrich the oldest un-enriched roster through ``users(logins:)``.

        The ``chatter_enrich_hours`` budget is a rate limit on how often this
        channel spends a ``users(logins:)`` call, so it is measured against the
        last SUCCESSFUL enrichment -- not against the age of the snapshot.
        Gating on ``snapshot.observed_at > now - hours`` skipped every fresh
        roster instead of every recent one, and because a new roster is written
        every ``CHATTER_ROSTER_EVERY`` polls the ``ChatterAccount`` cache stayed
        permanently empty, which silently disabled the whole account-based
        detector family (fresh accounts, clustered creation dates, zero
        followers, follower bursts).

        Failures here must never fail the poll: viewers/chatters are the primary
        observation and the enrichment cache is best-effort by design.
        """
        hours = max(float(self.settings.chatter_enrich_hours), 0.0)
        snapshot = db.scalar(
            select(ChatterSnapshot)
            .where(ChatterSnapshot.channel_login == login, ChatterSnapshot.enriched_at.is_(None))
            .order_by(ChatterSnapshot.observed_at.asc())
            .limit(1)
        )
        if snapshot is None:
            return
        if hours:
            last_enriched = db.scalar(
                select(func.max(ChatterSnapshot.enriched_at)).where(
                    ChatterSnapshot.channel_login == login,
                    ChatterSnapshot.enriched_at.is_not(None),
                )
            )
            if last_enriched is not None and (now - last_enriched).total_seconds() < hours * 3600.0:
                return
        logins = sorted({str(item).lower() for item in (snapshot.roster or []) if item})
        if not logins:
            snapshot.enriched_at = now
            return
        try:
            accounts = self.client.get_accounts(logins)
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("Канал %s: обогащение чаттеров не удалось: %s", login, exc)
            return
        for item in accounts:
            row = db.get(ChatterAccount, item["login"])
            if row is None:
                row = ChatterAccount(login=item["login"])
                db.add(row)
            row.account_id = item.get("account_id")
            row.twitch_created_at = item.get("twitch_created_at")
            row.followers_count = item.get("followers_count")
            row.last_broadcast_at = item.get("last_broadcast_at")
            row.enriched_at = now
            row.source = "demo" if self.settings.twitch_source == "demo" else "gql"
            self.stats["enriched"] += 1
        snapshot.enriched_at = now

    def _rollup_aggregates(self, db: Session, login: str, now: dt.datetime) -> None:
        for bucket, minutes in (("5m", 5), ("1h", 60)):
            if bucket == "5m":
                start = now.replace(minute=(now.minute // minutes) * minutes, second=0, microsecond=0)
            else:
                start = now.replace(minute=0, second=0, microsecond=0)
            rows = list(db.scalars(select(Sample).where(Sample.channel_login == login, Sample.observed_at >= start, Sample.observed_at <= now).order_by(Sample.observed_at)))
            live = [row for row in rows if row.is_live and row.viewer_count is not None]
            if not rows:
                continue
            values = [row.viewer_count for row in live]
            chatters = [row.chatters_count for row in live if row.chatters_count is not None]
            average = round(sum(values) / len(values), 2) if values else None
            ratio = round(min(sum(chatters) / sum(values), 1.0), 5) if chatters and sum(values) else None
            existing = db.scalar(select(SampleAggregate).where(SampleAggregate.channel_login == login, SampleAggregate.bucket == bucket, SampleAggregate.bucket_start == start))
            if existing is None:
                # Databases created before migration 0002 had a uniqueness
                # constraint on (channel, bucket) only. Reuse that legacy row
                # instead of letting the poller fail on an insert conflict.
                existing = db.scalar(select(SampleAggregate).where(SampleAggregate.channel_login == login, SampleAggregate.bucket == bucket).order_by(SampleAggregate.bucket_start.desc()).limit(1))
                if existing is not None:
                    existing.bucket_start = start
            if existing is None:
                existing = SampleAggregate(channel_login=login, bucket=bucket, bucket_start=start)
                db.add(existing)
            existing.avg_viewers = average
            existing.avg_chatters = round(sum(chatters) / len(chatters), 2) if chatters else None
            existing.min_viewers = min(values) if values else None
            existing.max_viewers = max(values) if values else None
            existing.ratio = ratio
            existing.samples_count = len(rows)
            existing.poll_count = sum(row.repeat_count or 1 for row in rows)
            existing.computed_at = now

    def _recompute_score(self, db: Session, login: str, now: dt.datetime) -> None:
        rows = list(db.scalars(select(Sample).where(Sample.channel_login == login).order_by(Sample.observed_at.asc())))
        if not rows:
            return
        recent = [_sample_dict(row) for row in rows[-500:]]
        spikes = detect_spikes(recent)
        old = db.scalars(select(Spike).where(Spike.channel_login == login, Spike.peak_at >= now - dt.timedelta(days=7)))
        for row in list(old):
            db.delete(row)
        for item in spikes:
            db.add(Spike(channel_login=login, **{key: value for key, value in item.items() if key in {"started_at", "peak_at", "ended_at", "baseline_viewers", "peak_viewers", "amplitude", "shape", "is_instant", "confidence", "baseline_method", "baseline_samples", "notes"}}))
        score = score_rows(recent, spikes)
        latest = db.scalar(select(ScoreSnapshot).where(ScoreSnapshot.channel_login == login).order_by(ScoreSnapshot.computed_at.desc()).limit(1))
        if latest is None:
            latest = ScoreSnapshot(channel_login=login, computed_at=now, window_days=7)
            db.add(latest)
        latest.computed_at = now
        latest.risk_score = score["risk_score"]
        latest.confidence = score["confidence"]
        latest.verdict = score["verdict"]
        latest.factors = score["factors"]
        latest.warnings = score["warnings"]
        latest.warning_codes = score["warning_codes"]
        latest.explanation = score["explanation"]
        latest.samples_used = score["samples_used"]
        latest.window_days = 7

    def _evaluate_alerts(self, db: Session, channel: Channel, stats: dict, previous, now: dt.datetime) -> None:
        profile_rows = db.scalars(select(Profile).join(ProfileChannel, ProfileChannel.profile_id == Profile.id).where(ProfileChannel.channel_login == channel.login))
        viewers = stats.get("viewer_count")
        chatters = stats.get("chatters_count")
        ratio = chatters / viewers if viewers and chatters is not None else None
        for profile in profile_rows:
            rules = db.scalars(select(AlertRule).where(AlertRule.profile_id == profile.id, AlertRule.enabled.is_(True)))
            for rule in rules:
                if rule.channels and channel.login not in rule.channels:
                    continue
                fired = False
                severity = "warning"
                if rule.type == "viewer_spike" and previous is not None and previous.viewer_count and viewers:
                    fired = viewers / max(previous.viewer_count, 1) >= max(rule.threshold, 1.1)
                    severity = "high" if viewers / max(previous.viewer_count, 1) >= 3 else "warning"
                elif rule.type == "ratio_collapse" and ratio is not None:
                    fired = ratio <= rule.threshold
                elif rule.type == "stream_offline":
                    fired = not stats.get("is_live")
                elif rule.type == "stale_data":
                    fired = channel.latest_observed_at is not None and (now - channel.latest_observed_at).total_seconds() > 300
                elif rule.type == "score_threshold":
                    score = db.scalar(select(ScoreSnapshot).where(ScoreSnapshot.channel_login == channel.login).order_by(ScoreSnapshot.computed_at.desc()).limit(1))
                    fired = score is not None and score.risk_score is not None and score.risk_score >= rule.threshold
                if not fired:
                    continue
                recent = db.scalar(select(AlertEvent).where(AlertEvent.rule_id == rule.id, AlertEvent.channel_login == channel.login, AlertEvent.created_at >= now - dt.timedelta(seconds=rule.cooldown_seconds)).order_by(AlertEvent.created_at.desc()).limit(1))
                if recent is not None:
                    continue
                event = AlertEvent(id=f"evt_{secrets.token_hex(8)}", profile_id=profile.id, rule_id=rule.id, type=rule.type, channel_login=channel.login, severity=severity, payload={"observed": {"viewers": viewers, "chatters": chatters, "ratio": ratio}, "explanation": f"Канал {channel.login}: сработало правило {rule.type}"}, created_at=now)
                db.add(event)
                deliver_event(db, event, self.settings)

    def _evaluate_stale_alerts(self, db: Session, channel: Channel, now: dt.datetime) -> None:
        last_success = channel.latest_observed_at or channel.last_polled_at
        if last_success is None or (now - last_success).total_seconds() <= 300:
            return
        profile_rows = db.scalars(select(Profile).join(ProfileChannel, ProfileChannel.profile_id == Profile.id).where(ProfileChannel.channel_login == channel.login))
        for profile in profile_rows:
            rules = db.scalars(select(AlertRule).where(AlertRule.profile_id == profile.id, AlertRule.enabled.is_(True), AlertRule.type == "stale_data"))
            for rule in rules:
                if rule.channels and channel.login not in rule.channels:
                    continue
                recent = db.scalar(select(AlertEvent).where(AlertEvent.rule_id == rule.id, AlertEvent.channel_login == channel.login, AlertEvent.created_at >= now - dt.timedelta(seconds=rule.cooldown_seconds)).order_by(AlertEvent.created_at.desc()).limit(1))
                if recent is not None:
                    continue
                event = AlertEvent(
                    id=f"evt_{secrets.token_hex(8)}",
                    profile_id=profile.id,
                    rule_id=rule.id,
                    type="stale_data",
                    channel_login=channel.login,
                    severity="warning",
                    payload={"last_success": last_success.isoformat(), "threshold_seconds": 300, "explanation": f"Канал {channel.login}: нет успешного обновления более 5 минут"},
                    created_at=now,
                )
                db.add(event)
                deliver_event(db, event, self.settings)

    def _on_error(self, db: Session, channel: Channel, exc: Exception, now: dt.datetime | None = None) -> None:
        moment = now or utcnow()
        self.stats["errors"] += 1
        channel.error_streak += 1
        channel.last_error = str(exc)[:2000]
        self._evaluate_stale_alerts(db, channel, moment)
        delay = min(max(self._retry_delay.get(channel.login, 5) * 2, 5), 300)
        self._retry_delay[channel.login] = delay
        self._retry_at[channel.login] = time.monotonic() + delay
        log.warning("Канал %s: %s; повтор через %s сек", channel.login, exc, delay)

    def shutdown(self) -> None:
        with self.session_factory() as db:
            now = utcnow()
            for channel in db.scalars(select(Channel).where(Channel.is_active.is_(True), Channel.latest_is_live.is_(True))):
                channel.stream_observed_until = now
            db.commit()

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="tvs-poller", daemon=True)
        thread.start()
        return thread
