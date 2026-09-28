"""Демонстрационная касса.

По умолчанию включён режим `demo`: имитирует успешный платёж, чтобы сайт
можно было проверить локально (карта 4242 4242 4242 4242).

Если задать YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY, платёж создаётся через
API ЮKassa, а оплату подтверждает вебхук (HTTP-уведомление) с проверкой
IP-адреса отправителя. Деньги при этом реальные.

Если задать PAYMENT_PROVIDER=manual, оплату подтверждает админ:
POST /api/admin/confirm (заголовок X-Admin-Token: ADMIN_TOKEN).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request

YOOKASSA_API = 'https://api.yookassa.ru/v3/payments'

# Подсети, с которых ЮKassa присылает HTTP-уведомления
# (https://yookassa.ru/developers/using-api/webhooks).
YOOKASSA_NOTIFICATION_NETWORKS = (
    '185.71.76.0/27',
    '185.71.77.0/27',
    '77.75.153.0/25',
    '77.75.154.128/25',
    '77.75.156.11/32',
    '77.75.156.35/32',
    '2a02:5180::/32',
)


def provider(env=None):
    env = env or os.environ
    if env.get('YOOKASSA_SHOP_ID') and env.get('YOOKASSA_SECRET_KEY'):
        return 'yookassa'
    mode = (env.get('PAYMENT_PROVIDER') or 'demo').strip().lower()
    return mode if mode in ('demo', 'manual') else 'demo'


def public_config(env=None):
    env = env or os.environ
    name = provider(env)
    return {
        'provider': name,
        'label': 'ЮKassa' if name == 'yookassa' else ('Тестовый платёж' if name == 'demo' else 'Оплата вручную'),
        'instant': name in ('demo', 'yookassa'),
    }


def in_trusted_network(ip, networks=YOOKASSA_NOTIFICATION_NETWORKS):
    import ipaddress
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for network in networks:
        try:
            if address in ipaddress.ip_network(network, strict=False):
                return True
        except ValueError:
            continue
    return False


def build_yookassa_payment(payment_id, plan, store, return_url, public_id, env=None):
    """Создаёт платёж в ЮKassa через API Basic-аутентификации."""
    env = env or os.environ
    body = {
        'amount': {'value': f'{plan["price_rub"]}.00', 'currency': 'RUB'},
        'capture': True,
        'confirmation': {'type': 'redirect', 'return_url': return_url},
        'description': f'Подписка {plan["title"]} для канала #{public_id}',
        'metadata': {'payment_id': payment_id, 'login': public_id, 'plan': plan['code']},
    }
    credentials = f'{env["YOOKASSA_SHOP_ID"]}:{env["YOOKASSA_SECRET_KEY"]}'.encode('utf-8')
    request = urllib.request.Request(
        YOOKASSA_API,
        data=json.dumps(body).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': 'Basic ' + base64.b64encode(credentials).decode('ascii'),
            'Idempotence-Key': secrets.token_hex(16),
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as err:
        text = err.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'ЮKassa ошибка (HTTP {err.code}): {text}') from err
    except urllib.error.URLError as err:
        raise RuntimeError(f'ЮKassa ошибка: {err.reason}') from err

    confirmation = payload.get('confirmation') or {}
    url = confirmation.get('confirmation_url')
    if not url:
        raise RuntimeError('ЮKassa не вернула confirmation_url')
    store.mark_payment_pending(payment_id, payload.get('id'), {
        'login': public_id,
        'plan': plan['code'],
        'amount_rub': plan['price_rub'],
        'provider': 'yookassa',
    })
    return url


def find_metadata(data):
    """Достаёт метаданные (payment_id/login/plan) из уведомления ЮKassa."""
    metadata = data.get('metadata')
    if isinstance(metadata, dict):
        return metadata
    for key in ('object', 'payment'):
        nested = data.get(key)
        if isinstance(nested, dict):
            metadata = nested.get('metadata')
            if isinstance(metadata, dict):
                return metadata
    return {}


def verify_webhook(secret, raw_body, timestamp, signature, tolerance_seconds=300):
    """Проверка подписи вебхука (HMAC-SHA256), если задан PAYMENT_WEBHOOK_SECRET."""
    if not secret:
        return True
    if not signature:
        return False
    try:
        moment = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - moment) > tolerance_seconds:
        return False
    expected = hmac.new(secret.encode('utf-8'), f'{timestamp}.'.encode('utf-8') + raw_body, hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), str(signature).strip().lower())