from collections.abc import AsyncIterator
from secrets import token_hex

import pytest
from api import CreateUser, UpdateUser, app, get_users_collection, get_users_db
from faker import Faker
from fastapi import status
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

COLLECTION_NAME = "test_users"
DB_NAME = "test_sample_mflix"

mongo_client = AsyncMongoMockClient()
db = getattr(mongo_client, DB_NAME)
collection = getattr(db, COLLECTION_NAME)

# app.state.db = db
# app.state.collection = collection

# Override dependencies to set testing DB and Collection objects
app.dependency_overrides[get_users_db] = lambda: db
app.dependency_overrides[get_users_collection] = lambda: collection


def generate_user_info(faker: Faker) -> CreateUser:
  """Helper function to generate a random user"""
  return CreateUser(name=faker.name(), email=faker.email(), password=faker.password())


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.fixture(scope="function")
def faker() -> Faker:
  return Faker()


@pytest.mark.anyio
async def test_ping(client: AsyncClient) -> None:
  resp = await client.get("/ping/")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == {"ok": 1}


@pytest.mark.anyio
async def test_create_user(client: AsyncClient, faker: Faker) -> None:
  user = generate_user_info(faker)
  create_user_resp = await client.post("/users/", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  assert "id" in create_user_resp.json()


@pytest.mark.anyio
async def test_get_user(client: AsyncClient, faker: Faker) -> None:
  # Create User
  user = generate_user_info(faker)
  create_user_resp = await client.post("/users/", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  # Get User
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}/")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id


@pytest.mark.anyio
async def test_get_unknown_user(client: AsyncClient) -> None:
  # Get Unknown User
  unknown_user_id = token_hex(12)
  get_unknown_user_resp = await client.get(f"/users/{unknown_user_id}/")
  assert get_unknown_user_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_get_users(client: AsyncClient, faker: Faker) -> None:
  # Create 3 Users
  total_new_users = 3
  for _ in range(total_new_users):
    user = generate_user_info(faker)
    create_user_resp = await client.post("/users/", json=user.model_dump())
    assert create_user_resp.status_code == status.HTTP_201_CREATED
  # Get Users
  get_users_resp = await client.get("/users/")
  assert get_users_resp.status_code == status.HTTP_200_OK
  assert get_users_resp.json()["users"]
  assert get_users_resp.json()["count"] >= total_new_users


@pytest.mark.anyio
async def test_delete_user(client: AsyncClient, faker: Faker) -> None:
  # Create User
  user = generate_user_info(faker)
  create_user_resp = await client.post("/users/", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  # Get User
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}/")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id
  # Delete User
  delete_user_resp = await client.delete(f"/users/{user_id}/")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get Deleted User
  get_user_resp = await client.get(f"/users/{user_id}/")
  assert get_user_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_update_user(client: AsyncClient, faker: Faker) -> None:
  # Create User
  user = generate_user_info(faker)
  create_user_resp = await client.post("/users/", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  # Get User
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}/")
  assert get_user_resp.status_code == status.HTTP_200_OK
  assert get_user_resp.json()["id"] == user_id
  # Update User
  updated_user = UpdateUser(
    name=faker.name(), email=faker.email(), password=faker.password()
  )
  updated_user_resp = await client.put(
    f"/users/{user_id}/", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get Updated User
  get_new_user_resp = await client.get(f"/users/{user_id}/")
  get_new_user_resp_json = get_new_user_resp.json()
  assert get_new_user_resp.status_code == status.HTTP_200_OK
  assert get_new_user_resp_json["name"] == updated_user.name
  assert get_new_user_resp_json["email"] == updated_user.email
  assert get_new_user_resp_json["password"] == updated_user.password
