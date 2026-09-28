import re
from urllib.parse import urlparse

_LOGIN_RE = re.compile(r'^[a-z0-9_]{1,25}$', re.I)


def is_valid_login(login: str) -> bool:
    return bool(_LOGIN_RE.match(login))


def extract_channel_login(input_str) -> str:
    """Извлекает логин канала (например, "asmongold") из ссылки на Twitch
    или возвращает строку как есть, если это уже похоже на логин.
    Поддерживает:
      https://www.twitch.tv/asmongold
      https://twitch.tv/asmongold?foo=bar
      twitch.tv/asmongold
      asmongold
    """
    if not input_str or not isinstance(input_str, str):
        raise ValueError('Не передана ссылка или имя канала Twitch')

    trimmed = input_str.strip()

    # Пробуем распарсить как URL (с протоколом или без)
    with_protocol = trimmed
    if not re.match(r'^https?://', trimmed, re.I):
        with_protocol = f'https://{trimmed}'

    try:
        url = urlparse(with_protocol)
        if re.search(r'(^|\.)twitch\.tv$', url.hostname or '', re.I):
            segments = [s for s in url.path.split('/') if s]
            if segments:
                login = segments[0].lower()
                if is_valid_login(login):
                    return login
    except ValueError:
        # не URL — обрабатываем ниже как "голый" логин
        pass

    bare_login = re.sub(r'^@', '', trimmed).lower()
    if is_valid_login(bare_login):
        return bare_login

    raise ValueError(f'Не удалось распознать имя канала из "{input_str}"')