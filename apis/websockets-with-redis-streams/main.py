import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache, wraps
from typing import Annotated, Self, TypedDict
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response, WebSocket, status
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from redis.asyncio import ConnectionPool, Redis


class FastAPIKwargs(TypedDict):
  """Kwargs for FastAPI app."""

  title: str
  description: str
  version: str
  debug: bool


class RedisKwargs(TypedDict):
  """Kwargs for Redis client."""

  connection_pool: ConnectionPool


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "Websockets API"
  description: str = "Websockets API with Redis Streams"
  version: str = "0.0.1"
  debug: bool = True

  # Redis settings
  redis_url: str = "redis://localhost:6379/0"
  redis_stream_name: str = "messages"
  redis_online_ws_key: str = "websockets:online"

  @property
  def fastapi_kwargs(self) -> FastAPIKwargs:
    """Kwargs for FastAPI app."""
    return FastAPIKwargs(
      title=self.title,
      description=self.description,
      version=self.version,
      debug=self.debug,
    )

  @property
  def redis_kwargs(self) -> RedisKwargs:
    """Kwargs for Redis client."""
    return RedisKwargs(
      connection_pool=ConnectionPool.from_url(self.redis_url, decode_responses=True),
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


class Timestamp(BaseModel):
  """Schema to provide the current Unix timestamp in UTC."""

  timestamp: int = Field(
    default_factory=lambda: int(datetime.now(UTC).timestamp()),
    description="Current Unix timestamp in UTC",
  )


class Message(Timestamp):
  """Schema to represent a message."""

  id: str = Field(
    default_factory=lambda: str(uuid4()),
    description="Unique identifier of the message",
  )
  text: str = Field(
    min_length=1,
    max_length=255,
    description="Text of the message",
  )


class Online(Timestamp):
  """Schema to represent number of active websocket connections."""

  online: int = Field(
    default=0,
    ge=0,
    description="Number of active websocket connections",
  )


class WSManager:
  """Class to manage websocket connections."""

  def __init__(self, redis: Redis) -> None:
    """Set redis client and init a list of active websocket connections."""
    self.redis = redis
    self.active_connections: set[WebSocket] = set()

  @staticmethod
  def sync_online[T](
    f: Callable[..., Coroutine[None, None, T]],
  ) -> Callable[..., Awaitable[T]]:
    """Save the number of active websocket connections into Redis."""

    @wraps(f)
    async def wrapper(self: Self, ws: WebSocket) -> T:
      res = await f(self, ws)
      online = {len(self.active_connections): int(datetime.now(UTC).timestamp())}
      await self.redis.zadd(settings.redis_online_ws_key, mapping=online)
      return res

    return wrapper

  @sync_online
  async def connect(self, ws: WebSocket) -> None:
    """Add websocket connection to the list of active connections."""
    await ws.accept()
    self.active_connections.add(ws)
    # await self.broadcast(text="Client connected")

  @sync_online
  async def disconnect(self, ws: WebSocket) -> None:
    """Remove the websocket connection from the list of active connections."""
    self.active_connections.remove(ws)
    # await self.broadcast(text="Client disconnected")

  async def broadcast(self, text: str) -> None:
    """Broadcast messages to all active websocket connections.

    Each message is also sent to the Redis Stream whose name is set in the settings.
    """
    message = Message(text=text)
    broadcast_messages = (
      conn.send_text(message.text) for conn in self.active_connections
    )
    await asyncio.gather(
      *broadcast_messages,
      self.redis.xadd(settings.redis_stream_name, message.model_dump()),
    )


class AppState(TypedDict):
  """State of the FastAPI app."""

  redis: Redis
  ws_manager: WSManager


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init websockets manager."""
  async with Redis(**settings.redis_kwargs) as redis:
    yield AppState(redis=redis, ws_manager=WSManager(redis))


app = FastAPI(**settings.fastapi_kwargs, lifespan=lifespan)


async def get_ws_manager(ws: WebSocket) -> WSManager:
  """Return Websockets Manager object, initialized in the lifespan."""
  return ws.state.ws_manager


async def get_redis(request: Request) -> WSManager:
  """Return Redis object, initialized in the lifespan."""
  return request.state.redis


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


@app.get("/online")
async def online(redis: Annotated[Redis, Depends(get_redis)]) -> Online:
  """Return number of active websocket connections."""
  if res := await redis.zrevrange(settings.redis_online_ws_key, 0, 0, withscores=True):
    return Online(online=res[0][0], timestamp=res[0][1])
  return Online()


@app.websocket("/ws")
async def websocket(
  ws: WebSocket,
  ws_manager: Annotated[WSManager, Depends(get_ws_manager)],
) -> None:
  """Handle websocket connections."""
  await ws_manager.connect(ws)
  async for text in ws.iter_text():
    await ws_manager.broadcast(text)
  await ws_manager.disconnect(ws)
