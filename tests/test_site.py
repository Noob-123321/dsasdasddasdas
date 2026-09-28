"""Проверка веб-оболочки: рендер, подписки, касса и HTTP API.

Запуск (из корня проекта):
    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import channel
import payments
import render
import server
import subscriptions


class FakeTwitch:
    """Заглушка Twitch GraphQL — тесты не зависят от сети."""

    def __init__(self, stats=None, error=None):
        self.stats = stats or {
            'is_live': True,
            'viewer_count': 1523,
            'title': 'Chill stream',
            'chatters_count': 287,
        }
        self.error = error
        self.calls = 0

    def get_channel_stats(self, login):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return dict(self.stats)


class RenderTests(unittest.TestCase):
    def test_report_matches_cli_layout(self):
        state = {
            'is_live': True,
            'total_viewers': 1523,
            'chatters_count': 287,
            'stream_title': 'Chill stream',
            'last_error': None,
        }
        lines = render.build_report('asmongold', state, 15000)

        self.assertEqual(lines[0], '=' * 60)
        self.assertEqual(lines[1], ' Twitch канал: #asmongold')
        self.assertIn(' Статус: 🟢 в эфире', lines)
        self.assertIn(' Название: Chill stream', lines)
        self.assertIn(' Всего зрителей:            1523', lines)
        self.assertIn(' Авторизованных (в чате):   287', lines)
        self.assertIn(' Гостей (примерно):         1236', lines)
        self.assertEqual(lines[-1], ' Обновление каждые 15 сек. Ctrl+C для выхода.')

    def test_report_offline_and_error(self):
        state = dict(render.empty_state(), last_error='Twitch GraphQL ошибка: timeout')
        lines = render.build_report('nobody', state, 5000)
        self.assertIn(' Статус: 🔴 оффлайн (стрим не идёт)', lines)
        self.assertIn(' Всего зрителей:            н/д (стрим оффлайн)', lines)
        self.assertIn(' Авторизованных (в чате):   н/д', lines)
        self.assertTrue(any('⚠ Последняя ошибка' in line for line in lines))

    def test_counts_math(self):
        counts = render.counts({
            'total_viewers': 100,
            'chatters_count': 250,
            'stream_title': None,
            'is_live': True,
            'last_error': None,
        })
        self.assertEqual(counts['authorized'], 100)
        self.assertEqual(counts['guests'], 0)
        empty = render.counts(render.empty_state())
        self.assertIsNone(empty['total_viewers'])
        self.assertIsNone(empty['guests'])


class ChannelTests(unittest.TestCase):
    def test_extract_login_variants(self):
        self.assertEqual(channel.extract_channel_login('https://www.twitch.tv/Asmongold'), 'asmongold')
        self.assertEqual(channel.extract_channel_login('twitch.tv/xqc?sr=a'), 'xqc')
        self.assertEqual(channel.extract_channel_login('@xqc'), 'xqc')
        with self.assertRaises(ValueError):
            channel.extract_channel_login('плохой логин!')


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix='.json')
        os.close(handle)
        os.remove(self.path)
        self.store = subscriptions.SubscriptionStore(self.path)

    def tearDown(self):
        if os.path.isfile(self.path):
            os.remove(self.path)

    def test_activation_license_and_expiry(self):
        self.assertFalse(self.store.is_active('asmongold'))
        subscription = self.store.activate('asmongold', 'pro', 'pay_1')
        self.assertEqual(subscription['status'], 'active')
        self.assertEqual(subscription['days'], 30)
        self.assertTrue(self.store.is_active('asmongold'))

        key = subscriptions.license_key('asmongold')
        self.assertEqual(key, 'TVS-ASMONGOLD')
        self.assertTrue(subscriptions.key_matches('asmongold', key.lower()))
        self.assertFalse(subscriptions.key_matches('asmongold', 'TVS-OTHER'))
        self.assertGreater(subscriptions.days_left(subscription), 20)

        import datetime
        far_future = subscriptions._now() + datetime.timedelta(days=40)
        self.assertEqual(self.store.deactivate_expired(far_future), ['asmongold'])
        self.assertEqual(self.store.get('asmongold')['status'], 'expired')

    def test_activation_extends_active_subscription(self):
        self.store.activate('streamer', 'start')
        first = self.store.get('streamer')['expires_at']
        second = self.store.activate('streamer', 'start')['expires_at']
        self.assertTrue(second > first)

    def test_bad_login_rejected(self):
        with self.assertRaises(ValueError):
            self.store.activate('плохой логин', 'pro')


class PaymentsTests(unittest.TestCase):
    def test_provider_selection(self):
        self.assertEqual(payments.provider({'PAYMENT_PROVIDER': 'demo'}), 'demo')
        self.assertEqual(payments.provider({'PAYMENT_PROVIDER': 'manual'}), 'manual')
        self.assertEqual(payments.provider({'PAYMENT_PROVIDER': 'нечто'}), 'demo')
        self.assertEqual(
            payments.provider({'YOOKASSA_SHOP_ID': '1', 'YOOKASSA_SECRET_KEY': 'x'}),
            'yookassa',
        )

    def test_webhook_signature(self):
        body = b'{"event":"payment.succeeded"}'
        timestamp = str(int(payments.time.time()))
        expected = payments.hmac.new(
            b'secret', f'{timestamp}.'.encode('utf-8') + body, payments.hashlib.sha256
        ).hexdigest()
        self.assertTrue(payments.verify_webhook('secret', body, timestamp, expected))
        self.assertFalse(payments.verify_webhook('secret', body, timestamp, 'deadbeef'))
        self.assertFalse(payments.verify_webhook('secret', body, '1', expected))
        self.assertTrue(payments.verify_webhook('', body, None, None))

    def test_trusted_networks(self):
        self.assertTrue(payments.in_trusted_network('185.71.76.5'))
        self.assertFalse(payments.in_trusted_network('127.0.0.1'))
        self.assertFalse(payments.in_trusted_network('not-an-ip'))

    def test_metadata_lookup(self):
        self.assertEqual(
            payments.find_metadata({'object': {'metadata': {'login': 'xqc'}}}),
            {'login': 'xqc'},
        )
        self.assertEqual(payments.find_metadata({}), {})


class ApiTests(unittest.TestCase):
    """Проверка HTTP API на реальном сервере (порт назначает ОС)."""

    def setUp(self):
        handle, self.store_path = tempfile.mkstemp(suffix='.json')
        os.close(handle)
        os.remove(self.store_path)

        self.saved_store, self.saved_twitch = server.STORE, server.TWITCH
        server.STORE = subscriptions.SubscriptionStore(self.store_path)
        server.TWITCH = FakeTwitch()
        server._cache.clear()

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        server.STORE, server.TWITCH = self.saved_store, self.saved_twitch
        server._cache.clear()
        if os.path.isfile(self.store_path):
            os.remove(self.store_path)

    def url(self, path):
        return f'http://127.0.0.1:{self.port}{path}'

    def get(self, path, headers=None):
        request = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as err:
            return err.code, err.read(), err.headers

    def post(self, path, payload, headers=None):
        body = json.dumps(payload).encode('utf-8')
        merged = {'Content-Type': 'application/json'}
        merged.update(headers or {})
        request = urllib.request.Request(self.url(path), data=body, method='POST', headers=merged)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode('utf-8'))

    def test_static_pages_are_served(self):
        status, body, headers = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers.get('Content-Type'))
        self.assertIn('Twitch Viewers', body.decode('utf-8'))

        for asset in ('/styles.css', '/app.js', '/favicon.svg'):
            status, body, _ = self.get(asset)
            self.assertEqual(status, 200, asset)
            self.assertTrue(body)

    def test_config_and_unknown_route(self):
        status, body, _ = self.get('/api/config')
        self.assertEqual(status, 200)
        config = json.loads(body.decode('utf-8'))
        self.assertEqual([plan['code'] for plan in config['plans']], ['start', 'pro', 'stream'])
        self.assertEqual(config['default_plan'], 'pro')
        self.assertTrue(config['webhook_url'].endswith('/api/payments/webhook'))

        status, _, _ = self.get('/api/unknown')
        self.assertEqual(status, 404)

    def test_stats_requires_subscription(self):
        status, body, _ = self.get('/api/stats?channel=asmongold')
        self.assertEqual(status, 402)
        payload = json.loads(body.decode('utf-8'))
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['access']['status'], 'none')
        self.assertTrue(any('Twitch канал: #asmongold' in line for line in payload['console']))
        self.assertEqual(server.TWITCH.calls, 0, 'без подписки не должно быть запросов к Twitch')

    def test_buy_then_read_stats(self):
        status, payload = self.post('/api/subscribe', {'channel': 'https://twitch.tv/Asmongold', 'plan': 'pro'})
        self.assertEqual(status, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['channel'], 'asmongold')
        self.assertEqual(payload['license_key'], 'TVS-ASMONGOLD')
        self.assertTrue(payload['access']['active'])
        self.assertEqual(payload['subscription']['plan_title'], 'Pro')
        self.assertEqual(payload['payment']['provider'], 'demo')

        status, body, _ = self.get('/api/stats?channel=asmongold&key=TVS-ASMONGOLD')
        self.assertEqual(status, 200)
        stats = json.loads(body.decode('utf-8'))
        self.assertTrue(stats['ok'])
        self.assertEqual(stats['counts']['total_viewers'], 1523)
        self.assertEqual(stats['counts']['authorized'], 287)
        self.assertEqual(stats['counts']['guests'], 1236)
        self.assertTrue(stats['state']['is_live'])

        joined = '\n'.join(stats['console'])
        self.assertIn(' Twitch канал: #asmongold', joined)
        self.assertIn(' Гостей (примерно):         1236', joined)
        self.assertEqual(server.TWITCH.calls, 1)
        self.assertEqual(len(server._cache), 1)

    def test_subscription_endpoint_reports_active_and_key(self):
        self.post('/api/subscribe', {'channel': 'xqc', 'plan': 'start'})
        status, body, _ = self.get('/api/subscription?channel=xqc&key=TVS-XQC')
        self.assertEqual(status, 200)
        payload = json.loads(body.decode('utf-8'))
        self.assertTrue(payload['access']['active'])
        self.assertEqual(payload['license_key'], 'TVS-XQC')
        self.assertEqual(payload['subscription']['plan'], 'start')

    def test_wrong_key_is_locked(self):
        self.post('/api/subscribe', {'channel': 'xqc', 'plan': 'start'})
        status, body, _ = self.get('/api/stats?channel=xqc&key=TVS-NEVER')
        self.assertEqual(status, 402)
        payload = json.loads(body.decode('utf-8'))
        self.assertEqual(payload['access']['status'], 'locked')

    def test_subscribe_validation(self):
        status, payload = self.post('/api/subscribe', {'channel': '!!!', 'plan': 'pro'})
        self.assertEqual(status, 400)
        self.assertIn('Не удалось распознать', payload['error'])

        status, payload = self.post('/api/subscribe', {'channel': 'asmongold', 'plan': 'free'})
        self.assertEqual(status, 400)
        self.assertIn('Неизвестный тариф', payload['error'])

    def test_webhook_requires_trusted_sender(self):
        self.post('/api/subscribe', {'channel': 'asmongold', 'plan': 'pro'})
        status, payload = self.post('/api/payments/webhook', {'event': 'payment.succeeded'})
        self.assertEqual(status, 403)
        self.assertIn('не от платёжного провайдера', payload['error'])

    def test_admin_confirm_disabled_without_token(self):
        status, payload = self.post('/api/admin/confirm', {'channel': 'asmongold', 'plan': 'pro'})
        self.assertEqual(status, 404)
        self.assertIn('отключено', payload['error'])

    def test_twitch_error_is_reported_in_console(self):
        server.TWITCH = FakeTwitch(error='Twitch GraphQL ошибка (HTTP 500)')
        server._cache.clear()
        self.post('/api/subscribe', {'channel': 'asmongold', 'plan': 'pro'})
        status, body, _ = self.get('/api/stats?channel=asmongold&key=TVS-ASMONGOLD')
        self.assertEqual(status, 200)
        stats = json.loads(body.decode('utf-8'))
        self.assertIn('HTTP 500', stats['error'])
        self.assertTrue(any('⚠ Последняя ошибка' in line for line in stats['console']))


class DemoQueueTests(unittest.TestCase):
    def setUp(self):
        handle, self.store_path = tempfile.mkstemp(suffix='.json')
        os.close(handle)
        os.remove(self.store_path)
        self.saved_store = server.STORE
        server.STORE = subscriptions.SubscriptionStore(self.store_path)
        server._demo_queue.clear()

    def tearDown(self):
        server.STORE = self.saved_store
        server._demo_queue.clear()
        if os.path.isfile(self.store_path):
            os.remove(self.store_path)

    def test_queue_returns_position(self):
        # в очереди уже стоит другой тариф по этому же каналу
        server._demo_queue['asmongold'] = ['start']
        result = server.demo_checkout('asmongold', 'pro')
        self.assertTrue(result['queued'])
        self.assertEqual(result['position'], 1)
        self.assertFalse(server.STORE.is_active('asmongold'))

        server._demo_queue.clear()
        result = server.demo_checkout('asmongold', 'pro')
        self.assertFalse(result['queued'])
        self.assertTrue(server.STORE.is_active('asmongold'))


if __name__ == '__main__':
    unittest.main(verbosity=2)