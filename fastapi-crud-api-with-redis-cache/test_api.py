import asyncio  # noqa: I001
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from faker import Faker
from fakeredis import FakeAsyncRedis
from fastapi import status
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)

from api import (
  Base,
  CreateUser,
  app,
  get_redis,
  get_session,
  settings,
  users_cache_key_builder,
)

if TYPE_CHECKING:
  from redis.asyncio import Redis

engine = create_async_engine(settings.test_database_url)
async_session = async_sessionmaker(
  engine,
  class_=AsyncSession,
  expire_on_commit=False,
)
faker = Faker()

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def redis_client() -> AsyncIterator["Redis"]:
  """Fake Redis client for testing."""
  async with FakeAsyncRedis() as client:
    yield client


@pytest.fixture(scope="session", autouse=True)
async def init_cache(redis_client: "Redis") -> AsyncIterator[None]:
  """Init FastAPI Cache using fake redis client."""
  backend = RedisBackend(redis_client)
  FastAPICache.init(backend, key_builder=users_cache_key_builder)
  yield
  FastAPICache.reset()


@pytest.fixture(scope="session", autouse=True)
async def migrate_db() -> AsyncIterator[None]:
  """Create and drop test test db on startup and shutdown."""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)


async def override_get_session() -> AsyncIterator[AsyncSession]:
  """Override dependency for API routes to interact with db."""
  async with async_session() as session:
    yield session


@pytest.fixture(scope="session")
async def client(redis_client: "Redis") -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""

  async def override_redis_client() -> "Redis":
    return redis_client

  # here we use a different logger specifically for testing
  app.state.logger = logging.getLogger(__name__)
  app.dependency_overrides[get_session] = override_get_session
  app.dependency_overrides[get_redis] = override_redis_client
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


def generate_user_info() -> CreateUser:
  """Generate random info about user to be created."""
  return CreateUser.model_construct(name=faker.name(), email=faker.email())


async def create_user(
  client: AsyncClient,
  user: CreateUser,
  expected_http_status_code: int = status.HTTP_201_CREATED,
) -> Response:
  """Perform API call to create a random user for further testing."""
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == expected_http_status_code
  return resp


async def get_user(
  client: AsyncClient,
  user_id: str,
  expected_http_status_code: int = status.HTTP_200_OK,
) -> Response:
  """Perform API call to get a random user for further testing."""
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == expected_http_status_code
  return resp


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


async def create_n_users_asynchronously(client: AsyncClient, n: int) -> None:
  """Perform API call to create N users asynchronously."""
  async with asyncio.TaskGroup() as tg:
    tasks: list[asyncio.Task[Response]] = []
    for _ in range(n):
      user = generate_user_info()
      task = tg.create_task(
        client.post("/users", json=user.model_dump()),
      )
      tasks.append(task)
  # check if all users added successfully
  for task in tasks:
    user_created_response: Response = task.result()
    assert user_created_response.status_code == status.HTTP_201_CREATED


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_user_is_cached(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()

  # Get the user (after first fetch the response will be added to cache)
  get_user_resp = await get_user(client, new_user["id"])
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, new_user["id"])
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_user_is_not_cached(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()

  # Get the user (after the first fetch the response will be cached)
  get_user_resp = await get_user(client, new_user["id"])
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Disable cache
  FastAPICache._enable = False

  # Get the user again (response isn't cached)
  get_user_resp_cached = await get_user(client, new_user["id"])
  assert "X-FastAPI-Cache" not in get_user_resp_cached.headers

  # Enable cache
  FastAPICache._enable = True


@pytest.mark.parametrize("total_users", [faker.random_int(min=10, max=50)])
async def test_get_users_are_cached(
  client: AsyncClient,
  total_users: int,
) -> None:
  await create_n_users_asynchronously(client, total_users)

  # Get the users (after first fetch the response will be added to cache)
  get_users_resp = await client.get(
    "/users",
    params={"limit": total_users},
  )
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the users again (this time the response will be taken from cache)
  get_users_resp_cached = await client.get(
    "/users",
    params={"limit": total_users},
  )
  assert get_users_resp_cached.status_code == status.HTTP_200_OK
  assert get_users_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.parametrize("total_users", [faker.random_int(min=10, max=50)])
async def test_get_users_are_not_cached(
  client: AsyncClient,
  total_users: int,
) -> None:
  await create_n_users_asynchronously(client, total_users)

  # Get the users (after first fetch the response will be cached)
  get_users_resp = await client.get(
    "/users",
    params={"limit": total_users},
  )
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the users again (this time the response will be taken from cache)
  get_users_resp_cached = await client.get(
    "/users",
    params={"limit": total_users},
  )
  assert get_users_resp_cached.status_code == status.HTTP_200_OK
  assert get_users_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"

  # Disable cache
  FastAPICache._enable = False

  # Get the users again (response isn't cached)
  get_users_resp_not_cached = await client.get("/users")
  assert get_users_resp_not_cached.status_code == status.HTTP_200_OK
  assert "X-FastAPI-Cache" not in get_users_resp_not_cached.headers

  # Enable cache back
  FastAPICache._enable = True


@pytest.mark.parametrize(
  ("user", "new_user_name"),
  [(generate_user_info(), faker.name())],
)
async def test_update_user_invalidate_cache(
  client: AsyncClient,
  user: CreateUser,
  new_user_name: str,
) -> None:
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()

  get_user_resp = await get_user(client, new_user["id"])
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, new_user["id"])
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"

  # Update the user (cache will be automatically invalidated)
  user.name = new_user_name
  updated_user_resp = await client.patch(
    f"/users/{new_user['id']}",
    json=user.model_dump(exclude={"id", "email"}),
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK

  # Get the user (new user info will be added to cache)
  get_update_user_resp = await get_user(client, new_user["id"])
  assert get_update_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_updated_user_resp_cached = await get_user(client, new_user["id"])
  assert get_updated_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user_invalidate_cache(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()

  # Get the user (after first fetch the response will be added to cache)
  get_user_resp = await get_user(client, new_user["id"])
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, new_user["id"])
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"

  # Delete User
  delete_user_resp = await client.delete(f"/users/{new_user['id']}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT

  # Get the user (cache is invalidated after delete, so the user won't be found)
  await get_user(
    client,
    new_user["id"],
    expected_http_status_code=status.HTTP_404_NOT_FOUND,
  )
