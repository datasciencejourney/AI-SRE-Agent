import json

import redis.asyncio as redis
from redis.exceptions import ResponseError

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=30,
            socket_connect_timeout=10,
        )
    return _client


async def publish(message: dict) -> None:
    await get_redis().xadd(settings.alert_stream, {"data": json.dumps(message)})


async def ensure_group() -> None:
    try:
        await get_redis().xgroup_create(settings.alert_stream, settings.consumer_group, id="0", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):  # group already exists, that is fine
            raise


async def dead_letter(message: dict, error: str) -> None:
    await get_redis().xadd(settings.dead_stream, {"data": json.dumps(message), "error": error[:500]})
