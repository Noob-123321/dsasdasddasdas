"""Веб-оболочка проекта: минималистичный сайт + JSON API.

Только стандартная библиотека Python — как и в остальном проекте.

  python src/server.py
  WEB_PORT=9000 python src/server.py

Страницы лежат в public/, данные отдаёт /api/*:
  GET  /api/config              — тарифы и настройки
  GET  /api/subscription        — состояние подписки канала
  GET  /api/stats               — отчёт по каналу (нужна активная подписка)
  POST /api/subscribe           — покупка подписки
  POST /api/payments/webhook    — уведомление платёжного провайдера
  POST /api/admin/confirm       — ручное подтверждение оплаты (ADMIN_TOKEN)
"""
import hmac
import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import channel
import envfile
import payments
import render
import subscriptions
from twitch_gql_client import TwitchGqlClient

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

PUBLIC_DIR = os.path.join(ROOT_DIR, 'public')

envfile.load_dotenv()

HOST = os.environ.get('WEB_HOST', '127.0.0.1')
PORT = int(os.environ.get('WEB_PORT', '8000'))
POLL_INTERVAL_MS = int(os.environ.get('POLL_INTERVAL_MS', '15000'))
CACHE_TTL_MS = int(os.environ.get('CACHE_TTL_MS', '5000'))
ADMIN_TOKEN = (os.environ.get('ADMIN_TOKEN') or '').strip()
WEBHOOK_SECRET = (os.environ.get('PAYMENT_WEBHOOK_SECRET') or '').strip()
PUBLIC_BASE_URL = (os.environ.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')

STORE = subscriptions.SubscriptionStore()
TWITCH = TwitchGqlClient()


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class BadRequest(HttpError):
    def __init__(self, message):
        super().__init__(400, message)


class NotFound(HttpError):
    def __init__(self, message):
        super().__init__(404, message)


# --- проверка истёкших подписок в фоне ------------------------------------
def expire_watcher():
    while True:
        time.sleep(60)
        try:
            STORE.deactivate_expired()
        except Exception:
            traceback.print_exc()


# --- кэш отчётов по каналу ------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()


def _cache_get(login):
    with _cache_lock:
        entry = _cache.get(login)
    if not entry or time.time() - entry['at'] > CACHE_TTL_MS / 1000:
        return None
    return entry['value']


def _cache_put(login, value):
    with _cache_lock:
        _cache[login] = {'at': time.time(), 'value': value}


def channel_report(login):
    """Отчёт по каналу: строки консоли + числа. Кэш на CACHE_TTL_MS."""
    cached = _cache_get(login)
    if cached is not None:
        return cached

    state = render.empty_state()
    error = None
    try:
        stats = TWITCH.get_channel_stats(login)
        state['is_live'] = stats['is_live']
        state['total_viewers'] = stats['viewer_count']
        state['stream_title'] = stats['title']
        state['chatters_count'] = stats['chatters_count']
    except Exception as err:  # сеть/Twitch — показываем строкой ошибки в отчёте
        error = str(err)
        state['last_error'] = error

    report = {
        'state': state,
        'counts': render.counts(state),
        'error': error,
        'console': render.build_report(login, state, POLL_INTERVAL_MS),
        'fetched_at': int(time.time() * 1000),
    }
    _cache_put(login, report)
    return report


# --- подписка и доступ ----------------------------------------------------
def public_subscription(login):
    subscription = STORE.get(login)
    if not subscription:
        return None
    return {
        'login': subscription['login'],
        'plan': subscription['plan'],
        'plan_title': subscription['plan_title'],
        'status': subscription['status'],
        'price_rub': subscription['price_rub'],
        'started_at': subscription['started_at'],
        'expires_at': subscription['expires_at'],
        'days_left': subscriptions.days_left(subscription),
    }


def access_for(login, key):
    """active — оплачено и ключ канала подошёл;
    locked — подписка есть, но ключ не передан/неверный;
    none — подписки нет; expired — срок истёк."""
    subscription = STORE.get(login)
    if not subscription:
        return {'status': 'none', 'active': False}
    if subscription.get('status') != 'active':
        return {'status': 'expired', 'active': False}
    if not subscriptions.key_matches(login, key):
        return {'status': 'locked', 'active': False}
    return {'status': 'active', 'active': True}


# --- тестовая касса -------------------------------------------------------
_demo_lock = threading.Lock()
_demo_queue = {}


def demo_checkout(login, plan_code):
    """Эмуляция оплаты с очередью: запросы по одному каналу обрабатываются
    по одному, каждый следующий становится в очередь."""
    with _demo_lock:
        queue = _demo_queue.setdefault(login, [])
        if plan_code not in queue:
            queue.append(plan_code)
        position = queue.index(plan_code)
        if position == 0:
            payment_id = STORE.new_payment_id()
            queue.pop(0)
            if not queue:
                _demo_queue.pop(login, None)
            STORE.activate(login, plan_code, payment_id)
            return {'queued': False, 'position': 0, 'size': 1}
        return {'queued': True, 'position': position, 'size': len(queue)}


def yookassa_checkout(login, plan_code, origin):
    """Реальный платёж ЮKassa — возвращает ссылку на страницу оплаты."""
    plan = subscriptions.plan_or_default(plan_code)
    payment_id = STORE.new_payment_id()
    return_url = f'{origin}/?payment=return&payment_id={payment_id}&login={login}'
    url = payments.build_yookassa_payment(payment_id, plan, STORE, return_url, login)
    return {
        'queued': True,
        'position': 1,
        'size': 1,
        'confirmation_url': url,
        'payment_id': payment_id,
    }


def manual_checkout(login, plan_code):
    """Оплата вне сайта: подтверждает админ через /api/admin/confirm."""
    plan = subscriptions.plan_or_default(plan_code)
    payment_id = STORE.new_payment_id()
    STORE.mark_payment_pending(payment_id, None, {
        'login': login,
        'plan': plan['code'],
        'amount_rub': plan['price_rub'],
        'provider': 'manual',
    })
    return {'queued': True, 'position': 1, 'size': 1, 'payment_id': payment_id}


def _rate_hits_clean(now, window):
    for ip in list(_rate_hits):
        hits = [moment for moment in _rate_hits[ip] if now - moment < window]
        if hits:
            _rate_hits[ip] = hits
        else:
            del _rate_hits[ip]


# --- простейший лимит запросов на покупку --------------------------------
_rate_lock = threading.Lock()
_rate_hits = {}


def rate_limit(ip, limit=60, window=60.0):
    now = time.time()
    with _rate_lock:
        hits = [moment for moment in _rate_hits.get(ip, []) if now - moment < window]
        if len(hits) >= limit:
            retry_after = max(1, int(window - (now - hits[0])))
            _rate_hits[ip] = hits
            return False, retry_after
        hits.append(now)
        _rate_hits[ip] = hits
        if len(_rate_hits) > 500:
            _rate_hits_clean(now, window)
        return True, 0


# --- HTTP ----------------------------------------------------------------
MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.json': 'application/json; charset=utf-8',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'TwitchViewersBot'
    protocol_version = 'HTTP/1.1'

    # --- утилиты --------------------------------------------------------
    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({'ok': False, 'error': message}, status)

    def read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise BadRequest('Некорректный Content-Length')
        if length <= 0:
            return {}
        if length > 65536:
            raise BadRequest('Слишком большой запрос')
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise BadRequest('Ожидается JSON')
        if not isinstance(data, dict):
            raise BadRequest('Ожидается JSON-объект')
        return data

    def read_body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b''

    def client_ip(self):
        forwarded = (self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        return forwarded or (self.client_address[0] if self.client_address else '')

    def base_url(self):
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL
        host = self.headers.get('Host')
        return f'http://{host}' if host else f'http://{HOST}:{PORT}'

    def require_login(self, raw):
        try:
            return channel.extract_channel_login(raw)
        except ValueError as err:
            raise BadRequest(str(err))

    def key_from(self, params):
        return (params.get('key') or params.get('license') or [''])[0] or self.headers.get('X-License-Key')

    def require_plan(self, code):
        if code is None or str(code).strip() == '':
            return subscriptions.plan_or_default(None)
        name = str(code).strip().lower()
        if name not in subscriptions.PLANS:
            raise BadRequest('Неизвестный тариф')
        return subscriptions.PLANS[name]

    # --- GET ------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith('/api/'):
                self.handle_api_get(parsed)
            else:
                self.serve_static(parsed.path)
        except HttpError as err:
            self.send_error_json(err.status, err.message)
        except Exception as err:
            traceback.print_exc()
            self.send_error_json(500, f'Внутренняя ошибка: {err}')

    def handle_api_get(self, parsed):
        route = parsed.path.rstrip('/')
        params = parse_qs(parsed.query)

        if route == '/api/config':
            self.send_json(config_payload(self.base_url()))
            return

        if route == '/api/subscription':
            login = self.require_login((params.get('channel') or params.get('login') or [''])[0])
            key = self.key_from(params)
            access = access_for(login, key)
            self.send_json({
                'ok': True,
                'channel': login,
                'subscription': public_subscription(login),
                'access': access,
                'license_key': subscriptions.license_key(login) if access['active'] else None,
            })
            return

        if route == '/api/stats':
            login = self.require_login((params.get('channel') or params.get('login') or [''])[0])
            key = self.key_from(params)
            access = access_for(login, key)
            if not access['active']:
                self.send_json({
                    'ok': False,
                    'error': 'Нужна активная подписка и лицензионный ключ этого канала',
                    'channel': login,
                    'subscription': public_subscription(login),
                    'access': access,
                    'console': render.build_report(login, render.empty_state(), POLL_INTERVAL_MS),
                }, 402)
                return
            report = channel_report(login)
            self.send_json({
                'ok': True,
                'channel': login,
                'subscription': public_subscription(login),
                'access': access,
                'counts': report['counts'],
                'state': report['state'],
                'error': report['error'],
                'console': report['console'],
                'fetched_at': report['fetched_at'],
            })
            return

        raise NotFound('Неизвестный метод API')

    # --- POST -----------------------------------------------------------
    def do_POST(self):
        route = urlparse(self.path).path.rstrip('/')
        try:
            if route == '/api/subscribe':
                self.handle_subscribe()
            elif route == '/api/payments/webhook':
                self.handle_webhook()
            elif route == '/api/admin/confirm':
                self.handle_admin_confirm()
            else:
                raise NotFound('Неизвестный метод API')
        except HttpError as err:
            self.send_error_json(err.status, err.message)
        except Exception as err:
            traceback.print_exc()
            self.send_error_json(500, f'Внутренняя ошибка: {err}')

    def handle_subscribe(self):
        allowed, retry_after = rate_limit(self.client_ip())
        if not allowed:
            self.send_json(
                {'ok': False, 'error': f'Слишком много попыток оплаты, попробуйте через {retry_after} сек'},
                429,
            )
            return

        payload = self.read_json()
        login = self.require_login(payload.get('channel') or payload.get('login'))
        plan = self.require_plan(payload.get('plan'))
        mode = payments.provider()

        if mode == 'yookassa':
            try:
                result = yookassa_checkout(login, plan['code'], self.base_url())
            except RuntimeError as err:
                raise HttpError(502, str(err))
        elif mode == 'manual':
            result = manual_checkout(login, plan['code'])
        else:
            result = demo_checkout(login, plan['code'])

        note = None
        if result.get('queued'):
            note = 'Место в очереди: %d.' % result['position']
            if mode == 'demo':
                note += ' Тестовый режим: счёт уже оплачен.'
            elif mode == 'manual':
                note += ' Оплатите вне сайта — доступ включит администратор.'

        self.send_json({
            'ok': True,
            'channel': login,
            'plan': plan['code'],
            'plan_title': plan['title'],
            'price_rub': plan['price_rub'],
            'payment': {
                'provider': mode,
                'queued': bool(result.get('queued')),
                'position': result.get('position', 0),
                'queue_size': result.get('size', 1),
                'payment_id': result.get('payment_id'),
                'confirmation_url': result.get('confirmation_url'),
            },
            'subscription': public_subscription(login),
            'access': access_for(login, subscriptions.license_key(login)),
            'license_key': subscriptions.license_key(login),
            'note': note,
        })

    def handle_webhook(self):
        raw = self.read_body()
        signature = self.headers.get('X-Payment-Signature') or self.headers.get('X-Signature')
        timestamp = self.headers.get('X-Payment-Timestamp')
        if not payments.verify_webhook(WEBHOOK_SECRET, raw, timestamp, signature):
            self.send_error_json(400, 'Неверная подпись уведомления')
            return
        if not payments.in_trusted_network(self.client_ip()):
            self.send_error_json(403, 'Уведомление пришло не от платёжного провайдера')
            return
        try:
            data = json.loads(raw.decode('utf-8') or '{}')
        except (UnicodeDecodeError, ValueError):
            raise BadRequest('Уведомление должно быть JSON')
        if not isinstance(data, dict):
            raise BadRequest('Уведомление должно быть JSON-объектом')

        event = str(data.get('event') or '')
        metadata = payments.find_metadata(data)
        payment_id = metadata.get('payment_id')
        login = metadata.get('login')
        plan_code = metadata.get('plan')
        if not payment_id and login:
            # уведомление только с логином и тарифом (ручная касса)
            payment_id = STORE.new_payment_id()
            STORE.mark_payment_pending(payment_id, None, {
                'login': login,
                'plan': plan_code,
            })

        if event and event != 'payment.succeeded':
            if payment_id:
                STORE.mark_payment_canceled(payment_id)
            self.send_json({'ok': True, 'status': 'ignored', 'event': event})
            return

        if not payment_id:
            raise BadRequest('В уведомлении нет payment_id')

        record = STORE.payment_status(payment_id) or {}
        login = login or record.get('login')
        plan_code = plan_code or record.get('plan')
        if not login:
            raise BadRequest('В уведомлении нет логина стримера')
        login = self.require_login(login)
        plan = self.require_plan(plan_code)

        STORE.activate(login, plan['code'], payment_id)
        self.send_json({
            'ok': True,
            'status': 'paid',
            'channel': login,
            'plan': plan['code'],
            'subscription': public_subscription(login),
            'license_key': subscriptions.license_key(login),
        })

    def handle_admin_confirm(self):
        if not ADMIN_TOKEN:
            raise NotFound('Ручное подтверждение оплаты отключено (не задан ADMIN_TOKEN)')
        token = (self.headers.get('X-Admin-Token') or '').strip()
        if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
            self.send_error_json(403, 'Неверный админ-токен')
            return

        payload = self.read_json()
        payment_id = (payload.get('payment_id') or '').strip()
        login = self.require_login(payload.get('channel') or payload.get('login'))
        record = STORE.payment_status(payment_id) or {}
        plan = self.require_plan(payload.get('plan') or record.get('plan'))
        if not payment_id:
            payment_id = STORE.new_payment_id()
            STORE.mark_payment_pending(payment_id, None, {'login': login, 'plan': plan['code']})

        STORE.activate(login, plan['code'], payment_id)
        self.send_json({
            'ok': True,
            'status': 'paid',
            'channel': login,
            'plan': plan['code'],
            'payment_id': payment_id,
            'subscription': public_subscription(login),
            'license_key': subscriptions.license_key(login),
        })

    # --- статика --------------------------------------------------------
    def serve_static(self, path):
        relative = path.lstrip('/') or 'index.html'
        if relative.endswith('/'):
            relative += 'index.html'
        candidate = os.path.normpath(os.path.join(PUBLIC_DIR, relative))
        if not candidate.startswith(PUBLIC_DIR) or not os.path.isfile(candidate):
            raise NotFound('Файл не найден')
        with open(candidate, 'rb') as f:
            body = f.read()
        extension = os.path.splitext(candidate)[1].lower()
        self.send_response(200)
        self.send_header('Content-Type', MIME_TYPES.get(extension, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


def config_payload(base_url):
    return {
        'ok': True,
        'poll_interval_ms': POLL_INTERVAL_MS,
        'cache_ttl_ms': CACHE_TTL_MS,
        'currency': 'RUB',
        'plans': list(subscriptions.PLANS.values()),
        'default_plan': subscriptions.DEFAULT_PLAN,
        'payment': payments.public_config(),
        'webhook_url': f'{base_url}/api/payments/webhook',
        'key_prefix': subscriptions.KEY_PREFIX,
    }


def main():
    if not os.path.isdir(PUBLIC_DIR):
        print(f'Не найден каталог сайта: {PUBLIC_DIR}')
        sys.exit(1)

    threading.Thread(target=expire_watcher, daemon=True).start()

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f'http://{HOST}:{PORT}/'
    print('=' * 60)
    print(' Twitch Viewers — веб-оболочка')
    print('=' * 60)
    print(f' Сайт:           {url}')
    print(f' Оплата:         {payments.public_config()["label"]}')
    print(f' Опрос Twitch:   каждые {round(POLL_INTERVAL_MS / 1000)} сек')
    print(' CLI-версия:     python src/index.py <канал>')
    print(' Остановка:      Ctrl+C')
    print('=' * 60)
    if os.environ.get('WEB_OPEN_BROWSER', '1') != '0':
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлено.')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
