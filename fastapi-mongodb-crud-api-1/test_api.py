from collections.abc import AsyncIterator
from datetime import UTC, datetime
from secrets import token_hex

import pytest
from api import Movie, MovieAwards, MovieImdb, UpdateMovie, app
from asgi_lifespan import LifespanManager
from faker import Faker
from fastapi import status
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

DB_NAME = "test_sample_mflix"

mongo_client = AsyncMongoMockClient()
db = getattr(mongo_client, DB_NAME)

# Replace real DB object defined in the lifespan
app.state.db = db


def generate_movie_info(faker: Faker) -> Movie:
  """Generate a random movie."""
  movie_awards = MovieAwards(
    wins=faker.random_number(), nominations=faker.random_number(), text=faker.sentence()
  )
  movie_imdb = MovieImdb(
    id=faker.random_number(), rating=faker.random_number(), votes=faker.random_number()
  )
  return Movie(
    title=faker.sentence(),
    num_mflix_comments=faker.random_number(),
    awards=movie_awards,
    lastupdated=str(faker.date_time()),
    year=faker.year(),
    imdb=movie_imdb,
    countries=[faker.country(), faker.country()],
    directors=[faker.name()],
    type=faker.word(),
  )


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Lifespan manager is required here in order to trigger async
  'beanie.init_beanie' function in the lifespan of the app.

  It will not work without it.
  See Warning in https://fastapi.tiangolo.com/advanced/async-tests/#other-asynchronous-function-calls
  """  # noqa: D205
  async with LifespanManager(app) as manager:
    transport = ASGITransport(manager.app)
    async with AsyncClient(base_url="http://test", transport=transport) as ac:
      yield ac


@pytest.fixture
def faker() -> Faker:
  return Faker()


@pytest.mark.anyio
async def test_ping(client: AsyncClient) -> None:
  resp = await client.get("/ping/")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == {"ok": 1}


@pytest.mark.anyio
async def test_create_movie(client: AsyncClient, faker: Faker) -> None:
  movie = generate_movie_info(faker)
  create_movie_resp = await client.post("/movies/", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  assert "id" in create_movie_resp.json()


@pytest.mark.anyio
async def test_get_movie(client: AsyncClient, faker: Faker) -> None:
  # Create Movie
  movie = generate_movie_info(faker)
  create_movie_resp = await client.post("/movies/", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["id"]
  # Get Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}/")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["id"] == movie_id


@pytest.mark.anyio
async def test_get_unknown_movie(client: AsyncClient) -> None:
  # Get Unknown Movie
  unknown_movie_id = token_hex(12)
  get_unknown_movie_resp = await client.get(f"/movies/{unknown_movie_id}/")
  assert get_unknown_movie_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_get_movies(client: AsyncClient, faker: Faker) -> None:
  # Create 3 Movies
  total_new_movies = 3
  for _ in range(total_new_movies):
    movie = generate_movie_info(faker)
    create_movie_resp = await client.post("/movies/", json=movie.model_dump())
    assert create_movie_resp.status_code == status.HTTP_201_CREATED
  # Get Movies
  get_movies_resp = await client.get("/movies/")
  assert get_movies_resp.status_code == status.HTTP_200_OK
  assert get_movies_resp.json()["movies"]
  assert get_movies_resp.json()["count"] >= total_new_movies


@pytest.mark.anyio
async def test_delete_movie(client: AsyncClient, faker: Faker) -> None:
  # Create Movie
  movie = generate_movie_info(faker)
  create_movie_resp = await client.post("/movies/", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["id"]
  # Get Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}/")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["id"] == movie_id
  # Delete Movie
  delete_movie_resp = await client.delete(f"/movies/{movie_id}/")
  assert delete_movie_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get Deleted Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}/")
  assert get_movie_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_update_movie(client: AsyncClient, faker: Faker) -> None:
  # Create Movie
  movie = generate_movie_info(faker)
  create_movie_resp = await client.post("/movies/", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["id"]
  # Get Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}/")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["id"] == movie_id
  # Update Movie
  updated_movie = UpdateMovie(
    title=faker.sentence(), num_mflix_comments=faker.random_number()
  )
  updated_movie_resp = await client.put(
    f"/movies/{movie_id}/", json=updated_movie.model_dump()
  )
  assert updated_movie_resp.status_code == status.HTTP_200_OK
  # Get Updated Movie
  get_new_movie_resp = await client.get(f"/movies/{movie_id}/")
  get_new_movie_resp_json = get_new_movie_resp.json()
  assert get_new_movie_resp.status_code == status.HTTP_200_OK
  assert get_new_movie_resp_json["title"] == updated_movie.title
  assert (
    get_new_movie_resp_json["num_mflix_comments"] == updated_movie.num_mflix_comments
  )
  movie_lastupdated = datetime.fromisoformat(get_new_movie_resp_json["lastupdated"])
  dt_now = datetime.now(UTC)
  assert dt_now >= movie_lastupdated
