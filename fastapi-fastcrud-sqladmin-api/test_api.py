import asyncio
from collections.abc import AsyncIterator

import pytest

from faker import Faker
from fastapi import status
from httpx import ASGITransport, Response
from httpx import AsyncClient as AC
from sqlalchemy.ext.asyncio import AsyncSession as AS
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import (
  MAX_USER_NAME_LENGTH,
  MIN_USER_NAME_LENGTH,
  Base,
  CreateUser,
  UpdateUser,
  app,
  get_session,
)


DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, class_=AS, expire_on_commit=False)
faker = Faker()


@pytest.fixture(scope="session", autouse=True)
async def migrate_db() -> AsyncIterator:
  """Create and drop database tables for testing."""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)


async def override_get_session() -> AsyncIterator[AS]:
  """Override dependency for API routes to interact with the database."""
  async with async_session() as session:
    yield session


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AC]:
  """Async HTTP client to test FastAPI endpoints."""
  app.dependency_overrides[get_session] = override_get_session
  transport = ASGITransport(app)
  async with AC(base_url="http://test", transport=transport) as ac:
    yield ac


def generate_user_info() -> CreateUser:
  return CreateUser(name=faker.name(), email=faker.email())


@pytest.mark.anyio
async def test_health(client: AC) -> None:
 resp = await client.get("/health")
 assert resp.status_code == status.HTTP_200_OK
 assert resp.json() == {"response": "ok"}


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_incorrect_email(client: AC, user: CreateUser) -> None:
  user.email = user.name
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert "value is not a valid email address" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_long_name(client: AC, user: CreateUser) -> None:
  user.name = faker.pystr(MAX_USER_NAME_LENGTH+1, MAX_USER_NAME_LENGTH+1)
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert f"at most {MAX_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user_too_short_name(client: AC, user: CreateUser) -> None:
  user.name = faker.pystr(MIN_USER_NAME_LENGTH-1, MIN_USER_NAME_LENGTH-1)
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert f"at least {MIN_USER_NAME_LENGTH} characters" in resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("first_user", "second_user"),
  [(generate_user_info(), generate_user_info())]
)
async def test_create_user_email_already_exists(
  client: AC,
  first_user: CreateUser,
  second_user: CreateUser
) -> None:
  # Create First User
  create_first_user_resp = await client.post("/users", json=first_user.model_dump())
  assert create_first_user_resp.status_code == status.HTTP_200_OK

   # Create Second User
  second_user.email = first_user.email
  create_second_user_resp = await client.post("/users", json=second_user.model_dump())
  assert create_second_user_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in create_second_user_resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user(client: AC, user: CreateUser) -> None:
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email


@pytest.mark.anyio
@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_get_unknown_user(client: AC, user_id: str) -> None:
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_valid_user(client: AC, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  user_id = create_user_resp.json()["id"]
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["id"] == user_id
  assert get_user_resp_json["name"] == user.name
  assert get_user_resp_json["email"] == user.email
  assert "created_at" in get_user_resp_json
  assert "updated_at" in get_user_resp_json


@pytest.mark.anyio
@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_delete_unknown_user(client: AC, user_id: str) -> None:
  resp = await client.delete(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user(client: AC, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  user_id = create_user_resp.json()["id"]
  # Delete User
  delete_user_resp = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
@pytest.mark.parametrize("user", [generate_user_info()])
async def test_update_user_incorrect_email(client: AC, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  user_id = create_user_resp.json()["id"]
  # Update User
  updated_user = UpdateUser(name=faker.name(), email=faker.email())
  updated_user.email = faker.name()
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert "not a valid email address" in updated_user_resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("user", "user_id"),
  [(UpdateUser(), faker.uuid4())]
)
async def test_update_unknown_user(
  client: AC,
  user: UpdateUser,
  user_id: str
) -> None:
  resp = await client.patch(f"/users/{user_id}", json=user.model_dump())
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("user", "new_user_name"),
  [(generate_user_info(), faker.name())]
)
async def test_update_user_name(
  client: AC,
  user: CreateUser,
  new_user_name: str
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["id"]
  # Update User
  updated_user = UpdateUser(name=new_user_name)
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump(exclude_defaults=True)
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["id"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == create_user_resp_json["email"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("user", "new_user_email"),
  [(generate_user_info(), faker.email())]
)
async def test_update_user_email(
  client: AC,
  user: CreateUser,
  new_user_email: str
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["id"]
  # Update User
  updated_user = UpdateUser(email=new_user_email)
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump(exclude_defaults=True)
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["id"] == user_id
  assert get_user_resp_json["name"] == create_user_resp_json["name"]
  assert get_user_resp_json["email"] == updated_user.email


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("first_user", "second_user"),
  [(generate_user_info(), generate_user_info())]
)
async def test_update_user_email_already_exists(
  client: AC,
  first_user: CreateUser,
  second_user: CreateUser
) -> None:
  # Create First User
  create_first_user_resp = await client.post("/users", json=first_user.model_dump())
  assert create_first_user_resp.status_code == status.HTTP_200_OK

   # Create Second User
  create_second_user_resp = await client.post("/users", json=second_user.model_dump())
  assert create_second_user_resp.status_code == status.HTTP_200_OK

  # Update email of the second user to be equal email of the first user
  second_user_id = create_second_user_resp.json()["id"]
  updated_second_user = UpdateUser(email=first_user.email)
  updated_second_user_resp = await client.patch(
    f"/users/{second_user_id}",
    json=updated_second_user.model_dump(exclude_defaults=True)
  )
  assert updated_second_user_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in updated_second_user_resp.json()["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
  ("user", "updated_user"),
  [(
    CreateUser(name=faker.name(), email=faker.email()),
    UpdateUser(name=faker.name(), email=faker.email())
  )]
)
async def test_update_user(
  client: AC,
  user: CreateUser,
  updated_user: UpdateUser
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_200_OK
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["id"]
  # Update User
  updated_user_resp = await client.patch(
    f"/users/{user_id}",
    json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["id"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == updated_user.email


async def create_n_users_asynchronously(
  client: AC,
  total_users: int
) -> None:
  """Create N users asynchronously.

  Additionally it verifies that the users are created successfully.

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
    assert user_created_response.status_code == status.HTTP_200_OK


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=5, max=10)]
)
async def test_get_users(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  resp = await client.get("/users")
  resp_json = resp.json()
  assert resp_json["total_count"] >= total_users
  assert "data" in resp_json


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=5, max=10)]
)
async def test_get_users_limit(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  request_params = {"limit": total_users_to_fetch, "offset": 0}
  resp = await client.get("/users", params=request_params)
  resp_json = resp.json()
  assert resp_json["total_count"] != total_users_to_fetch
  assert len(resp_json["data"]) == total_users_to_fetch


@pytest.mark.anyio
@pytest.mark.parametrize(
  "total_users",
  [faker.random_int(min=5, max=10)]
)
async def test_get_users_limit_with_offset(client: AC, total_users: int) -> None:
  await create_n_users_asynchronously(client, total_users)
  total_users_to_fetch = total_users - 1
  offset = total_users - total_users_to_fetch
  request_params = {"limit": total_users_to_fetch, "offset": offset}
  resp = await client.get("/users", params=request_params)
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
async def test_admin(client: AC) -> None:
  resp = await client.get("/admin/")
  assert resp.status_code == status.HTTP_200_OK
  assert '<span class="nav-link-title">Users</span>' in resp.text
