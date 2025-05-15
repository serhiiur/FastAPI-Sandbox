import asyncio
from typing import AsyncIterator

import pytest
from faker import Faker
from fakeredis import FakeAsyncRedis
from fastapi import status
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from httpx import AsyncClient as AC, ASGITransport, Response
from sqlalchemy.ext.asyncio import (
  AsyncSession as AS,
  async_sessionmaker,
  create_async_engine
)

from api import (
  app,
  Base,
  CreateUser,
  get_session,
  get_redis,
  MAX_USER_NAME_LENGTH,
  MIN_USER_NAME_LENGTH,
  UpdateUser,
  UserSelectFilters,
  users_cache_key_builder,
)


DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, class_=AS, expire_on_commit=False)
faker = Faker()
redis_client = FakeAsyncRedis()


@pytest.fixture(scope="session", autouse=True)
async def init_cache() -> AsyncIterator:
  """Initialize FastAPI Cache using fake redis client."""
  FastAPICache.init(
    RedisBackend(redis_client),
    key_builder=users_cache_key_builder
  )
  yield
  FastAPICache.reset()


@pytest.fixture(scope="session", autouse=True)
async def migrate_db() -> AsyncIterator:
  """
  Automatically create and drop the database for
  testing on startup and shutdown of the test session.
  """
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)


async def override_get_session() -> AsyncIterator[AS]:
  """Override dependency for API routes to interact with the database."""
  async with async_session() as session:
    yield session


