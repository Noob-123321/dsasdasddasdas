"""CommunityTab roster + ``users(logins:)`` enrichment detector (spec §3.4, idea #6).

The ``roster`` input is the CommunityTab sample: at most 100 logins that the
anonymous client returns as a **randomised alphabetical slice** (two polls 20 s
apart shared 0 % of their logins). It is a sample of the channel's chatters and
**never the population** -- nothing here may be read as "this channel has N bots
among its M chatters". Every threshold below is therefore a *share of the
enriched sample*, not an absolute count of the channel.

What the findings mean:

* ``fresh_account_cluster`` -- >= 3 sampled chatters whose account is at most 30
  days old and who are >= 12 % of the age sample. Measured baseline: tumblurr 2 %,
  xqc 0 %, so the share is what separates the two.
* ``clustered_creation_dates`` -- >= 3 sampled chatters created on the same
  calendar day: farms buy accounts in batches.
* ``zero_follower_cluster`` -- >= 40 % of the follower sample has 0 followers.
  Measured on normal channels this is high (tumblurr 87 %, xqc 71 %), so it is a
  deliberately weak signal and carries the LOW weight 0.05.
* ``follower_burst`` -- the channel's own ``followers.totalCount`` grew >= 3x
  between the first and the last observation of one and the same stream.
* ``follow_without_viewing`` -- that same >= 3x follower growth while the stream's
  median viewers stayed flat (< 10 % change). The user's key point: followers are
  not viewers.

Inputs and honesty rules:

* ``accounts`` is the ``users(logins:)`` enrichment keyed by login; a login the
  query did not return is *unknown*, never a zero-age / zero-follower account.
* Age findings use only records with ``created_at``; the zero-follower finding
  uses only records with ``followers``. ``sampled`` in ``observed`` is the size of
  that metric's sample, not the roster length.
* Fewer than 3 enriched accounts means the sample cannot say anything, so the
  function returns ``[]`` -- including the no-enrichment case and including when
  ``follower_history`` has data.
* ``follower_history`` is the channel's own follower/stream intel and is compared
  within a single ``stream_id`` only (first vs last observation of that stream).
* ``viewer_median`` / ``observed_minutes`` are context/confidence only: they never
  change a verdict, they only enrich ``explanation``.
* Pure module: stdlib + :mod:`app.detect.types` only.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence

from app.detect.types import Finding, clamp

WEIGHTS: dict[str, float] = {
    "fresh_account_cluster": 0.18,
    "clustered_creation_dates": 0.16,
    "zero_follower_cluster": 0.05,
    "follower_burst": 0.08,
    "follow_without_viewing": 0.10,
}

MIN_ENRICHED_ACCOUNTS = 3
MIN_CLUSTER_SIZE = 3
FRESH_MAX_AGE_DAYS = 30.0
FRESH_MIN_SHARE = 0.12
ZERO_FOLLOWER_MIN_SHARE = 0.40
FOLLOWER_BURST_RATIO = 3.0
VIEWERS_FLAT_TOLERANCE = 0.10

#: Placeholder for a value the input did not carry, used in ``note_args`` only.
NOT_AVAILABLE = "н/д"


# --------------------------------------------------------------------------- #
# small normalisers
# --------------------------------------------------------------------------- #
def _field(entry: object, name: str, default=None):
    if entry is None:
        return default
    if isinstance(entry, Mapping):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _as_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _naive_utc(moment) -> dt.datetime | None:
    """Naive-UTC datetime for a datetime input, ``None`` for anything else."""
    if not isinstance(moment, dt.datetime):
        return None
    if moment.tzinfo is not None and moment.utcoffset() is not None:
        return moment.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return moment


def _iso(moment: dt.datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment is not None else None


def _normalise_login(login) -> str:
    return str(login).strip().lower()


def _unique_logins(roster: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for login in roster or ():
        key = _normalise_login(login)
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _records(roster: Iterable[str], accounts: Mapping | None) -> list[dict]:
    """Enrichment records for the roster logins that ``users(logins:)`` returned."""
    index: dict[str, object] = {}
    for login, entry in (accounts or {}).items():
        key = _normalise_login(login)
        if key and key not in index:
            index[key] = entry
    records: list[dict] = []
    for login in _unique_logins(roster):
        entry = index.get(login)
        if entry is None:
            continue
        created_at = _naive_utc(_field(entry, "created_at"))
        followers = _as_int(_field(entry, "followers"))
        account_id = _field(entry, "id")
        if created_at is None and followers is None and account_id is None:
            continue  # the row exists but carries no information
        records.append(
            {"login": login, "created_at": created_at, "followers": followers, "id": account_id}
        )
    return records


def _context(viewer_median: float | None, observed_minutes: float | None) -> str:
    """Context fragment for ``explanation``; never influences a verdict."""
    parts: list[str] = []
    if viewer_median is not None:
        parts.append(f"медиана онлайна {viewer_median:g}")
    if observed_minutes:
        parts.append(f"наблюдение {observed_minutes:g} мин")
    return f"Контекст: {', '.join(parts)}." if parts else ""


def _ratio_score(ratio: float, threshold: float = FOLLOWER_BURST_RATIO) -> float:
    """0.5 at the firing threshold, 1.0 at twice the threshold."""
    return clamp(ratio / (2.0 * threshold))


# --------------------------------------------------------------------------- #
# follower-history helpers
# --------------------------------------------------------------------------- #
def _ordered_history(history: Sequence | None) -> list:
    entries = list(history or ())
    stamps = [_naive_utc(_field(entry, "observed_at")) for entry in entries]
    if entries and all(stamp is not None for stamp in stamps):
        return [entry for _, entry in sorted(zip(stamps, entries), key=lambda pair: pair[0])]
    return entries


def _stream_groups(history: Sequence) -> list[tuple[str, list]]:
    groups: dict[str, list] = {}
    order: list[str] = []
    for entry in history:
        stream_id = _field(entry, "stream_id")
        if stream_id is None or str(stream_id).strip() == "":
            continue
        key = str(stream_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)
    return [(key, groups[key]) for key in order]


def _follower_span(group: Sequence) -> dict | None:
    """First/last follower observation of one stream, when it grew >= 3x."""
    points: list[tuple[dt.datetime | None, int]] = []
    for entry in group:
        followers = _as_int(_field(entry, "followers"))
        if followers is None:
            continue
        points.append((_naive_utc(_field(entry, "observed_at")), followers))
    if len(points) < 2:
        return None
    first_ts, first = points[0]
    last_ts, last = points[-1]
    if first <= 0:
        return None  # a ratio from zero is not a growth factor
    ratio = last / first
    if ratio < FOLLOWER_BURST_RATIO:
        return None
    return {
        "first_ts": first_ts,
        "first_followers": first,
        "last_ts": last_ts,
        "last_followers": last,
        "ratio": ratio,
    }


def _as_float(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _viewer_edge(group: Sequence) -> tuple[float | None, float | None]:
    """``viewers_median`` of the first and the last observation of one stream.

    An edge without intel stays ``None`` (that is how the caller can tell a stream
    with no viewer data from one whose viewer data is only half known).
    """
    if not group:
        return None, None
    return _as_float(_field(group[0], "viewers_median")), _as_float(
        _field(group[-1], "viewers_median")
    )


def _viewers_flat(first: float | None, last: float | None) -> bool:
    if first is None and last is None:
        return True  # no viewer intel at all: the follower signal stands alone
    if first is None or last is None:
        return False  # only one edge known -- flatness is unknown, do not claim it
    if first == 0:
        return last == 0
    return abs(last - first) / abs(first) < VIEWERS_FLAT_TOLERANCE


def _viewers_ratio(first: float | None, last: float | None) -> float | None:
    if first is None or last is None or first == 0:
        return None
    return last / first


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def account_findings(
    roster: Sequence[str],
    accounts: Mapping[str, Mapping | object],
    *,
    follower_history: Sequence[Mapping] | None = None,
    viewer_median: float | None = None,
    observed_minutes: float = 0.0,
    now: dt.datetime | None = None,
) -> list[Finding]:
    """Detection findings from the sampled CommunityTab roster and channel intel.

    ``roster`` is the <=100 login sample (never the population), ``accounts`` the
    ``users(logins:)`` enrichment, ``follower_history`` the channel's own
    ``{observed_at, followers, stream_id, viewers_median}`` rows in time order.
    Returns ``[]`` when fewer than :data:`MIN_ENRICHED_ACCOUNTS` roster logins were
    enriched -- the sample is too small to say anything about the channel.
    """
    records = _records(roster, accounts)
    if len(records) < MIN_ENRICHED_ACCOUNTS:
        return []

    moment = _naive_utc(now) or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    context = _context(viewer_median, observed_minutes)
    findings: list[Finding] = []

    aged: list[tuple[dict, float]] = [
        (record, (moment - record["created_at"]).total_seconds() / 86400.0)
        for record in records
        if record["created_at"] is not None
    ]

    # --- fresh_account_cluster ------------------------------------------- #
    if aged:
        fresh = [(record, age) for record, age in aged if 0.0 <= age <= FRESH_MAX_AGE_DAYS]
        share = len(fresh) / len(aged)
        if len(fresh) >= MIN_CLUSTER_SIZE and share >= FRESH_MIN_SHARE:
            ages_days = sorted(round(age, 1) for _, age in fresh)
            findings.append(
                Finding(
                    code="fresh_account_cluster",
                    score=clamp(share / (2.0 * FRESH_MIN_SHARE)),
                    weight=WEIGHTS["fresh_account_cluster"],
                    observed={
                        "fresh": len(fresh),
                        "sampled": len(aged),
                        "share": round(share, 4),
                        "threshold_share": FRESH_MIN_SHARE,
                        "max_age_days": FRESH_MAX_AGE_DAYS,
                        "ages_days": ages_days,
                    },
                    note=(
                        f"Свежие аккаунты: {len(fresh)} из {len(aged)} ({share:.1%}) "
                        f"созданы не более {FRESH_MAX_AGE_DAYS:.0f} дн. назад."
                    ),
                    explanation=(
                        f"Возраст свежих аккаунтов (дней): {', '.join(f'{age:g}' for age in ages_days)}. "
                        f"Порог: не менее {FRESH_MIN_SHARE:.0%} выборки. {context}"
                    ).strip(),
                    note_code="note_fresh_account_cluster",
                    note_args={
                        "fresh": len(fresh),
                        "sampled": len(aged),
                        "share": share,
                        "threshold_share": FRESH_MIN_SHARE,
                        "max_age_days": int(FRESH_MAX_AGE_DAYS),
                        "ages_days": ", ".join(f"{age:g}" for age in ages_days),
                    },
                )
            )

    # --- clustered_creation_dates ---------------------------------------- #
    if aged:
        by_day: dict[str, int] = {}
        for record, _age in aged:
            day = record["created_at"].date().isoformat()
            by_day[day] = by_day.get(day, 0) + 1
        best_count = max(by_day.values())
        if best_count >= MIN_CLUSTER_SIZE:
            day = min(candidate for candidate, count in by_day.items() if count == best_count)
            share = best_count / len(aged)
            findings.append(
                Finding(
                    code="clustered_creation_dates",
                    score=clamp(best_count / float(2 * MIN_CLUSTER_SIZE)),
                    weight=WEIGHTS["clustered_creation_dates"],
                    observed={
                        "day": day,
                        "count": best_count,
                        "sampled": len(aged),
                        "share": round(share, 4),
                        "days": len(by_day),
                    },
                    note=(
                        f"Аккаунтов, созданных в один день ({day}): {best_count} из {len(aged)} "
                        f"({share:.1%})."
                    ),
                    explanation=(
                        f"Всего различных дат создания в выборке: {len(by_day)}. "
                        f"Порог: не менее {MIN_CLUSTER_SIZE} аккаунтов в один день. {context}"
                    ).strip(),
                    note_code="note_clustered_creation_dates",
                    note_args={
                        "day": day,
                        "count": best_count,
                        "sampled": len(aged),
                        "share": share,
                        "days": len(by_day),
                    },
                )
            )

    # --- zero_follower_cluster (low weight on purpose) -------------------- #
    followed = [record for record in records if record["followers"] is not None]
    if len(followed) >= MIN_CLUSTER_SIZE:
        zero_followers = sum(1 for record in followed if record["followers"] == 0)
        share = zero_followers / len(followed)
        if share >= ZERO_FOLLOWER_MIN_SHARE:
            findings.append(
                Finding(
                    code="zero_follower_cluster",
                    score=clamp(share / (2.0 * ZERO_FOLLOWER_MIN_SHARE)),
                    weight=WEIGHTS["zero_follower_cluster"],
                    observed={
                        "zero_followers": zero_followers,
                        "sampled": len(followed),
                        "share": round(share, 4),
                        "threshold_share": ZERO_FOLLOWER_MIN_SHARE,
                    },
                    note=(
                        f"{zero_followers} из {len(followed)} аккаунтов ({share:.1%}) без подписчиков."
                    ),
                    explanation=(
                        "Слабый сигнал сам по себе (на обычных каналах доля высока), "
                        f"поэтому вес понижен до {WEIGHTS['zero_follower_cluster']}. {context}"
                    ).strip(),
                    note_code="note_zero_follower_cluster",
                    note_args={
                        "zero_followers": zero_followers,
                        "sampled": len(followed),
                        "share": share,
                        "threshold_share": ZERO_FOLLOWER_MIN_SHARE,
                    },
                )
            )

    # --- follower intel: burst / followers without viewers ---------------- #
    spans: list[tuple[str, dict, float | None, float | None]] = []
    for stream_id, group in _stream_groups(_ordered_history(follower_history)):
        span = _follower_span(group)
        if span is None:
            continue
        first_viewers, last_viewers = _viewer_edge(group)
        spans.append((stream_id, span, first_viewers, last_viewers))

    if spans:
        best = max(spans, key=lambda item: item[1]["ratio"])
        stream_id, span = best[0], best[1]
        ratio = span["ratio"]
        first_ts = _iso(span["first_ts"])
        last_ts = _iso(span["last_ts"])
        findings.append(
            Finding(
                code="follower_burst",
                score=_ratio_score(ratio),
                weight=WEIGHTS["follower_burst"],
                observed={
                    "stream_id": stream_id,
                    "first_followers": span["first_followers"],
                    "last_followers": span["last_followers"],
                    "ratio": round(ratio, 2),
                    "first_ts": first_ts,
                    "last_ts": last_ts,
                },
                note=(
                    f"Подписчики выросли в {ratio:.2f} раза за один стрим {stream_id}: "
                    f"{span['first_followers']} -> {span['last_followers']}."
                ),
                explanation=(
                    f"Первое наблюдение {first_ts or NOT_AVAILABLE}, последнее {last_ts or NOT_AVAILABLE}. "
                    f"Порог роста: {FOLLOWER_BURST_RATIO:g}x внутри одного stream_id. {context}"
                ).strip(),
                note_code="note_follower_burst",
                note_args={
                    "stream_id": stream_id,
                    "first_followers": span["first_followers"],
                    "last_followers": span["last_followers"],
                    "ratio": round(ratio, 2),
                    "first_ts": first_ts or NOT_AVAILABLE,
                    "last_ts": last_ts or NOT_AVAILABLE,
                },
            )
        )

        flat_spans = [item for item in spans if _viewers_flat(item[2], item[3])]
        if flat_spans:
            best_flat = max(flat_spans, key=lambda item: item[1]["ratio"])
            stream_id, span = best_flat[0], best_flat[1]
            first_viewers, last_viewers = best_flat[2], best_flat[3]
            ratio = span["ratio"]
            viewers_ratio = _viewers_ratio(first_viewers, last_viewers)
            findings.append(
                Finding(
                    code="follow_without_viewing",
                    score=_ratio_score(ratio),
                    weight=WEIGHTS["follow_without_viewing"],
                    observed={
                        "followers_ratio": round(ratio, 2),
                        "viewers_ratio": None if viewers_ratio is None else round(viewers_ratio, 4),
                        "first_viewers": first_viewers,
                        "last_viewers": last_viewers,
                        "stream_id": stream_id,
                    },
                    note=(
                        f"Подписчики выросли в {ratio:.2f} раза, а медиана онлайна не изменилась "
                        f"({first_viewers if first_viewers is not None else NOT_AVAILABLE} -> "
                        f"{last_viewers if last_viewers is not None else NOT_AVAILABLE})."
                    ),
                    explanation=(
                        "Рост подписчиков без роста онлайна: подписки не приходят от зрителей стрима. "
                        f"Порог: рост в {FOLLOWER_BURST_RATIO:g}x и изменение медианы < "
                        f"{VIEWERS_FLAT_TOLERANCE:.0%}. {context}"
                    ).strip(),
                    note_code="note_follow_without_viewing",
                    note_args={
                        "followers_ratio": round(ratio, 2),
                        "viewers_ratio": (
                            NOT_AVAILABLE if viewers_ratio is None else round(viewers_ratio, 4)
                        ),
                        "first_viewers": (
                            NOT_AVAILABLE if first_viewers is None else first_viewers
                        ),
                        "last_viewers": (
                            NOT_AVAILABLE if last_viewers is None else last_viewers
                        ),
                        "stream_id": stream_id,
                    },
                )
            )

    return findings
