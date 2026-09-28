import json
import urllib.error
import urllib.request

GQL_URL = 'https://gql.twitch.tv/gql'

# Client-ID, который использует расширение viewermetrics. Публичный, не секрет;
# поддерживает и обычные запросы, и персистентный CommunityTab.
TWITCH_CLIENT_ID = 'kd1unb4b3q4t58fwlpcbzcbnm76a8fp'

# Персистентный запрос CommunityTab отдаёт список участников чата канала
# (broadcasters/moderators/vips/viewers/chatbots + общий count) АНОНИМНО,
# без OAuth и без integrity-токена — именно так это делают браузерные
# расширения ("Authenticated Viewers").
COMMUNITY_TAB_HASH = '92168b4434c8f4d32df14510052131c3544b929723d5f8b69bb96c96207e483e'

_STREAM_QUERY = (
    'query StreamInfo($login:String!){user(login:$login){stream{type title viewersCount}}}'
)


class TwitchGqlClient:
    """Анонимный клиент Twitch GraphQL API.

    Одним batched-запросом получает:
      - общее число зрителей и название стрима (user.stream.viewersCount);
      - количество авторизованных в чате (user.channel.chatters.count).
    Ни регистрация приложения, ни OAuth-токен не нужны.
    """

    def _post(self, payload):
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            GQL_URL,
            data=data,
            method='POST',
            headers={
                'Client-Id': TWITCH_CLIENT_ID,
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            text = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'Twitch GraphQL ошибка (HTTP {e.code}): {text}') from e
        except urllib.error.URLError as e:
            raise RuntimeError(f'Twitch GraphQL ошибка: {e.reason}') from e

    def get_channel_stats(self, login: str):
        """Возвращает dict: is_live, viewer_count, title, chatters_count."""
        payload = [
            {
                'operationName': 'StreamInfo',
                'variables': {'login': login},
                'query': _STREAM_QUERY,
            },
            {
                'operationName': 'CommunityTab',
                'variables': {'login': login},
                'extensions': {
                    'persistedQuery': {
                        'version': 1,
                        'sha256Hash': COMMUNITY_TAB_HASH,
                    }
                },
            },
        ]

        response = self._post(payload)

        stream = self._extract(response, 0, ('user', 'stream'))
        chatters = self._extract(response, 1, ('user', 'channel', 'chatters'))

        is_live = bool(stream) and stream.get('type') == 'live'
        viewer_count = stream.get('viewersCount') if is_live else None
        title = stream.get('title') if is_live else None

        chatters_count = None
        if chatters:
            chatters_count = chatters.get('count')

        return {
            'is_live': is_live,
            'viewer_count': viewer_count,
            'title': title,
            'chatters_count': chatters_count,
        }

    @staticmethod
    def _extract(response, index, path):
        if not isinstance(response, list) or index >= len(response):
            return None
        item = response[index]
        if not isinstance(item, dict):
            return None
        if item.get('errors'):
            message = '; '.join(
                err.get('message', '?') for err in item['errors']
            )
            raise RuntimeError(f'Twitch GraphQL ошибка ({path[-1]}): {message}')
        data = item.get('data') or {}
        for key in path:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
        return data
