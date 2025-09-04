import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from api import CreateUser, UpdateUser, app
from fastapi import status
from httpx import ASGITransport, AsyncClient

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
  # use a different logger specifically for testing
  app.state.logger = logging.getLogger(__name__)
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.fixture
def user(faker: "Faker") -> CreateUser:
  """Generate random info about user."""
  faker.seed_instance()
  return CreateUser.model_construct(name=faker.name(), email=faker.email())


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


async def test_create_user(client: AsyncClient, user: CreateUser) -> None:
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_201_CREATED
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "pk" in resp_json
  assert "created_at" in resp_json


async def test_get_unknown_user(client: AsyncClient) -> None:
  unknown_user_id = -1
  resp = await client.get(f"/users/{unknown_user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_get_user(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  user_id = create_user_resp.json()["pk"]
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == user.name
  assert get_user_resp_json["email"] == user.email
  assert "pk" in get_user_resp_json
  assert "created_at" in get_user_resp_json


async def test_get_users(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  get_users_resp = await client.get("/users")
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.json()["users"]
  assert get_users_resp.json()["count"] >= 1


async def test_delete_user(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  user_id = create_user_resp.json()["pk"]
  # Delete User
  delete_user_resp = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get the deleted user
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_unknown_user(client: AsyncClient, user: CreateUser) -> None:
  unknown_user_id = -1
  resp = await client.patch(f"/users/{unknown_user_id}", json=user.model_dump())
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_user_name(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user = UpdateUser.model_construct(name=user.name + " Updated")
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump(),
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == create_user_resp_json["email"]


async def test_update_user_email(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user = UpdateUser.model_construct(email=faker.email())
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump(),
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == create_user_resp_json["name"]
  assert get_user_resp_json["email"] == updated_user.email


async def test_update_user(
  client: AsyncClient,
  user: CreateUser,
  faker: "Faker",
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user = UpdateUser.model_construct(
    name=faker.name(),
    email=faker.email(),
  )
  updated_user_resp = await client.patch(
    f"/users/{user_id}", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == updated_user.email
