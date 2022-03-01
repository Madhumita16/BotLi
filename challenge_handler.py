import json
import multiprocessing
import queue
import sys
from multiprocessing.context import Process
from multiprocessing.managers import ValueProxy

from api import API
from enums import Decline_Reason
from game_api import Game_api


class Challenge_Handler:
    def __init__(
            self, config: dict, is_running: ValueProxy[bool],
            accept_challenges: ValueProxy[bool],
            game_count: ValueProxy[int]) -> None:
        self.config = config
        self.api = API(self.config['token'])
        self.is_running = is_running
        self.accept_challenges = accept_challenges
        self.manager = multiprocessing.Manager()
        self.count_concurrent_games = 0
        self.game_count = game_count

    def start(self) -> None:
        challenge_queue = self.manager.Queue()
        challenge_queue_process = multiprocessing.Process(
            target=self._watch_challenge_stream, args=(challenge_queue,))
        challenge_queue_process.start()

        username = self.api.get_account()['username']
        self.game_processes: dict[str, Process] = {}

        while self.is_running.value:
            try:
                event = challenge_queue.get(timeout=2)
            except queue.Empty:
                continue

            if event['type'] == 'challenge':
                challenger_name = event['challenge']['challenger']['name']

                if challenger_name == username:
                    continue

                challenge_id = event['challenge']['id']
                challenger_title = event['challenge']['challenger']['title'] if event['challenge']['challenger'][
                    'title'] else ''
                challenger_rating = event['challenge']['challenger']['rating']
                tc = event['challenge']['timeControl'].get('show')
                rated = event['challenge']['rated']
                variant = event['challenge']['variant']['name']
                print(
                    f'ID: {challenge_id}\tChallenger: {challenger_title} {challenger_name} ({challenger_rating})\tTC: {tc}\tRated: {rated}\tVariant: {variant}')

                decline_reason = self._get_decline_reason(event)
                if decline_reason:
                    self.api.decline_challenge(challenge_id, decline_reason)
                    continue

                if not self.api.accept_challenge(challenge_id):
                    print('Challenge could not be accepted!', file=sys.stderr)
                    continue

                print('Accepted challenge ...')
            elif event['type'] == 'gameStart':
                game_id = event['game']['id']

                if not self.accept_challenges.value:
                    continue

                self.game_count.value += 1
                game = Game_api(username, game_id, self.config)
                game_process = multiprocessing.Process(target=game.run_game)
                self.game_processes[game_id] = game_process
                game_process.start()
            elif event['type'] == 'gameFinish':
                game_id = event['game']['id']

                if game_id in self.game_processes:
                    self.game_processes[game_id].join()
                    del self.game_processes[game_id]
                    self.game_count.value -= 1
            elif event['type'] == 'challengeDeclined':
                continue
            elif event['type'] == 'challengeCanceled':
                continue
            else:
                print('Type not caught! Torsten do something:', file=sys.stderr)
                print(event)

        for process in self.game_processes.values():
            process.join()
            self.game_count.value -= 1

        challenge_queue_process.terminate()
        challenge_queue_process.join()

    def _watch_challenge_stream(self, challenge_queue: multiprocessing.Queue) -> None:
        event_stream = self.api.get_event_stream()

        for line in event_stream:
            if line:
                event = json.loads(line.decode('utf-8'))
                challenge_queue.put_nowait(event)

    def _get_decline_reason(self, event: dict) -> Decline_Reason | None:
        concurrency = self.config['challenge'].get('concurrency', 1)
        variants = self.config['challenge']['variants']
        time_controls = self.config['challenge']['time_controls']
        min_increment = self.config['challenge'].get('min_increment', 0)
        max_increment = self.config['challenge'].get('max_increment', 180)
        min_initial = self.config['challenge'].get('min_initial', 0)
        max_initial = self.config['challenge'].get('max_initial', 315360000)
        is_bot = event['challenge']['challenger']['title'] == 'BOT'
        modes = self.config['challenge']['bot_modes'] if is_bot else self.config['challenge']['human_modes']

        variant = event['challenge']['variant']['key']
        if variant not in variants:
            print(f'Variant "{variant}" is not allowed by config!')
            return Decline_Reason.VARIANT

        speed = event['challenge']['speed']
        increment = event['challenge']['timeControl']['increment']
        initial = event['challenge']['timeControl']['limit']
        if speed not in time_controls:
            print(f'Speed "{speed}" is not allowed by config!')
            return Decline_Reason.TIME_CONTROL
        elif increment < min_increment or increment > max_increment:
            print(f'Increment {increment} is not allowed by config!')
            return Decline_Reason.TIME_CONTROL
        elif initial < min_initial or initial > max_initial:
            print(f'Initial time {initial} is not allowed by config!')
            return Decline_Reason.TIME_CONTROL

        is_rated = event['challenge']['rated']
        is_casual = not is_rated
        if is_rated and 'rated' not in modes:
            print(f'Rated is not allowed by config!')
            return Decline_Reason.CASUAL
        elif is_casual and 'casual' not in modes:
            print(f'Casual is not allowed by config!')
            return Decline_Reason.RATED

        if not self.accept_challenges.value:
            print('We are currently not accepting any new challenges!')
            return Decline_Reason.LATER

        if concurrency <= self.game_count.value:
            print(f'Not more then {concurrency} concurrend game(s) allowed by config!')
            return Decline_Reason.LATER
