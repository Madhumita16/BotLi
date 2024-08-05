import random
from collections import defaultdict
from datetime import datetime, timedelta

from api import API
from botli_dataclasses import Bot, Challenge_Request, Challenge_Response, Matchmaking_Type
from challenger import Challenger
from config import Config
from enums import Busy_Reason, Perf_Type, Variant
from opponents import NoOpponentException, Opponents


class Matchmaking:
    def __init__(self, api: API, config: Config, username: str) -> None:
        self.api = api
        self.config = config
        self.username = username
        self.next_update = datetime.now()
        self.timeout = max(config.matchmaking.timeout, 1)
        self.types = self._get_types()
        self.suspended_types: list[Matchmaking_Type] = []
        self.opponents = Opponents(config.matchmaking.delay, username)
        self.challenger = Challenger(api)

        self.game_start_time: datetime = datetime.now()
        self.online_bots: list[Bot] = []
        self.current_type: Matchmaking_Type | None = None

    async def create_challenge(self) -> Challenge_Response | None:
        if await self._call_update():
            return

        if not self.current_type:
            self.current_type, = random.choices(self.types, [type.weight for type in self.types])
            print(f'Matchmaking type: {self.current_type}')

        try:
            next_opponent = self.opponents.get_opponent(self.online_bots, self.current_type)
        except NoOpponentException:
            print(f'Suspending matchmaking type {self.current_type.name} because no suitable opponent is available.')
            self.suspended_types.append(self.current_type)
            self.types.remove(self.current_type)
            self.current_type = None
            if not self.types:
                print('No usable matchmaking type configured.')
                return Challenge_Response(is_misconfigured=True)

            return Challenge_Response(no_opponent=True)

        if next_opponent:
            opponent, color = next_opponent
        else:
            print(f'No opponent available for matchmaking type {self.current_type.name}.')
            self.current_type = None
            return Challenge_Response(no_opponent=True)

        if busy_reason := await self._get_busy_reason(opponent):
            if busy_reason == Busy_Reason.PLAYING:
                rating_diff = opponent.rating_diffs[self.current_type.perf_type]
                print(f'Skipping {opponent.username} ({rating_diff:+}) as {color.value} ...')
                self.opponents.skip_bot()
            elif busy_reason == Busy_Reason.OFFLINE:
                print(f'Removing {opponent.username} from online bots because it is offline ...')
                self.online_bots.remove(opponent)

            return

        rating_diff = opponent.rating_diffs[self.current_type.perf_type]
        print(f'Challenging {opponent.username} ({rating_diff:+}) as {color.value} to {self.current_type.name} ...')
        challenge_request = Challenge_Request(opponent.username, self.current_type.initial_time,
                                              self.current_type.increment, self.current_type.rated, color,
                                              self.current_type.variant, self.timeout)

        response = await self.challenger.create(challenge_request)
        if not response.success and not (response.has_reached_rate_limit or response.is_misconfigured):
            self.opponents.add_timeout(False, self.current_type.estimated_game_duration, self.current_type)

        return response

    def on_game_started(self) -> None:
        self.game_start_time = datetime.now()

    def on_game_finished(self, was_aborted: bool) -> None:
        assert self.current_type

        game_duration = datetime.now() - self.game_start_time
        if was_aborted:
            game_duration += self.current_type.estimated_game_duration

        self.opponents.add_timeout(not was_aborted, game_duration, self.current_type)
        self.current_type = None

    def _get_types(self) -> list[Matchmaking_Type]:
        matchmaking_types: list[Matchmaking_Type] = []
        for name, type_config in self.config.matchmaking.types.items():
            initial_time, increment = type_config.tc.split('+')
            initial_time = int(float(initial_time) * 60) if initial_time else 0
            increment = int(increment) if increment else 0
            rated = True if type_config.rated is None else type_config.rated
            variant = Variant.STANDARD if type_config.variant is None else Variant(type_config.variant)
            perf_type = self._variant_to_perf_type(variant, initial_time, increment)
            multiplier = 15 if type_config.multiplier is None else type_config.multiplier
            weight = 1.0 if type_config.weight is None else type_config.weight
            min_rating_diff = 0 if type_config.min_rating_diff is None else type_config.min_rating_diff
            max_rating_diff = 10_000 if type_config.max_rating_diff is None else type_config.max_rating_diff

            matchmaking_types.append(Matchmaking_Type(name, initial_time, increment, rated, variant,
                                                      perf_type, multiplier, weight, min_rating_diff, max_rating_diff))

        perf_type_count = len({matchmaking_type.perf_type for matchmaking_type in matchmaking_types})
        for matchmaking_type, type_config in zip(matchmaking_types, self.config.matchmaking.types.values()):
            if type_config.multiplier is None:
                matchmaking_type.multiplier *= perf_type_count

            if type_config.weight is None:
                matchmaking_type.weight /= matchmaking_type.estimated_game_duration.seconds

        return matchmaking_types

    async def _call_update(self) -> bool:
        if self.next_update <= datetime.now():
            print('Updating online bots and rankings ...')
            self.types.extend(self.suspended_types)
            self.suspended_types.clear()
            self.online_bots = await self._get_online_bots()
            return True

        return False

    async def _get_online_bots(self) -> list[Bot]:
        user_ratings = await self._get_user_ratings()

        online_bots: list[Bot] = []
        bot_counts: defaultdict[str, int] = defaultdict(int)
        async for bot in self.api.get_online_bots_stream():
            bot_counts['online'] += 1

            tos_violation = False
            if 'tosViolation' in bot:
                tos_violation = True
                bot_counts['with tosViolation'] += 1

            if bot['username'] == self.username:
                continue

            if 'disabled' in bot:
                bot_counts['disabled'] += 1
                continue

            if bot['id'] in self.config.blacklist:
                bot_counts['blacklisted'] += 1
                continue

            rating_diffs: dict[Perf_Type, int] = {}
            for perf_type in Perf_Type:
                bot_rating = bot['perfs'][perf_type.value]['rating'] if perf_type.value in bot['perfs'] else 1500
                rating_diffs[perf_type] = bot_rating - user_ratings[perf_type]

            online_bots.append(Bot(bot['username'], tos_violation, rating_diffs))

        for category, count in bot_counts.items():
            if count:
                print(f'{count:3} bots {category}')

        self.next_update = datetime.now() + timedelta(minutes=30.0)
        return online_bots

    async def _get_user_ratings(self) -> dict[Perf_Type, int]:
        user = await self.api.get_account()

        performances: dict[Perf_Type, int] = {}
        for perf_type in Perf_Type:
            if perf_type.value in user['perfs']:
                performances[perf_type] = user['perfs'][perf_type.value]['rating']
            else:
                performances[perf_type] = 2500

        return performances

    def _variant_to_perf_type(self, variant: Variant, initial_time: int, increment: int) -> Perf_Type:
        if variant != Variant.STANDARD:
            return Perf_Type(variant.value)

        estimated_game_duration = initial_time + increment * 40
        if estimated_game_duration < 179:
            return Perf_Type.BULLET

        if estimated_game_duration < 479:
            return Perf_Type.BLITZ

        if estimated_game_duration < 1499:
            return Perf_Type.RAPID

        return Perf_Type.CLASSICAL

    def _perf_type_to_variant(self, perf_type: Perf_Type) -> Variant:
        if perf_type in [Perf_Type.BULLET, Perf_Type.BLITZ, Perf_Type.RAPID, Perf_Type.CLASSICAL]:
            return Variant.STANDARD

        return Variant(perf_type.value)

    async def _get_busy_reason(self, bot: Bot) -> Busy_Reason | None:
        bot_status = await self.api.get_user_status(bot.username)
        if 'online' not in bot_status:
            return Busy_Reason.OFFLINE

        if 'playing' in bot_status:
            return Busy_Reason.PLAYING
