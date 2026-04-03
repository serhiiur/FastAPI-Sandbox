from collections.abc import AsyncIterator  # noqa: I001
from typing import TYPE_CHECKING

import pytest
from asgi_lifespan import LifespanManager
from fastapi import status
from httpx import ASGITransport, AsyncClient, Response
from tortoise import Tortoise

from api import CreateUser, UpdateUser, app, configure_logging, settings

if TYPE_CHECKING:
  from faker import Faker


pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  app.state.logger = configure_logging(__name__)
  app.state.database_url = settings.test_database_url
  async with LifespanManager(app) as manager:
    transport = ASGITransport(manager.app)
    base_url = "http://test"
    async with AsyncClient(base_url=base_url, transport=transport) as ac:
      yield ac
    await Tortoise._drop_databases()  # noqa: SLF001


@pytest.fixture
def user(faker: "Faker") -> CreateUser:
  """Fixture to provide random user info."""
  faker.seed_instance()
  return CreateUser.model_construct(
    email=faker.email(),
    first_name=faker.name(),
    second_name=faker.name(),
    username=faker.user_name(),
    password=faker.password(),
  )


async def create_user(
  client: AsyncClient,
  user: CreateUser,
  expected_http_status_code: int = status.HTTP_201_CREATED,
) -> Response:
  """Perform API call to create a random user for testing."""
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == expected_http_status_code
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


async def test_create_user_invalid_email(client: AsyncClient, user: CreateUser) -> None:
  user.email = user.username
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
  assert "not a valid email address" in resp.json()["error"]


async def test_create_email_already_exists_error(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_409_CONFLICT,
  )
  assert "already exists" in resp.json()["error"]


async def test_create_username_already_exists_error(
  client: AsyncClient, user: CreateUser, faker: "Faker"
) -> None:
  await create_user(client, user)
  user.email = faker.email()
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_409_CONFLICT,
  )
  assert "already exists" in resp.json()["error"]


async def test_create_user_success(client: AsyncClient, user: CreateUser) -> None:
  resp = await create_user(client, user)
  resp_json = resp.json()
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json
  for k, v in resp_json.items():
    if hasattr(user, k):
      assert getattr(user, k) == v


async def test_get_user_success(client: AsyncClient, user: CreateUser) -> None:
  resp = await create_user(client, user)
  user_id = resp.json()["id"]
  get_user_resp = await get_user(client, user_id)
  user_json = get_user_resp.json()
  assert user_json["id"] == user_id
  for k, v in user_json.items():
    if hasattr(user, k):
      assert getattr(user, k) == v


async def test_get_unknown_user_error(client: AsyncClient) -> None:
  resp = await get_user(
    client,
    user_id="-1",
    expected_http_status_code=status.HTTP_404_NOT_FOUND,
  )
  assert "not found" in resp.json()["error"]


async def test_get_multiple_users_success(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  resp = await client.get("/users")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert "data" in resp_json
  assert "count" in resp_json
  assert len(resp_json["data"]) == resp_json["count"]


async def test_get_multiple_users_with_pagination_success(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  await create_user(client, user)
  user.email = faker.email()
  user.username = faker.user_name()
  await create_user(client, user)
  resp = await client.get("/users", params={"limit": 1})
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert "data" in resp_json
  assert "count" in resp_json
  assert len(resp_json["data"]) == resp_json["count"] == 1


async def test_delete_unknown_user_error(client: AsyncClient) -> None:
  resp = await client.delete("/users/-1")
  assert resp.status_code == status.HTTP_404_NOT_FOUND
  assert "not found" in resp.json()["error"]


async def test_delete_user_success(client: AsyncClient, user: CreateUser) -> None:
  resp = await create_user(client, user)
  user_id = resp.json()["id"]
  delete_user_resp = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT
  get_user_resp = await get_user(
    client,
    user_id=user_id,
    expected_http_status_code=status.HTTP_404_NOT_FOUND,
  )
  assert "not found" in get_user_resp.json()["error"]


async def test_update_unknown_user_error(client: AsyncClient, user: CreateUser) -> None:
  resp = await client.put("/users/-1", json=user.model_dump())
  assert resp.status_code == status.HTTP_404_NOT_FOUND
  assert "not found" in resp.json()["error"]


async def test_update_user_email_already_exists_error(
  client: AsyncClient, user: CreateUser, faker: "Faker"
) -> None:
  first_user_email = user.email
  await create_user(client, user)
  user.email = faker.email()
  user.username = faker.user_name()
  create_second_user_resp = await create_user(client, user)
  second_user_id = create_second_user_resp.json()["id"]
  new_user_info = UpdateUser(email=first_user_email)
  update_second_user_email_resp = await client.patch(
    f"/users/{second_user_id}",
    json=new_user_info.model_dump(),
  )
  assert update_second_user_email_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in update_second_user_email_resp.json()["error"]


async def test_update_user_username_already_exists_error(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  first_user_username = user.username
  await create_user(client, user)
  user.email = faker.email()
  user.username = faker.user_name()
  create_second_user_resp = await create_user(client, user)
  second_user_id = create_second_user_resp.json()["id"]
  new_user_info = UpdateUser(username=first_user_username)
  update_second_user_username_resp = await client.patch(
    f"/users/{second_user_id}",
    json=new_user_info.model_dump(),
  )
  assert update_second_user_username_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in update_second_user_username_resp.json()["error"]


async def test_full_update_user_success(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  resp = await create_user(client, user)
  user_id = resp.json()["id"]
  new_user_info = UpdateUser.model_construct(
    email=faker.email(),
    first_name=faker.name(),
    second_name=faker.name(),
    username=faker.user_name(),
    password=faker.password(),
  )
  update_user_resp = await client.put(
    f"/users/{user_id}",
    json=new_user_info.model_dump(),
  )
  assert update_user_resp.status_code == status.HTTP_200_OK
  for k, v in update_user_resp.json().items():
    if hasattr(new_user_info, k):
      assert getattr(new_user_info, k) == v


async def test_partial_update_user_success(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  resp = await create_user(client, user)
  user_id = resp.json()["id"]
  new_user_info = UpdateUser.model_construct(
    email=faker.email(),
    second_name=faker.name(),
  )
  update_user_resp = await client.patch(
    f"/users/{user_id}",
    json=new_user_info.model_dump(),
  )
  assert update_user_resp.status_code == status.HTTP_200_OK
  resp_json = update_user_resp.json()
  assert resp_json["email"] == new_user_info.email
  assert resp_json["second_name"] == new_user_info.second_name
