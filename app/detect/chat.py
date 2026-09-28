"""Chat liveness detectors: a dead chat under a large audience.

Every statistic here is computed on the *expanded* per-minute timeline produced
by :func:`app.detect.series.expand_series` (a step function), never on raw
``Sample`` rows: 59-63% of consecutive rows are identical because the poller
deduplicates changes, so flatness measured on raw rows describes the poller
instead of the channel.

Inputs
------
``points``
    The expanded window under analysis (normally one stream). Points without
    data (``viewers is None``, a gap longer than ``max_gap_minutes``) end a
    "still" run and are excluded from every median.
``stream_points``
    Optional narrower window belonging to the same stream. When given, it is the
    window used for the early/late split of ``chat_collapse`` ("the channel's own
    earlier median *within this stream*"); otherwise ``points`` is used.
``chat_events``
    Iterable of dicts with ``author_login`` and ``ts``. The current anonymous
    client **cannot read chat messages** (CommunityTab returns a sampled roster,
    not messages), so the production adapter passes nothing and
    ``single_chatter_dominance`` stays silent. The unavailable state is exposed
    by :func:`chat_message_input_state` so the pipeline can lower confidence and
    list the metric as unavailable instead of scoring it as "passed".

Scoring notes
-------------
No finding is emitted for a signal that did not fire, and no finding is emitted
to report a healthy channel. ``observed`` carries the raw numbers that produced
the finding; ``note_args`` carries the same numbers rounded for display and the
matching ``note_code``/``note_<code>`` i18n entries live with the UI templates.

Genre baselines
---------------
``starvation_floor`` accepts an optional ``adjustments`` mapping of *product*
multipliers, but it is **off by default and no genre baseline has been measured
yet** for this repo. The parameter exists so a future, measured per-genre table
can be plugged in without changing the detector; with ``adjustments`` falsy the
``genre`` argument has no effect at all.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Sequence

from app.detect.series import Point, median
from app.detect.types import Finding, scale

WEIGHTS: dict[str, float] = {
    "silent_chat": 0.16,
    "chat_starvation_ratio": 0.12,
    "chat_collapse": 0.10,
    "message_rate": 0.10,
    "single_chatter_dominance": 0.08,
    "passive_viewer_caveat": 0.0,
}

#: Below this viewer count a chatters/viewers ratio is meaningless.
MEANINGFUL_VIEWERS = 50.0
#: Chat is "silent" when the reported chatter count holds this long.
STILL_MINUTES = 10.0
#: A share estimate needs at least this many readable messages.
MIN_MESSAGES = 10
#: One author writing this share of the messages is suspicious.
DOMINANCE_SHARE = 0.80
#: Minimum number of minutes with a known chatter count before the per-minute
#: change of a single minute says anything.
MIN_RATE_MINUTES = 10
#: A minute whose chatter count did not move at all, relative to the window's
#: own median chatter count: the honest channels measured in the live DB all sit
#: at 0.47-0.65, so only a much higher share is evidence of a frozen counter.
FROZEN_STALE_SHARE = 0.80
#: Below this the chatter count never moves at all: one value for the window.
FROZEN_MOVEMENT = 0.0
#: A minute counts as "unpaired" when chatters moved this much (relative to the
#: median chatter count) while viewers stayed inside this band (relative to the
#: median viewer count): chat churn with no audience movement behind it.
UNPAIRED_CHAT_MOVE = 0.02
UNPAIRED_VIEWER_MOVE = 0.005
#: Minimum number of minutes on each side of a collapse boundary.
MIN_SEGMENT_POINTS = 3

_CAVEAT_NOTE = (
    "Зрители не называются ботами: сигналы ({triggered_by}) говорят только о "
    "необычном соотношении активных авторов чата и зрителей."
)
_CAVEAT_EXPLANATION = (
    "Число активных авторов берётся из CommunityTab и является приблизительной "
    "оценкой (выборка по запросу, а не полный список). Плоский или низкий чат "
    "встречается у тихих каналов, в режиме «только подписчики» и при "
    "модерации; сигнал требует ручной проверки и не является доказательством."
)


def starvation_floor(viewers, *, genre=None, adjustments=None) -> float | None:
    """Minimum acceptable ``chatters/viewers`` for a channel with ``viewers`` watchers.

    ``None`` below :data:`MEANINGFUL_VIEWERS` (50): at that scale a handful of
    chatters makes the ratio jump, so it carries no information. Above it the
    floor rises monotonically towards the 0.09 asymptote::

        floor(v) = 0.02 + 0.07 * (1 - 50 / v)

    which keeps the repo's reference rows consistent -- 300/30 (ratio 0.1) stays
    above ``floor(300) = 0.078``, while 500/1 (ratio 0.002) is far below
    ``floor(500) = 0.083``.

    ``adjustments`` is an optional ``{genre: multiplier}`` mapping of *product*
    adjustments (a ``"default"`` key is applied when ``genre`` is ``None``). No
    genre baseline has been measured for this repo yet, so it defaults to
    ``None``/empty and is off; passing ``genre`` alone never changes the result.
    """
    if viewers is None:
        return None
    count = float(viewers)
    if count < MEANINGFUL_VIEWERS:
        return None
    floor = 0.02 + 0.07 * (1.0 - MEANINGFUL_VIEWERS / count)
    if adjustments:
        key = "default" if genre is None else genre
        floor *= float(adjustments.get(key, 1.0))
    return min(max(floor, 0.0), 1.0)


def chat_message_input_state(chat_events) -> tuple[str, str]:
    """Whether chat *messages* are readable: ``(state, detail)``.

    ``"unavailable"`` -- no readable messages at all (``None``, empty, or events
    without ``author_login``); the anonymous client must report the metric as
    unavailable and lower confidence instead of assuming it passed.
    ``"insufficient"`` -- some messages, fewer than :data:`MIN_MESSAGES`, so no
    share can be estimated. ``"available"`` -- enough messages for a share.
    """
    if chat_events is None:
        return "unavailable", "no chat message source: anonymous reads expose no messages (0 events)"
    events = list(chat_events)
    usable = [event for event in events if _event_author(event)]
    if not usable:
        return "unavailable", f"no readable chat messages ({len(events)} events without author_login)"
    if len(usable) < MIN_MESSAGES:
        return "insufficient", f"{len(usable)} readable chat messages, {MIN_MESSAGES} needed for a share estimate"
    return "available", f"{len(usable)} readable chat messages"


def chat_findings(
    points: Sequence[Point],
    *,
    chat_events: Iterable | None = None,
    stream_points: Sequence[Point] | None = None,
) -> list[Finding]:
    """All chat-liveness findings for one analyzed window, in a fixed order."""
    window = list(points or [])
    findings: list[Finding] = []
    findings.extend(_silent_chat(window))
    findings.extend(_starvation(window))
    collapse_window = list(stream_points) if stream_points else window
    findings.extend(_collapse(collapse_window))
    findings.extend(_message_rate(window, chat_events))
    findings.extend(_dominance(chat_events))
    if findings:
        findings.append(_caveat([finding.code for finding in findings], window))
    return findings


def _event_author(event) -> str | None:
    """``author_login`` of a chat event (dict or attribute object), normalised."""
    if isinstance(event, dict):
        author = event.get("author_login")
    else:
        author = getattr(event, "author_login", None)
    if author is None:
        return None
    author = str(author).strip()
    return author or None


def _observed_points(points: Sequence[Point]) -> list[Point]:
    """Points usable for ratio math: viewers present and positive, chatters known."""
    return [
        point
        for point in points
        if point.viewers is not None and point.viewers > 0 and point.chatters is not None
    ]


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _silent_chat(points: Sequence[Point]) -> list[Finding]:
    """Longest run of a frozen chatter count on a channel with viewers >= 50."""
    runs: list[list[Point]] = []
    current: list[Point] = []
    for point in points:
        if point.viewers is None or point.chatters is None or point.viewers < MEANINGFUL_VIEWERS:
            current = []
            continue
        if current and point.chatters == current[-1].chatters:
            current.append(point)
        else:
            if current:
                runs.append(current)
            current = [point]
    if current:
        runs.append(current)

    best: tuple[list[Point], float] | None = None
    for run in runs:
        minutes = (run[-1].ts - run[0].ts).total_seconds() / 60.0
        if minutes < STILL_MINUTES:
            continue
        if best is None or minutes > best[1]:
            best = (run, minutes)
    if best is None:
        return []

    run, minutes = best
    viewers_median = median(point.viewers for point in run)
    start_ts = run[0].ts.isoformat()
    end_ts = run[-1].ts.isoformat()
    chatters = int(run[0].chatters)
    observed = {
        "viewers_median": float(viewers_median),
        "chatters": chatters,
        "still_minutes": minutes,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }
    # A frozen chatter counter is not the same thing as a dead chat: at 26k
    # chatters the room is loud and the *counter* simply did not tick. Name
    # what was measured so the number is not read as "nobody is talking".
    if viewers_median and chatters / viewers_median < 0.05:
        summary = "Чат молчит при большом онлайне"
        detail = f"активных авторов всего {chatters} на {int(viewers_median)} зрителей"
    else:
        summary = "Счётчик чата замер"
        detail = f"при {chatters} активных авторах на {int(viewers_median)} зрителей"
    finding = Finding(
        code="silent_chat",
        score=scale(minutes, STILL_MINUTES - 1.0, 30.0),
        weight=WEIGHTS["silent_chat"],
        observed=observed,
        note=(
            f"{summary}: {detail}, а число активных авторов не менялось {_round(minutes, 1)} мин подряд "
            f"({start_ts} — {end_ts})."
        ),
        explanation=(
            "Замороженный счётчик чата при большом онлайне характерен для накрученных зрителей, "
            "но так же выглядит тихий стрим, режим «только подписчики» или медленная модерация."
        ),
        note_code="note_silent_chat",
        note_args={
            "viewers_median": _round(viewers_median, 2),
            "chatters": chatters,
            "still_minutes": _round(minutes, 1),
            "start_ts": start_ts,
            "end_ts": end_ts,
        },
    )
    return [finding]


def _starvation(points: Sequence[Point]) -> list[Finding]:
    """Median ``chatters/viewers`` below the viewer-aware floor."""
    data = _observed_points(points)
    if not data:
        return []
    viewers_median = median(point.viewers for point in data)
    floor = starvation_floor(viewers_median)
    if floor is None or floor <= 0.0:
        return []
    ratio_median = median(point.chatters / point.viewers for point in data)
    if ratio_median is None or ratio_median >= floor:
        return []

    minutes = len(data)
    observed = {
        "ratio_median": ratio_median,
        "floor": floor,
        "viewers_median": float(viewers_median),
        "minutes": minutes,
    }
    finding = Finding(
        code="chat_starvation_ratio",
        score=scale(floor - ratio_median, 0.0, floor),
        weight=WEIGHTS["chat_starvation_ratio"],
        observed=observed,
        note=(
            f"Медиана отношения активные авторы/зрители {_round(ratio_median)} ниже минимального порога "
            f"{_round(floor)} для медианы {_round(viewers_median, 2)} зрителей "
            f"(наблюдений: {minutes} мин)."
        ),
        explanation=(
            "Порог растёт с онлайном: доля пишущих в чат падает на крупных каналах, поэтому "
            "единая константа неприменима. Порог — оценочная кривая; жанровая поправка пока не "
            "измерена и по умолчанию выключена."
        ),
        note_code="note_chat_starvation_ratio",
        note_args={
            "ratio_median": _round(ratio_median),
            "floor": _round(floor),
            "viewers_median": _round(viewers_median, 2),
            "minutes": minutes,
        },
    )
    return [finding]


def _collapse(points: Sequence[Point]) -> list[Finding]:
    """Ratio at least halved versus the window's own earlier median, viewers rising.

    Every split of the window into "earlier" and "later" is scored; the winning
    split has the largest drop, ties resolved towards the most balanced split
    (closest to the middle of the window).
    """
    data = _observed_points(points)
    if len(data) < 2 * MIN_SEGMENT_POINTS:
        return []

    best: dict | None = None
    best_key: tuple[float, float] | None = None
    for index in range(MIN_SEGMENT_POINTS, len(data) - MIN_SEGMENT_POINTS + 1):
        early, late = data[:index], data[index:]
        early_ratio = median(point.chatters / point.viewers for point in early)
        if not early_ratio:
            continue
        late_ratio = median(point.chatters / point.viewers for point in late)
        if late_ratio is None or late_ratio > early_ratio * 0.5:
            continue
        early_viewers = median(point.viewers for point in early)
        late_viewers = median(point.viewers for point in late)
        if early_viewers is None or late_viewers is None or late_viewers <= early_viewers:
            continue
        drop_ratio = 1.0 - late_ratio / early_ratio
        key = (drop_ratio, -abs(2 * index - len(data)))
        if best_key is None or key > best_key:
            best_key = key
            best = {
                "early_ratio": early_ratio,
                "late_ratio": late_ratio,
                "drop_ratio": drop_ratio,
                "early_viewers": float(early_viewers),
                "late_viewers": float(late_viewers),
                "boundary_ts": late[0].ts.isoformat(),
            }
    if best is None:
        return []

    finding = Finding(
        code="chat_collapse",
        score=scale(best["drop_ratio"], 0.49, 0.9),
        weight=WEIGHTS["chat_collapse"],
        observed=best,
        note=(
            f"Отношение активные авторы/зрители упало с {_round(best['early_ratio'])} до "
            f"{_round(best['late_ratio'])} (падение {_round(best['drop_ratio'])} от прежнего уровня) "
            f"у границы {best['boundary_ts']}, при этом медиана зрителей выросла с "
            f"{_round(best['early_viewers'], 2)} до {_round(best['late_viewers'], 2)}."
        ),
        explanation=(
            "Зрители выросли, а пишущих стало относительно вдвое меньше — так выглядит приток "
            "зрителей без интереса к чату (или уход живого чата при сохранении онлайна)."
        ),
        note_code="note_chat_collapse",
        note_args={
            "early_ratio": _round(best["early_ratio"]),
            "late_ratio": _round(best["late_ratio"]),
            "drop_ratio": _round(best["drop_ratio"]),
            "early_viewers": _round(best["early_viewers"], 2),
            "late_viewers": _round(best["late_viewers"], 2),
            "boundary_ts": best["boundary_ts"],
        },
    )
    return [finding]


def _per_minute_messages(chat_events, window: list[Point]) -> tuple[list[float], bool]:
    """Real messages per minute from readable chat events, when they exist.

    Returns ``(rates, complete)``. ``complete`` is ``True`` only when the events
    carry usable timestamps; ``rates`` covers **every minute of the window**,
    counting the silent ones as zero. Counting only the minutes that happen to
    hold a message would make a dead chat look busy, because a message source
    reports precisely the minutes in which somebody spoke.

    The anonymous client cannot read messages, so this returns ``([], False)``
    in production and the caller falls back to the chatter-count proxy.
    """
    events = [event for event in (chat_events or []) if _event_author(event)]
    if len(events) < MIN_MESSAGES:
        return [], False
    per_minute: dict[dt.datetime, float] = {}
    for point in window:
        per_minute[point.ts] = 0.0
    for event in events:
        raw = event.get("ts") if isinstance(event, dict) else getattr(event, "ts", None)
        if not isinstance(raw, dt.datetime):
            return [], False
        key = raw.replace(second=0, microsecond=0)
        per_minute[key] = per_minute.get(key, 0.0) + 1.0
    return [per_minute[key] for key in sorted(per_minute)], True


def _message_rate(points: Sequence[Point], chat_events=None) -> list[Finding]:
    """Chatter turnover per minute, and what a frozen counter implies.

    True "messages per minute" is **not available anonymously**: the public
    client-id is rejected for every chat-message field, so the production
    adapter passes no ``chat_events``. What is available is the change of the
    reported chatter count minute over minute, which measures how fast the
    population of people in chat turns over. The finding is named and worded
    as that proxy, never as counted messages.

    Real events win when the source ever provides them: a complete per-minute
    message capture replaces the proxy rather than sitting next to it.
    """
    data = [point for point in points if point.chatters is not None and point.viewers is not None]
    if len(data) < MIN_RATE_MINUTES:
        return []

    rates, from_messages = _per_minute_messages(chat_events, data)
    # The chatter median is always the reported chatter count, whichever source
    # produced the rate: it is context, not a rate.
    chatters_median = median(float(point.chatters) for point in data) or 0.0
    if from_messages and len(rates) >= 2:
        # Counted messages: `per_minute` is already "messages in that minute",
        # so the chatter-count join/leave split below does not apply.
        source = "chat_events"
        per_minute = list(rates)
    else:
        source = "chatters_proxy"
        if chatters_median <= 0:
            return []
        chatters = [float(point.chatters) for point in data]
        per_minute = [abs(right - left) for left, right in zip(chatters, chatters[1:])]
        if not per_minute:
            return []
    minutes = len(per_minute)
    stale_minutes = sum(1 for value in per_minute if value == 0.0)
    stale_share = stale_minutes / minutes
    messages_per_minute = median(per_minute) or 0.0
    joined = sum(value for value in per_minute if value > 0) if source == "chatters_proxy" else 0.0
    left = sum(value for value in per_minute if value < 0) if source == "chatters_proxy" else 0.0
    chatter_turnover = joined - left
    if source == "chatters_proxy":
        movement = (joined + abs(left)) / minutes / chatters_median
    else:
        movement = 1.0

    viewers = [float(point.viewers) for point in data]
    viewers_median = median(viewers) or 0.0
    unpaired_minutes = 0
    if viewers_median > 0 and source == "chatters_proxy" and chatters_median > 0:
        for left_point, right_point in zip(data, data[1:]):
            chat_move = abs(right_point.chatters - left_point.chatters) / chatters_median
            viewer_move = abs(right_point.viewers - left_point.viewers) / viewers_median
            if chat_move >= UNPAIRED_CHAT_MOVE and viewer_move < UNPAIRED_VIEWER_MOVE:
                unpaired_minutes += 1
    unpaired_share = unpaired_minutes / minutes if minutes else 0.0

    frozen = viewers_median >= MEANINGFUL_VIEWERS and (
        movement <= FROZEN_MOVEMENT or stale_share >= FROZEN_STALE_SHARE
    )
    erratic = unpaired_share >= 0.5
    if not (frozen or erratic):
        return []

    if frozen and erratic:
        score = max(
            scale(stale_share, FROZEN_STALE_SHARE - 0.05, 1.0),
            scale(unpaired_share, 0.5, 1.0),
        )
    elif frozen:
        score = scale(stale_share, FROZEN_STALE_SHARE - 0.05, 1.0)
    else:
        score = 0.5 * scale(unpaired_share, 0.5, 1.0)

    observed = {
        "source": source,
        "messages_per_minute": _round(messages_per_minute, 3),
        "chatter_turnover": _round(chatter_turnover, 3),
        "stale_minutes": stale_minutes,
        "stale_share": _round(stale_share, 4),
        "unpaired_minutes": unpaired_minutes,
        "unpaired_share": _round(unpaired_share, 4),
        "movement": _round(movement, 5),
        "chatters_median": _round(chatters_median, 2),
        "viewers_median": _round(viewers_median, 2),
        "minutes": minutes,
        "frozen": frozen,
        "erratic": erratic,
    }
    reason = "счётчик чата замёр" if frozen else "споры колебаний чата без движения онлайна"
    finding = Finding(
        code="message_rate",
        score=round(min(max(score, 0.0), 1.0), 4),
        weight=WEIGHTS["message_rate"],
        observed=observed,
        note=(
            f"Прокси сообщений в минуту (Δ активных авторов): {_round(messages_per_minute, 1)} в минуту "
            f"при медиане {observed['chatters_median']} активных авторов и {observed['viewers_median']} зрителей "
            f"({minutes} мин, из них {stale_minutes} мин без изменений — доля {observed['stale_share']}). "
            f"Причина: {reason}."
        ),
        explanation=(
            "Анонимный клиент Twitch не отдаёт сообщения чата, поэтому «сообщений в минуту» "
            "считается по изменению числа активных авторов, а не по самим сообщениям. "
            "Это прокси: он показывает скорость оборота чата, но не количество реплик. "
            "Замёрший счётчик при живом онлайне и разнонаправленные колебания чата без "
            "соответствующего движения зрителей — признаки пассивной или накрученной аудитории; "
            "тот же след оставляет модерация, тихий стрим и задержки опроса."
        ),
        note_code="note_message_rate",
        note_args=dict(observed),
    )
    return [finding]


def _dominance(chat_events) -> list[Finding]:
    """One account writing >= 80% of >= 10 readable chat messages."""
    events = list(chat_events) if chat_events is not None else []
    state, _detail = chat_message_input_state(events)
    if state != "available":
        return []
    usable = [event for event in events if _event_author(event)]
    counts = Counter(_event_author(event) for event in usable)
    top_author, top_count = counts.most_common(1)[0]
    messages = len(usable)
    top_share = top_count / messages
    if top_share < DOMINANCE_SHARE:
        return []

    score = 0.5 * scale(top_share, DOMINANCE_SHARE - 0.01, 1.0) + 0.5 * scale(messages, MIN_MESSAGES - 1.0, 50.0)
    top_share_percent = _round(top_share * 100.0, 1)
    finding = Finding(
        code="single_chatter_dominance",
        score=score,
        weight=WEIGHTS["single_chatter_dominance"],
        observed={"messages": messages, "top_author": top_author, "top_share": top_share},
        note=(
            f"Почти весь читаемый чат пишет один аккаунт: {top_author} — {top_share_percent}% "
            f"прочитанных сообщений чата (всего {messages} сообщений)."
        ),
        explanation=(
            "Доля считается по прочитанным сообщениям чата; при малой выборке один активный "
            "автор встречается и на живых каналах, поэтому сигнал слабый."
        ),
        note_code="note_single_chatter_dominance",
        note_args={
            "messages": messages,
            "top_author": top_author,
            "top_share": _round(top_share),
            "top_share_percent": top_share_percent,
        },
    )
    return [finding]


def _caveat(triggered_by: Sequence[str], points: Sequence[Point]) -> Finding:
    """Neutral weight-0 disclaimer emitted next to every chat finding."""
    viewers_median = median(point.viewers for point in points if point.viewers is not None)
    observed = {
        "triggered_by": list(triggered_by),
        "viewers_median": float(viewers_median) if viewers_median is not None else 0.0,
    }
    return Finding(
        code="passive_viewer_caveat",
        score=0.0,
        weight=WEIGHTS["passive_viewer_caveat"],
        observed=observed,
        note=_CAVEAT_NOTE.format(triggered_by=", ".join(triggered_by)),
        explanation=_CAVEAT_EXPLANATION,
        note_code="note_passive_viewer_caveat",
        note_args={
            "triggered_by": ", ".join(triggered_by),
            "viewers_median": _round(observed["viewers_median"], 2),
        },
    )


__all__ = [
    "MEANINGFUL_VIEWERS",
    "WEIGHTS",
    "chat_findings",
    "chat_message_input_state",
    "starvation_floor",
]
