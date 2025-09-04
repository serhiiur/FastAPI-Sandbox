from collections.abc import AsyncIterator  # noqa: I001
from secrets import token_hex
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from api import (
  CreateUser,
  UpdateUser,
  DatabaseT,
  CollectionT,
  app,
  get_users_collection,
  get_users_db,
  settings,
)

if TYPE_CHECKING:
  from faker import Faker
  from motor.motor_asyncio import AsyncIOMotorClient


pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture
def user(faker: "Faker") -> CreateUser:
  """Generate a random user."""
  faker.seed_instance()
  return CreateUser.model_construct(
    name=faker.name(),
    email=faker.email(),
    password=faker.password(),
  )


mongo: "AsyncIOMotorClient[Any]" = AsyncMongoMockClient()
db: DatabaseT = getattr(mongo, settings.test_db_name)
collection: CollectionT = getattr(db, settings.collection_name)


async def override_get_users_db() -> DatabaseT:
  return db


async def override_get_users_collection() -> CollectionT:
  return collection


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  # add unique index to email field on the mock collection
  await collection.create_index("email", unique=True)
  app.dependency_overrides[get_users_db] = override_get_users_db
  app.dependency_overrides[get_users_collection] = override_get_users_collection
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


async def test_ping(client: AsyncClient) -> None:
  resp = await client.get("/ping")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == {"ok": 1}


async def test_create_user_already_exists(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_409_CONFLICT


async def test_create_user(client: AsyncClient, user: CreateUser) -> None:
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_201_CREATED
  assert "id" in resp.json()


async def test_get_user(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id


async def test_get_unknown_user(client: AsyncClient) -> None:
  unknown_user_id = token_hex(12)
  resp = await client.get(f"/users/{unknown_user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


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
  # Get User
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id
  # Delete User
  delete_user_resp = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get Deleted User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_unknown_user(client: AsyncClient) -> None:
  unknown_user_id = token_hex(12)
  resp = await client.delete(f"/users/{unknown_user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_user(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  # Get User
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id
  # Update User
  updated_user = UpdateUser.model_construct(
    name=user.name + " Updated",
    password=user.password + " Updated",
  )
  updated_user_resp = await client.patch(
    f"/users/{user_id}", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get Updated User
  get_new_user_resp = await client.get(f"/users/{user_id}")
  get_new_user_resp_json = get_new_user_resp.json()
  assert get_new_user_resp.status_code == status.HTTP_200_OK
  assert get_new_user_resp_json["name"] == updated_user.name
  assert get_new_user_resp_json["password"] == updated_user.password


async def test_update_user_nothing_to_update_error(client: AsyncClient) -> None:
  random_user_id = token_hex(12)
  resp = await client.patch(f"/users/{random_user_id}", json={})
  assert resp.status_code == status.HTTP_400_BAD_REQUEST


async def test_update_unknown_user(client: AsyncClient, user: CreateUser) -> None:
  unknown_user_id = token_hex(12)
  resp = await client.patch(
    f"/users/{unknown_user_id}",
    json=user.model_dump(),
  )
  assert resp.status_code == status.HTTP_404_NOT_FOUND
