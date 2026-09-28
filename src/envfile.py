"""Минимальный загрузчик .env без внешних зависимостей.

Если файл не найден, переменные просто не подставляются — проект работает
анонимно и без .env.
"""
import os

DEFAULT_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'
)


def load_dotenv(path=None):
    """Читает KEY=VALUE из .env и подставляет в os.environ (не перезатирая)."""
    target = path or DEFAULT_ENV_PATH
    if not target or not os.path.isfile(target):
        return False
    with open(target, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return True