import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
from tenacity import after_log, retry, retry_if_exception_type, wait_fixed

from botli_dataclasses import API_Challenge_Reponse, Challenge_Request
from config import Config
from enums import Decline_Reason, Variant

logger = logging.getLogger(__name__)
BASIC_RETRY_CONDITIONS = {'retry': retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
                          'wait': wait_fixed(5.0),
                          'after': after_log(logger, logging.DEBUG)}
JSON_RETRY_CONDITIONS = {'retry': retry_if_exception_type((aiohttp.ClientError, json.JSONDecodeError, TimeoutError)),
                         'wait': wait_fixed(5.0),
                         'after': after_log(logger, logging.DEBUG)}
GAME_STREAM_RETRY_CONDITIONS = {'retry': retry_if_exception_type((aiohttp.ClientError,
                                                                  json.JSONDecodeError,
                                                                  TimeoutError)),
                                'wait': wait_fixed(1.0),
                                'after': after_log(logger, logging.DEBUG)}
MOVE_RETRY_CONDITIONS = {'retry': retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
                         'wait': wait_fixed(1.0),
                         'after': after_log(logger, logging.DEBUG)}


class API:
    def __init__(self, config: Config) -> None:
        self.lichess_session = aiohttp.ClientSession(config.url, headers={'Authorization': f'Bearer {config.token}',
                                                                          'User-Agent': f'BotLi/{config.version}'},
                                                     timeout=aiohttp.ClientTimeout(total=5.0))
        self.external_session = aiohttp.ClientSession(headers={'User-Agent': f'BotLi/{config.version}'})

    def append_user_agent(self, username: str) -> None:
        self.lichess_session.headers['User-Agent'] += f' user:{username}'
        self.external_session.headers['User-Agent'] += f' user:{username}'

    async def close(self) -> None:
        await self.lichess_session.close()
        await self.external_session.close()

    @retry(**BASIC_RETRY_CONDITIONS)
    async def abort_game(self, game_id: str) -> bool:
        try:
            async with self.lichess_session.post(f'/api/bot/game/{game_id}/abort') as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            print(e)
            return False

    @retry(**BASIC_RETRY_CONDITIONS)
    async def accept_challenge(self, challenge_id: str) -> bool:
        try:
            async with self.lichess_session.post(f'/api/challenge/{challenge_id}/accept') as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            if not 400 <= e.status <= 499:
                print(e)
            return False

    @retry(**BASIC_RETRY_CONDITIONS)
    async def cancel_challenge(self, challenge_id: str) -> bool:
        try:
            async with self.lichess_session.post(f'/api/challenge/{challenge_id}/cancel') as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            print(e)
            return False

    async def create_challenge(self,
                               challenge_request: Challenge_Request
                               ) -> AsyncIterator[API_Challenge_Reponse]:
        try:
            async with self.lichess_session.post(f'/api/challenge/{challenge_request.opponent_username}',
                                                 data={'rated': str(challenge_request.rated).lower(),
                                                       'clock.limit': challenge_request.initial_time,
                                                       'clock.increment': challenge_request.increment,
                                                       'color': challenge_request.color.value,
                                                       'variant': challenge_request.variant.value,
                                                       'keepAliveStream': 'true'},
                                                 timeout=aiohttp.ClientTimeout(sock_read=60.0)) as response:

                if response.status == 429:
                    yield API_Challenge_Reponse(has_reached_rate_limit=True)
                    return

                async for line in response.content:
                    if not line.strip():
                        continue

                    data: dict[str, Any] = json.loads(line)
                    yield API_Challenge_Reponse(data.get('id', None),
                                                data.get('done') == 'accepted',
                                                data.get('error'),
                                                data.get('done') == 'declined',
                                                'clock.limit' in data,
                                                'clock.increment' in data)

        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            yield API_Challenge_Reponse(error=str(e))
        except TimeoutError:
            yield API_Challenge_Reponse(error='Connection timed out.')

    @retry(**BASIC_RETRY_CONDITIONS)
    async def decline_challenge(self, challenge_id: str, reason: Decline_Reason) -> bool:
        try:
            async with self.lichess_session.post(f'/api/challenge/{challenge_id}/decline',
                                                 data={'reason': reason.value}) as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            print(e)
            return False

    @retry(**JSON_RETRY_CONDITIONS)
    async def get_account(self) -> dict[str, Any]:
        async with self.lichess_session.get('/api/account') as response:
            json_response = await response.json()

            if 'error' in json_response:
                raise RuntimeError(f'Account error: {json_response["error"]}')

            return json_response

    async def get_chessdb_eval(self, fen: str, best_move: bool, timeout: int) -> dict[str, Any] | None:
        try:
            async with self.external_session.get('http://www.chessdb.cn/cdb.php',
                                                 params={'action': 'querypv',
                                                         'board': fen,
                                                         'stable': int(best_move),
                                                         'json': 1},
                                                 timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            print(f'ChessDB: {e}')
        except TimeoutError:
            print(f'ChessDB: Timed out after {timeout} second(s).')

    async def get_cloud_eval(self, fen: str, variant: Variant, timeout: int) -> dict[str, Any] | None:
        try:
            async with self.lichess_session.get('/api/cloud-eval', params={'fen': fen,
                                                                           'variant': variant.value},
                                                timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            print(f'Cloud: {e}')
        except TimeoutError:
            print(f'Cloud: Timed out after {timeout} second(s).')

    async def get_egtb(self, fen: str, variant: str, timeout: int) -> dict[str, Any] | None:
        try:
            async with self.external_session.get(f'https://tablebase.lichess.ovh/{variant}',
                                                 params={'fen': fen},
                                                 timeout=aiohttp.ClientTimeout(total=timeout)) as response:

                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            print(f'EGTB: {e}')
        except TimeoutError:
            print(f'EGTB: Timed out after {timeout} second(s).')

    @retry(**JSON_RETRY_CONDITIONS)
    async def get_event_stream(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self.lichess_session.get('/api/stream/event',
                                            timeout=aiohttp.ClientTimeout(sock_read=9.0)) as response:
            async for line in response.content:
                if line.strip():
                    await queue.put(json.loads(line))

    @retry(**GAME_STREAM_RETRY_CONDITIONS)
    async def get_game_stream(self, game_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self.lichess_session.get(f'/api/bot/game/stream/{game_id}',
                                            timeout=aiohttp.ClientTimeout(sock_read=9.0)) as response:
            async for line in response.content:
                await queue.put(json.loads(line) if line.strip() else {'type': 'ping'})

    @retry(**JSON_RETRY_CONDITIONS)
    async def get_online_bots(self) -> list[dict[str, Any]]:
        async with self.lichess_session.get('/api/bot/online',
                                            timeout=aiohttp.ClientTimeout(sock_read=9.0)) as response:
            return [json.loads(line) async for line in response.content if line.strip()]

    async def get_opening_explorer(self,
                                   username: str,
                                   fen: str,
                                   variant: Variant,
                                   color: str,
                                   speeds: str,
                                   timeout: int
                                   ) -> dict[str, Any] | None:
        try:
            async with self.external_session.get('https://explorer.lichess.ovh/player',
                                                 params={'player': username, 'variant': variant.value,
                                                         'fen': fen, 'color': color, 'speeds': speeds,
                                                         'modes': 'rated', 'recentGames': 0},
                                                 timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                response.raise_for_status()
                async for line in response.content:
                    if line.strip():
                        return json.loads(line)
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            print(f'Explore: {e}')
        except TimeoutError:
            print(f'Explore: Timed out after {timeout} second(s).')

    @retry(**JSON_RETRY_CONDITIONS)
    async def get_token_scopes(self, token: str) -> str:
        async with self.lichess_session.post('/api/token/test', data=token) as response:
            json_response = await response.json()
            return json_response[token]['scopes']

    @retry(**JSON_RETRY_CONDITIONS)
    async def get_user_status(self, username: str) -> dict[str, Any]:
        async with self.lichess_session.get('/api/users/status', params={'ids': username}) as response:
            json_response = await response.json()
            return json_response[0]

    @retry(**BASIC_RETRY_CONDITIONS)
    async def resign_game(self, game_id: str) -> bool:
        try:
            async with self.lichess_session.post(f'/api/bot/game/{game_id}/resign') as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            print(e)
            return False

    async def send_chat_message(self, game_id: str, room: str, text: str) -> bool:
        try:
            async with self.lichess_session.post(f'/api/bot/game/{game_id}/chat',
                                                 data={'room': room, 'text': text},
                                                 timeout=aiohttp.ClientTimeout(total=1.0)) as response:
                response.raise_for_status()
                return True
        except (aiohttp.ClientError, TimeoutError):
            return False

    @retry(**MOVE_RETRY_CONDITIONS)
    async def send_move(self, game_id: str, uci_move: str, offer_draw: bool) -> bool:
        try:
            async with self.lichess_session.post(f'/api/bot/game/{game_id}/move/{uci_move}',
                                                 params={'offeringDraw': str(offer_draw).lower()},
                                                 timeout=aiohttp.ClientTimeout(total=1.0)) as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            if 500 <= e.status <= 599:
                raise
            if e.status != 400:
                print(e)
            return False

    @retry(**BASIC_RETRY_CONDITIONS)
    async def upgrade_account(self) -> bool:
        try:
            async with self.lichess_session.post('/api/bot/account/upgrade') as response:
                response.raise_for_status()
                return True
        except aiohttp.ClientResponseError as e:
            print(e)
            return False
