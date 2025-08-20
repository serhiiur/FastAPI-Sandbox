import asyncio  # noqa: I001
from collections.abc import AsyncIterator
from typing import Final

import pytest
from faker import Faker
from fastapi import status
from httpx import AsyncClient, ASGITransport, Response
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)

from api import (
  app,
  Base,
  CreateUser,
  configure_logging,
  get_session,
  MAX_USER_NAME_LENGTH,
  MIN_USER_NAME_LENGTH,
  UpdateUser,
)

# Constants
DATABASE_URL: Final[str] = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(
  engine,
  class_=AsyncSession,
  expire_on_commit=False,
)
faker = Faker()

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session", autouse=True)
async def migrate_db() -> AsyncIterator:
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
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  # Set application state
  logger = configure_logging()
  app.state.logger = logger

  # Override application dependencies
  app.dependency_overrides[get_session] = override_get_session
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


def generate_user_info() -> CreateUser:
  """Generate random info about user to be created."""
  return CreateUser(name=faker.name(), email=faker.email())


async def create_user(
  client: AsyncClient,
  user: CreateUser,
  expected_http_status_code: int = status.HTTP_200_OK,
) -> Response:
  """Perform API call to create a random user for testing."""
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == expected_http_status_code
  # user.id = resp.json()["id"]
  return resp


async def get_user(
  client: AsyncClient,
  user_id: str,
  expected_http_status_code: int = status.HTTP_200_OK,
) -> Response:
  """Perform API call to get a random user for testing."""
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == expected_http_status_code
  return resp


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_incorrect_email(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  user.email = user.name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert "value is not a valid email address" in resp.json()["error"]


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_long_name(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  random_long_name = faker.pystr(
    min_chars=MAX_USER_NAME_LENGTH + 1,
    max_chars=MAX_USER_NAME_LENGTH + 1,
  )
  user.name = random_long_name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert f"at most {MAX_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_short_name(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  random_short_name = faker.pystr(
    min_chars=MIN_USER_NAME_LENGTH - 1,
    max_chars=MIN_USER_NAME_LENGTH - 1,
  )
  user.name = random_short_name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert f"at least {MIN_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.parametrize(
  ("first_user", "second_user"),
  [(generate_user_info(), generate_user_info())],
)
async def test_create_user_email_already_exists(
  client: AsyncClient,
  first_user: CreateUser,
  second_user: CreateUser,
) -> None:
  # Create first user
  await create_user(client, first_user)
  second_user.email = first_user.email
  create_second_user_resp = await create_user(
    client,
    second_user,
    expected_http_status_code=status.HTTP_409_CONFLICT,
  )
  assert "already exists" in create_second_user_resp.json()["error"]


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  resp = await create_user(client, user)
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_get_unknown_user(
  client: AsyncClient,
  user_id: str,
) -> None:
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_valid_user(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  # Create first user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  resp = await client.get(f"/users/{new_user['id']}")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_delete_unknown_user(
  client: AsyncClient,
  user_id: str,
) -> None:
  resp = await client.delete(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  resp = await client.delete(f"/users/{new_user['id']}")
  assert resp.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_update_user_incorrect_email(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  # Set invalid email
  user.email = faker.name()
  resp = await client.patch(
    f"/users/{new_user['id']}",
    json=user.model_dump(exclude={"id", "name"}),
  )
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert "not a valid email address" in resp.json()["error"]


@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_update_unknown_user(
  client: AsyncClient,
  user_id: str,
) -> None:
  resp = await client.patch(f"/users/{user_id}", json={})
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
  ("user", "new_user_name"),
  [(generate_user_info(), faker.name())],
)
async def test_update_user_name(
  client: AsyncClient,
  user: CreateUser,
  new_user_name: str,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  user.name = new_user_name
  resp = await client.patch(
    f"/users/{new_user['id']}",
    json=user.model_dump(exclude={"id", "email"}),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"


@pytest.mark.parametrize(
  ("user", "new_user_email"),
  [(generate_user_info(), faker.email())],
)
async def test_update_user_email(
  client: AsyncClient,
  user: CreateUser,
  new_user_email: str,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  user.email = new_user_email
  resp = await client.patch(
    f"/users/{new_user['id']}",
    json=user.model_dump(exclude={"id", "name"}),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"


@pytest.mark.parametrize(
  ("first_user", "second_user"),
  [(generate_user_info(), generate_user_info())],
)
async def test_update_user_email_already_exists(
  client: AsyncClient,
  first_user: CreateUser,
  second_user: CreateUser,
) -> None:
  # Create first user
  await create_user(client, first_user)
  # Create second user
  create_second_user_resp = await create_user(client, second_user)
  new_user = create_second_user_resp.json()

  # Update email of the second user to be equal email of the first user
  second_user.email = first_user.email

  resp = await client.patch(
    f"/users/{new_user['id']}",
    json=second_user.model_dump(exclude={"id", "name"}),
  )
  assert resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in resp.json()["error"]


@pytest.mark.parametrize(
  ("user", "updated_user"),
  [(generate_user_info(), generate_user_info())],
)
async def test_update_user(
  client: AsyncClient,
  user: CreateUser,
  updated_user: UpdateUser,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  new_user = create_user_resp.json()
  resp = await client.patch(
    f"/users/{new_user['id']}",
    json=updated_user.model_dump(),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"
  # resp_json = resp.json()
  # assert resp_json["id"] == new_user["id"]
  # assert resp_json["name"] == updated_user.name
  # assert resp_json["email"] == updated_user.email


async def create_n_users_asynchronously(
  client: AsyncClient,
  n: int,
) -> None:
  """Perform API call to create N users asynchronously."""
  async with asyncio.TaskGroup() as tg:
    tasks: list[asyncio.Task] = []
    for _ in range(n):
      user: CreateUser = generate_user_info()
      task = tg.create_task(
        client.post("/users", json=user.model_dump()),
      )
      tasks.append(task)
  # check if all users added successfully
  for task in tasks:
    user_created_response: Response = task.result()
    assert user_created_response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("total_users", [faker.random_int(min=10, max=50)])
async def test_get_users(
  client: AsyncClient,
  total_users: int,
) -> None:
  # Create random N users
  await create_n_users_asynchronously(client, total_users)
  resp = await client.get("/users")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["total_count"] >= total_users
  assert "data" in resp_json


@pytest.mark.parametrize("total_users", [faker.random_int(min=10, max=50)])
async def test_get_users_limit(
  client: AsyncClient,
  total_users: int,
) -> None:
  # Create random N users
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  request_params = {"limit": total_users_to_fetch, "offset": 0}
  resp = await client.get("/users", params=request_params)
  resp_json = resp.json()
  assert resp_json["total_count"] != total_users_to_fetch
  assert len(resp_json["data"]) == total_users_to_fetch


@pytest.mark.parametrize("total_users", [faker.random_int(min=10, max=50)])
async def test_get_users_limit_with_offset(
  client: AsyncClient,
  total_users: int,
) -> None:
  # Create random N users
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  offset = total_users - total_users_to_fetch
  request_params = {"limit": total_users_to_fetch, "offset": offset}
  resp = await client.get("/users", params=request_params)
  resp_json = resp.json()
  assert resp_json["total_count"] != total_users_to_fetch
  assert len(resp_json["data"]) == (total_users_to_fetch - offset) + 1


@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_filter(
  client: AsyncClient,
  total_users: int,
) -> None:
  pass


@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_order_filter(
  client: AsyncClient,
  total_users: int,
) -> None:
  pass
