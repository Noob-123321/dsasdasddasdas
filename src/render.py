"""Единый рендер консольного отчёта.

Один и тот же текст использует и CLI (src/index.py), и веб-оболочка
(src/server.py) — поэтому вывод на сайте выглядит ровно так же, как в cmd.
"""

WIDTH = 60


def build_report(channel_login, state, poll_interval_ms):
    """Собирает строки отчёта (без очистки экрана).

    state — dict с ключами:
      is_live, total_viewers, chatters_count, stream_title, last_error
    """
    lines = []
    lines.append('=' * WIDTH)
    lines.append(f' Twitch канал: #{channel_login}')
    lines.append('=' * WIDTH)

    if not state.get('is_live'):
        lines.append(' Статус: 🔴 оффлайн (стрим не идёт)')
    else:
        lines.append(' Статус: 🟢 в эфире')
        if state.get('stream_title'):
            lines.append(f' Название: {state["stream_title"]}')

    lines.append('-' * WIDTH)

    total = state.get('total_viewers')
    raw_chatters = state.get('chatters_count')

    if total is None:
        lines.append(' Всего зрителей:            н/д (стрим оффлайн)')
    else:
        lines.append(f' Всего зрителей:            {total}')

    if raw_chatters is None:
        lines.append(' Авторизованных (в чате):   н/д')
    elif total is None:
        lines.append(f' Авторизованных (в чате):   {raw_chatters}')
    else:
        authorized = min(raw_chatters, total)
        guests = max(total - authorized, 0)
        lines.append(f' Авторизованных (в чате):   {authorized}')
        lines.append(f' Гостей (примерно):         {guests}')

    lines.append('-' * WIDTH)
    lines.append(' * "Авторизованные" — залогиненные пользователи в списке')
    lines.append('   чата канала (то же, что показывают расширения Twitch).')
    lines.append(' * "Гости" = всего зрителей − авторизованные.')
    lines.append(' * Если авторизованных в чате больше, чем зрителей, число')
    lines.append('   ограничивается сверху общим количеством зрителей.')

    if state.get('last_error'):
        lines.append('-' * WIDTH)
        lines.append(f' ⚠ Последняя ошибка: {state["last_error"]}')

    lines.append('=' * WIDTH)
    lines.append(
        f' Обновление каждые {round(poll_interval_ms / 1000)} сек. Ctrl+C для выхода.'
    )
    return lines


def empty_state():
    return {
        'total_viewers': None,
        'chatters_count': None,
        'stream_title': None,
        'is_live': False,
        'last_error': None,
    }


def counts(state):
    """Разбор чисел: authorized / guests (та же логика, что и в отчёте)."""
    total = state.get('total_viewers')
    raw_chatters = state.get('chatters_count')

    if raw_chatters is None:
        authorized = None
    elif total is None:
        authorized = raw_chatters
    else:
        authorized = min(raw_chatters, total)

    if total is None or authorized is None:
        guests = None
    else:
        guests = max(total - authorized, 0)

    return {
        'total_viewers': total,
        'chatters_count': raw_chatters,
        'authorized': authorized,
        'guests': guests,
    }