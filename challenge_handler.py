import json
import queue
import sys
from collections import deque
from queue import Queue
from threading import Thread

from api import API
from enums import Decline_Reason
from game_api import Game_api
from game_counter import Game_Counter


class Challenge_Handler(Thread):
    def __init__(self, config: dict, api: API, game_count: Game_Counter) -> None:
        Thread.__init__(self)
        self.config = config
        self.api = api
        self.is_running = True
        self.game_count = game_count
        self.challenge_queue = Queue()
        self.open_challenge_ids: deque[str] = deque()
        self.outgoing_challenge_ids: list[str] = []

    def start(self):
        Thread.start(self)

    def stop(self):
        self.is_running = False

    def run(self) -> None:
        challenge_queue_thread = Thread(target=self._watch_challenge_stream, daemon=True)
        challenge_queue_thread.start()

        username = self.api.user['username']
        self.game_threads: dict[str, Thread] = {}

        while self.is_running:
            self.check_challenges()

            try:
                event = self.challenge_queue.get(timeout=2)
            except queue.Empty:
                continue

            if event['type'] == 'challenge':
                challenger_name = event['challenge']['challenger']['name']
                challenge_id = event['challenge']['id']

                if challenger_name == username:
                    self.outgoing_challenge_ids.append(challenge_id)
                    continue

                challenger_title = event['challenge']['challenger']['title']
                challenger_title = challenger_title if challenger_title else ''
                challenger_rating = event['challenge']['challenger']['rating']
                tc = event['challenge']['timeControl'].get('show')
                rated = event['challenge']['rated']
                variant = event['challenge']['variant']['name']
                print(
                    f'ID: {challenge_id}\tChallenger: {challenger_title} {challenger_name} ({challenger_rating})\tTC: {tc}\tRated: {rated}\tVariant: {variant}')

                if decline_reason := self._get_decline_reason(event):
                    self.api.decline_challenge(challenge_id, decline_reason)
                    continue

                self.open_challenge_ids.append(challenge_id)
                print(f'Challenge "{challenge_id}" added to queue.')
            elif event['type'] == 'gameStart':
                game_id = event['game']['id']

                if game_id in self.outgoing_challenge_ids:
                    self.outgoing_challenge_ids.remove(game_id)
                    continue

                if not self.game_count.increment():
                    print(f'Max number of concurrent games reached. Aborting a already started game "{game_id}".')
                    self.api.abort_game(game_id)
                    continue

                game = Game_api(self.config, self.api, game_id)
                game_thread = Thread(target=game.run_game)
                self.game_threads[game_id] = game_thread
                game_thread.start()
            elif event['type'] == 'gameFinish':
                game_id = event['game']['id']

                if game_id in self.game_threads:
                    self.game_threads[game_id].join()
                    del self.game_threads[game_id]
                    self.game_count.decrement()
            elif event['type'] == 'challengeDeclined':
                continue
            elif event['type'] == 'challengeCanceled':
                challenge_id = event['challenge']['id']
                try:
                    self.open_challenge_ids.remove(challenge_id)
                    print(f'Challenge "{challenge_id}" has been canceled.')
                except ValueError:
                    pass
            else:
                print('Event type not caught:', file=sys.stderr)
                print(event)

        for challenge_id in self.open_challenge_ids:
            self.api.decline_challenge(challenge_id, Decline_Reason.GENERIC)

        for thread in self.game_threads.values():
            thread.join()
            self.game_count.decrement()

    def _watch_challenge_stream(self) -> None:
        while True:
            try:
                event_stream = self.api.get_event_stream()
                for line in event_stream:
                    if line:
                        event = json.loads(line.decode('utf-8'))
                        self.challenge_queue.put_nowait(event)
            except Exception as e:
                print(e)

    def _get_decline_reason(self, event: dict) -> Decline_Reason | None:
        variants = self.config['challenge']['variants']
        time_controls = self.config['challenge']['time_controls']
        bullet_with_increment_only = self.config['challenge'].get('bullet_with_increment_only', False)
        min_increment = self.config['challenge'].get('min_increment', 0)
        max_increment = self.config['challenge'].get('max_increment', 180)
        min_initial = self.config['challenge'].get('min_initial', 0)
        max_initial = self.config['challenge'].get('max_initial', 315360000)
        is_bot = event['challenge']['challenger']['title'] == 'BOT'
        modes = self.config['challenge']['bot_modes'] if is_bot else self.config['challenge']['human_modes']

        if modes is None:
            if is_bot:
                print('Bots are not allowed according to config.')
                return Decline_Reason.NO_BOT
            else:
                print('Only bots are allowed according to config.')
                return Decline_Reason.ONLY_BOT

        variant = event['challenge']['variant']['key']
        if variant not in variants:
            print(f'Variant "{variant}" is not allowed according to config.')
            return Decline_Reason.VARIANT

        speed = event['challenge']['speed']
        increment = event['challenge']['timeControl'].get('increment')
        initial = event['challenge']['timeControl'].get('limit')
        if speed not in time_controls:
            print(f'Time control "{speed}" is not allowed according to config.')
            return Decline_Reason.TIME_CONTROL
        elif increment < min_increment:
            print(f'Increment {increment} is too short according to config.')
            return Decline_Reason.TOO_FAST
        elif increment > max_increment:
            print(f'Increment {increment} is too long according to config.')
            return Decline_Reason.TOO_SLOW
        elif initial < min_initial:
            print(f'Initial time {initial} is too short according to config.')
            return Decline_Reason.TOO_FAST
        elif initial > max_initial:
            print(f'Initial time {initial} is too long according to config.')
            return Decline_Reason.TOO_SLOW
        elif speed == 'bullet' and increment == 0 and bullet_with_increment_only:
            print('Bullet is only allowed with increment according to config.')
            return Decline_Reason.TOO_FAST

        is_rated = event['challenge']['rated']
        is_casual = not is_rated
        if is_rated and 'rated' not in modes:
            print(f'Rated is not allowed according to config.')
            return Decline_Reason.CASUAL
        elif is_casual and 'casual' not in modes:
            print(f'Casual is not allowed according to config.')
            return Decline_Reason.RATED

    def check_challenges(self) -> None:
        if not self.open_challenge_ids:
            return

        if self.game_count.is_max():
            return

        challenge_id = self.open_challenge_ids.popleft()

        if not self.api.accept_challenge(challenge_id):
            print(f'Challenge "{challenge_id}" could not be accepted!')
