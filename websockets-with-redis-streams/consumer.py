import asyncio  # noqa: I001

from redis.asyncio import Redis

from main import settings


async def main() -> None:
  """Ingest and display messages from the Redis Stream."""
  async with Redis(decode_responses=True) as r:
    while True:
      received = await r.xread({settings.redis_stream_name: "$"}, block=0)
      message = received[0][1][0][1]
      print(message)


if __name__ == "__main__":
  asyncio.run(main())
