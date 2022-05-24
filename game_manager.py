from collections import deque
from threading import Event, Thread

from aliases import Challenge_ID, Game_ID
from api import API
from game import Game
from game_counter import Game_Counter
from matchmaking import Matchmaking
from pending_challenge import Pending_Challenge


class Game_Manager(Thread):
    def __init__(self, config: dict, api: API) -> None:
        Thread.__init__(self)
        self.config = config
        self.api = api
        self.is_running = True
        self.game_counter = Game_Counter(self.config['challenge'].get('concurrency', 1))
        self.games: dict[Game_ID, Game] = {}
        self.open_challenge_ids: deque[Challenge_ID] = deque()
        self.reserved_game_ids: list[Game_ID] = []
        self.finished_game_ids: deque[Game_ID] = deque()
        self.started_game_ids: deque[Game_ID] = deque()
        self.changed_event = Event()
        self.matchmaking = Matchmaking(self.config, self.api)
        self.is_matchmaking_allowed = False
        self.current_matchmaking_game_id: Game_ID | None = None

    def start(self):
        Thread.start(self)

    def stop(self):
        self.is_running = False
        self.changed_event.set()

    def run(self) -> None:
        while self.is_running:
            event_received = self.changed_event.wait(10.0)
            if not event_received:
                self._check_matchmaking()
                continue

            self.changed_event.clear()

            while self.started_game_ids:
                self._start_game(self.started_game_ids.popleft())

            while self.finished_game_ids:
                self._finish_game(self.finished_game_ids.popleft())

            while challenge_id := self._get_next_challenge():
                self._accept_challenge(challenge_id)

        for thread in self.games.values():
            thread.join()
            self.game_counter.decrement()

    def add_challenge(self, challenge_id: Challenge_ID) -> None:
        self.open_challenge_ids.append(challenge_id)
        self.changed_event.set()

    def remove_challenge(self, challenge_id: Challenge_ID) -> None:
        try:
            self.open_challenge_ids.remove(challenge_id)
            print(f'Challenge "{challenge_id}" has been canceled.')
            self.changed_event.set()
        except ValueError:
            pass

    def on_game_started(self, game_id: Game_ID) -> None:
        self.started_game_ids.append(game_id)
        if game_id == self.current_matchmaking_game_id:
            self.matchmaking.on_game_started()
        self.changed_event.set()

    def on_game_finished(self, game_id: Game_ID) -> None:
        self.finished_game_ids.append(game_id)
        if game_id == self.current_matchmaking_game_id:
            self.matchmaking.on_game_finished(self.games[game_id], self.is_running)
            self.current_matchmaking_game_id = None
        self.changed_event.set()

    def _start_game(self, game_id: Game_ID) -> None:
        try:
            # Remove reserved spot, if it exists:
            self.reserved_game_ids.remove(game_id)
        except ValueError:
            pass

        if not self.game_counter.increment():
            print(f'Max number of concurrent games reached. Aborting an already started game {game_id}.')
            self.api.abort_game(game_id)

        self.games[game_id] = Game(self.config, self.api, game_id)
        self.games[game_id].start()

    def _finish_game(self, game_id: Game_ID) -> None:
        self.games[game_id].join()
        del self.games[game_id]
        self.game_counter.decrement()

    def _get_next_challenge(self) -> Challenge_ID | None:
        if not self.open_challenge_ids:
            return

        if self.game_counter.is_max(len(self.reserved_game_ids)):
            return

        return self.open_challenge_ids.popleft()

    def _accept_challenge(self, challenge_id: Challenge_ID) -> None:
        if self.api.accept_challenge(challenge_id):
            # Reserve a spot for this game
            self.reserved_game_ids.append(challenge_id)
        else:
            print(f'Challenge "{challenge_id}" could not be accepted!')

    def _check_matchmaking(self) -> None:
        if not self.is_matchmaking_allowed:
            return

        if self.game_counter.is_max(len(self.reserved_game_ids)):
            return

        if self.current_matchmaking_game_id:
            # There is already a matchmaking game running
            return

        pending_challenge = Pending_Challenge()
        Thread(target=self.matchmaking.create_challenge, args=(pending_challenge,), daemon=True).start()

        challenge_id = pending_challenge.get_challenge_id()
        self.current_matchmaking_game_id = challenge_id

        success, has_reached_rate_limit = pending_challenge.get_final_state()

        if success:
            if challenge_id is not None:
                # Reserve a spot for this game
                self.reserved_game_ids.append(challenge_id)
            else:
                print('challenge_id was None despite success.')
        else:
            self.current_matchmaking_game_id = None
            if has_reached_rate_limit:
                print('Matchmaking stopped due to rate limiting.')
                self.is_matchmaking_allowed = False
