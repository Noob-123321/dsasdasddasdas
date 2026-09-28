"""Подписки: тарифы, хранилище оплаченных подписок и проверка доступа.

Хранилище — простой JSON-файл (без внешних БД), ключ — логин стримера
в нижнем регистре. Демо-касса помечает подписку оплаченной по вебхуку
платёжного провайдера (см. src/payments.py).
"""
import datetime
import hmac
import json
import os
import re
import secrets
import threading

import channel

DEFAULT_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'subscriptions.json')

KEY_PREFIX = 'TVS'

# Планы: код -> (название, дней, цена в рублях)
PLANS = {
    'start': {'code': 'start', 'title': 'Start', 'days': 7, 'price_rub': 149},
    'pro': {'code': 'pro', 'title': 'Pro', 'days': 30, 'price_rub': 499},
    'stream': {'code': 'stream', 'title': 'Stream', 'days': 90, 'price_rub': 1290},
}
DEFAULT_PLAN = 'pro'


def plan_or_default(code):
    if not code:
        return PLANS[DEFAULT_PLAN]
    return PLANS.get(str(code).strip().lower()) or PLANS[DEFAULT_PLAN]


class SubscriptionStore:
    """JSON-хранилище подписок с блокировкой для многопоточного сервера."""

    def __init__(self, path=None):
        self.path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()

    # --- низкоуровневый ввод/вывод -------------------------------------
    def _read(self):
        if not os.path.isfile(self.path):
            return {'subscriptions': {}, 'payments': {}}
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {'subscriptions': {}, 'payments': {}}
        if not isinstance(data, dict):
            return {'subscriptions': {}, 'payments': {}}
        data.setdefault('subscriptions', {})
        data.setdefault('payments', {})
        return data

    def _write(self, data):
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        tmp = f'{self.path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # --- публичное API --------------------------------------------------
    def get(self, login):
        key = _key(login)
        with self._lock:
            return self._read()['subscriptions'].get(key)

    def is_active(self, login):
        subscription = self.get(login)
        return bool(subscription) and subscription['status'] == 'active'

    def activate(self, login, plan, payment_id=None, now=None):
        """Помечает подписку оплаченной и продлевает её на срок тарифа."""
        key = _key(login)
        moment = now or _now()
        with self._lock:
            data = self._read()
            current = data['subscriptions'].get(key)
            base = moment
            if current and current.get('status') == 'active':
                try:
                    expires = _parse(current.get('expires_at'))
                except ValueError:
                    expires = None
                if expires and expires > moment:
                    base = expires
            subscription = {
                'login': key,
                'plan': plan,
                'plan_title': PLANS[plan]['title'],
                'status': 'active',
                'price_rub': PLANS[plan]['price_rub'],
                'started_at': _iso(base),
                'expires_at': _iso(base + datetime.timedelta(days=PLANS[plan]['days'])),
                'days': PLANS[plan]['days'],
                'payment_id': payment_id,
                'updated_at': _iso(moment),
            }
            data['subscriptions'][key] = subscription
            if payment_id:
                payments = data['payments']
                payments[payment_id] = dict(payments.get(payment_id, {}), **{
                    'login': key,
                    'plan': plan,
                    'status': 'paid',
                    'amount_rub': PLANS[plan]['price_rub'],
                    'paid_at': _iso(moment),
                })
            self._write(data)
            return subscription

    def payment_status(self, payment_id):
        if not payment_id:
            return None
        with self._lock:
            return self._read()['payments'].get(payment_id)

    def mark_payment_pending(self, payment_id, provider_payment_id=None, meta=None):
        """Платёж создан у провайдера, но ещё не оплачен."""
        with self._lock:
            data = self._read()
            payments = data['payments']
            record = dict(payments.get(payment_id, {}))
            record.update({
                'status': 'pending',
                'provider_payment_id': provider_payment_id,
                'created_at': record.get('created_at') or _iso(_now()),
            })
            record.update(meta or {})
            payments[payment_id] = record
            self._write(data)
            return record

    def mark_payment_canceled(self, payment_id):
        with self._lock:
            data = self._read()
            record = data['payments'].get(payment_id)
            if not record:
                return None
            record['status'] = 'canceled'
            record['updated_at'] = _iso(_now())
            self._write(data)
            return record

    def new_payment_id(self):
        return f'pay_{secrets.token_hex(8)}'

    def deactivate_expired(self, now=None):
        """Переводит истёкшие подписки в статус expired. Возвращает их логины."""
        moment = now or _now()
        expired = []
        with self._lock:
            data = self._read()
            changed = False
            for key, sub in data['subscriptions'].items():
                if sub.get('status') != 'active':
                    continue
                try:
                    expires = _parse(sub.get('expires_at'))
                except (ValueError, TypeError):
                    continue
                if expires <= moment:
                    sub['status'] = 'expired'
                    sub['updated_at'] = _iso(moment)
                    expired.append(key)
                    changed = True
            if changed:
                self._write(data)
        return expired


def license_key(login):
    """Лицензионный ключ канала (детерминированный, формируется из логина)."""
    return f'{KEY_PREFIX}-{_key(login).upper()}'


def key_matches(login, key):
    if not key or not isinstance(key, str):
        return False
    return hmac.compare_digest(key.strip().upper(), license_key(login))


def _key(login):
    if not login or not isinstance(login, str):
        raise ValueError('Не передан логин стримера')
    key = login.strip().lstrip('#').lower()
    if not channel.is_valid_login(key):
        raise ValueError(f'Неверный логин стримера: "{login}"')
    return key


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(moment):
    return moment.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse(value):
    if not value:
        raise ValueError('пустая дата')
    text = value.strip().replace('Z', '+00:00')
    match = re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', text)
    parsed = datetime.datetime.fromisoformat(text if match else f'{text}T00:00:00+00:00')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def days_left(subscription, now=None):
    """Сколько целых дней осталось (0, если уже истекла)."""
    if not subscription:
        return 0
    try:
        expires = _parse(subscription.get('expires_at'))
    except (ValueError, TypeError):
        return 0
    delta = expires - (now or _now())
    return max(delta.days, 0) if delta.total_seconds() > 0 else 0