async def override_get_redis() -> FakeAsyncRedis:
  """Override dependency for API routes to get async redis client"""
  return redis_client


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests"""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AC]:
  """Async HTTP client to test FastAPI endpoints."""
  app.dependency_overrides[get_session] = override_get_session
  app.dependency_overrides[get_redis] = override_get_redis
  transport = ASGITransport(app)
  async with AC(base_url="http://test", transport=transport) as ac:
    yield ac


class CreateTestUser(CreateUser):
  """Schema to represent info about created user"""
  id: str | None = None


def generate_user_info() -> CreateTestUser:
  """Generate random info about user to be saved into the database"""
  return CreateTestUser(name=faker.name(), email=faker.email())


async def create_user(
  client: AC,
  user: CreateTestUser,
  expected_http_status_code: int = status.HTTP_201_CREATED
) -> Response:
  """Helper function to create a user"""
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == expected_http_status_code
  user.id = resp.json().get("id")  # type: ignore
  return resp

async def get_user(
  client: AC,
  user_id: str,
  expected_http_status_code: int = status.HTTP_200_OK  
) -> Response:
  """Helper function to get a user"""
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == expected_http_status_code
  return resp


@pytest.mark.anyio
async def test_health(client: AC) -> None:
 resp = await client.get("/health")
 assert resp.status_code == status.HTTP_200_OK
 assert resp.json() == {"response": "ok"}


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_incorrect_email(client: AC, user: CreateTestUser) -> None:
  user.email = user.name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
  )
  assert "value is not a valid email address" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_long_name(client: AC, user: CreateTestUser) -> None:
  user.name = faker.pystr(MAX_USER_NAME_LENGTH+1, MAX_USER_NAME_LENGTH+1)
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
  )
  assert f"at most {MAX_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_short_name(client: AC, user: CreateTestUser) -> None:
  user.name = faker.pystr(MIN_USER_NAME_LENGTH-1, MIN_USER_NAME_LENGTH-1)
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
  )
  assert f"at least {MIN_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  "first_user, second_user",
  [(generate_user_info(), generate_user_info())]
)
async def test_create_user_email_already_exists(
  client: AC,
  first_user: CreateTestUser,
  second_user: CreateTestUser
) -> None:
  _ = await create_user(client, first_user)
  second_user.email = first_user.email
  create_second_user_resp = await create_user(
    client,
    second_user,
    expected_http_status_code=status.HTTP_409_CONFLICT
  )
  assert "already exists" in create_second_user_resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user(client: AC, user: CreateTestUser) -> None:
  resp = await create_user(client, user)
  resp_json = resp.json()
  assert resp_json["id"] == user.id
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


@pytest.mark.anyio
@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_get_unknown_user(client: AC, user_id: str) -> None:
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_valid_user(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)
  resp = await client.get(f"/users/{user.id}")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["id"] == user.id
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


@pytest.mark.anyio
@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_delete_unknown_user(client: AC, user_id: str) -> None:
  resp = await client.delete(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)
  resp = await client.delete(f"/users/{user.id}")
  assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_update_user_incorrect_email(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)
  # Set invalid email
  user.email = faker.name()
  resp = await client.patch(
    f"/users/{user.id}",
    json=user.model_dump(exclude=["id", "name"])
  )
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert "not a valid email address" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_update_unknown_user(client: AC, user_id: str) -> None:
  resp = await client.patch(f"/users/{user_id}", json={})
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize(
  "user, new_user_name",
  [(generate_user_info(), faker.name())]
)
async def test_update_user_name(
  client: AC,
  user: CreateTestUser,
  new_user_name: str
) -> None:
  _ = await create_user(client, user)
  user.name = new_user_name
  resp = await client.patch(
    f"/users/{user.id}",
    json=user.model_dump(exclude=["id", "email"])
  )
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["id"] == user.id
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email


@pytest.mark.anyio
@pytest.mark.parametrize(
  "user, new_user_email",
  [(generate_user_info(), faker.email())]
)
async def test_update_user_email(
  client: AC,
  user: CreateTestUser,
  new_user_email: str
) -> None:
  _ = await create_user(client, user)
  user.email = new_user_email
  resp = await client.patch(
    f"/users/{user.id}",
    json=user.model_dump(exclude=["id", "name"])
  )
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["id"] == user.id
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email


@pytest.mark.anyio
@pytest.mark.parametrize(
  "first_user, second_user",
  [(generate_user_info(), generate_user_info())]
)
async def test_update_user_email_already_exists(
  client: AC,
  first_user: CreateTestUser,
  second_user: CreateTestUser
) -> None:
  _ = await create_user(client, first_user)
  _ = await create_user(client, second_user)

  # Update email of the second user to be equal email of the first user
  second_user.email = first_user.email

  resp = await client.patch(
    f"/users/{second_user.id}",
    json=second_user.model_dump(exclude=["id", "name"])
  )
  assert resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  "user, updated_user",
  [(generate_user_info(), generate_user_info())]
)
async def test_update_user(
  client: AC,
  user: CreateTestUser,
  updated_user: UpdateUser
) -> None:
  _ = await create_user(client, user)
  resp = await client.patch(
    f"/users/{user.id}",
    json=updated_user.model_dump()
  )
  resp_json = resp.json()
  assert resp_json["id"] == user.id
  assert resp_json["name"] == updated_user.name
  assert resp_json["email"] == updated_user.email


async def create_n_users_asynchronously(
  client: AC,
  total_users: int
) -> None:
  """
  Helper function to create N users asynchonously and
  verify that all users have been added successfully.

  :param client: Async Http client
  :param total_users: number of users to create
  """
  async with asyncio.TaskGroup() as tg:
    tasks: list[asyncio.Task] = []
    for _ in range(total_users):
      user = generate_user_info()
      create_user_task = tg.create_task(client.post("/users", json=user.model_dump()))
      tasks.append(create_user_task)
  for task in tasks:
    user_created_response: Response = task.result()
    assert user_created_response.status_code == status.HTTP_201_CREATED


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=2, max=10)]
)
async def test_get_users(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  resp = await client.get("/users")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["total_count"] >= total_users
  assert "data" in resp_json


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=2, max=10)]
)
async def test_get_users_limit(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  request_filters = UserSelectFilters(limit=total_users_to_fetch)
  resp = await client.get(
    "/users",
    params=request_filters.model_dump(exclude_defaults=True)
  )
  resp_json = resp.json()
  assert resp_json["total_count"] != total_users_to_fetch
  assert len(resp_json["data"]) == total_users_to_fetch


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=2, max=10)]
)
async def test_get_users_limit_with_offset(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  offset = total_users - total_users_to_fetch
  request_filters = UserSelectFilters(limit=total_users_to_fetch, offset=offset)
  resp = await client.get(
    "/users",
    params=request_filters.model_dump(exclude_defaults=True)
  )
  resp_json = resp.json()
  assert resp_json["total_count"] != total_users_to_fetch
  assert len(resp_json["data"]) == (total_users_to_fetch - offset) + 1


@pytest.mark.anyio
@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_filter(client: AC, total_users: int) -> None:
  pass


@pytest.mark.anyio
@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_order_filter(client: AC, total_users: int) -> None:
  pass


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_user_is_cached(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)

  # Get the user (after first fetch the response will be added to cache)
  get_user_resp = await get_user(client, user.id)
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, user.id)
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_user_is_not_cached(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)

  # Get the user (after the first fetch the response will be added to cache)
  get_user_resp = await get_user(client, user.id)
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Disable cache
  FastAPICache._enable = False

  # Get the user again (response isn't cached)
  get_user_resp_cached = await get_user(client, user.id)
  assert "X-FastAPI-Cache" not in get_user_resp_cached.headers

  # Enable cache
  FastAPICache._enable = True


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=2, max=10)]
)
async def test_get_users_are_cached(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)

  # Get the users (after first fetch the response will be added to cache)
  get_users_resp = await client.get("/users", params={"limit": total_users})
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the users again (this time the response will be taken from cache)
  get_users_resp_cached = await client.get("/users", params={"limit": total_users})
  assert get_users_resp_cached.status_code == status.HTTP_200_OK
  assert get_users_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=2, max=10)]
)
async def test_get_users_are_not_cached(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)

  # Get the users (after first fetch the response will be added to cache)
  get_users_resp = await client.get("/users", params={"limit": total_users})
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the users again (this time the response will be taken from cache)
  get_users_resp_cached = await client.get("/users", params={"limit": total_users})
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


@pytest.mark.anyio
@pytest.mark.parametrize(
  "user, new_user_name",
  [(generate_user_info(), faker.name())]
)
async def test_update_user_invalidate_cache(
  client: AC,
  user: CreateTestUser,
  new_user_name: str
) -> None:
  _ = await create_user(client, user)

  get_user_resp = await get_user(client, user.id)
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, user.id)
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"

  # Update the user (cache will be automatically invalidated)
  user.name = new_user_name
  updated_user_resp = await client.patch(
    f"/users/{user.id}",
    json=user.model_dump(exclude=["id", "email"])
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK

  # Get the user (new user info will be added to cache)
  get_update_user_resp = await get_user(client, user.id)
  assert get_update_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_updated_user_resp_cached = await get_user(client, user.id)
  assert get_updated_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user_invalidate_cache(client: AC, user: CreateTestUser) -> None:
  _ = await create_user(client, user)

  # Get the user (after first fetch the response will be added to cache)
  get_user_resp = await get_user(client, user.id)
  assert get_user_resp.headers.get("X-FastAPI-Cache") == "MISS"

  # Get the user again (this time the response will be taken from cache)
  get_user_resp_cached = await get_user(client, user.id)
  assert get_user_resp_cached.headers.get("X-FastAPI-Cache") == "HIT"

  # Delete User
  delete_user_resp = await client.delete(f"/users/{user.id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT

  # Get the user (cache is invalidated after delete, so the user will not be found)
  _ = await get_user(
    client,
    user.id,
    expected_http_status_code=status.HTTP_404_NOT_FOUND
  )
