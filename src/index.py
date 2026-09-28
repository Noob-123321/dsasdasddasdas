import os
import sys
import time

import channel
import envfile
import render
from twitch_gql_client import TwitchGqlClient

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


envfile.load_dotenv()

POLL_INTERVAL_MS = int(os.environ.get('POLL_INTERVAL_MS', '15000'))


def print_usage_and_exit():
    print('Использование: python src/index.py <ссылка или имя канала Twitch>')
    print('Пример:        python src/index.py https://www.twitch.tv/asmongold')
    sys.exit(1)


def main():
    raw_input = sys.argv[1] if len(sys.argv) > 1 else None
    if not raw_input:
        print_usage_and_exit()

    try:
        channel_login = channel.extract_channel_login(raw_input)
    except ValueError as err:
        print(f'Ошибка: {err}')
        print_usage_and_exit()

    twitch = TwitchGqlClient()

    state = render.empty_state()

    def render_screen():
        clear_screen()
        for line in render.build_report(channel_login, state, POLL_INTERVAL_MS):
            print(line)

    def poll():
        try:
            stats = twitch.get_channel_stats(channel_login)
            state['is_live'] = stats['is_live']
            state['total_viewers'] = stats['viewer_count']
            state['stream_title'] = stats['title']
            state['chatters_count'] = stats['chatters_count']
            state['last_error'] = None
        except Exception as err:
            state['last_error'] = str(err)
        render_screen()

    render_screen()
    poll()
    try:
        while True:
            time.sleep(POLL_INTERVAL_MS / 1000)
            poll()
    except KeyboardInterrupt:
        print()


if __name__ == '__main__':
    main()