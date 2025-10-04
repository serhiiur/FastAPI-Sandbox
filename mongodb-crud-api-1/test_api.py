from collections.abc import AsyncIterator  # noqa: I001
from datetime import UTC, datetime
from secrets import token_hex
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

import pytest
from asgi_lifespan import LifespanManager
from fastapi import status
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from api import Movie, MovieAwards, MovieImdb, UpdateMovie, app, settings

if TYPE_CHECKING:
  from faker import Faker
  from motor.motor_asyncio import AsyncIOMotorClient
  from pymongo.asynchronous.database import AsyncDatabase


pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture
def movie(faker: "Faker") -> Movie:
  """Generate a random movie."""
  faker.seed_instance()
  movie_awards = MovieAwards(
    wins=faker.random_number(),
    nominations=faker.random_number(),
    text=faker.sentence(),
  )
  movie_imdb = MovieImdb(
    id=faker.random_number(),
    rating=faker.random_number(),
    votes=faker.random_number(),
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


mongo: "AsyncIOMotorClient[Any]" = AsyncMongoMockClient()
db: "AsyncDatabase[Mapping[str, Any]]" = getattr(mongo, settings.test_db_name)


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Lifespan manager is required here in order to trigger async
  'beanie.init_beanie' function in the lifespan of the app.

  It will not work without it.
  See Warning in https://fastapi.tiangolo.com/advanced/async-tests/#other-asynchronous-function-calls
  """  # noqa: D205
  app.state.db = db
  async with LifespanManager(app) as manager:
    transport = ASGITransport(manager.app)
    async with AsyncClient(base_url="http://test", transport=transport) as ac:
      yield ac


async def test_create_movie(client: AsyncClient, movie: Movie) -> None:
  resp = await client.post("/movies", json=movie.model_dump())
  assert resp.status_code == status.HTTP_201_CREATED
  assert "_id" in resp.json()


async def test_get_movie(client: AsyncClient, movie: Movie) -> None:
  create_movie_resp = await client.post("/movies", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["_id"]
  get_movie_resp = await client.get(f"/movies/{movie_id}")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["_id"] == movie_id


async def test_get_unknown_movie(client: AsyncClient) -> None:
  unknown_movie_id = token_hex(12)
  resp = await client.get(f"/movies/{unknown_movie_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_get_movies(client: AsyncClient, movie: Movie) -> None:
  create_movie_resp = await client.post("/movies", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  get_movies_resp = await client.get("/movies")
  assert get_movies_resp.status_code == status.HTTP_200_OK
  assert get_movies_resp.json()["movies"]
  assert get_movies_resp.json()["count"] >= 1


async def test_delete_movie(client: AsyncClient, movie: Movie) -> None:
  # Create Movie
  create_movie_resp = await client.post("/movies", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["_id"]
  # Get Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["_id"] == movie_id
  # Delete Movie
  delete_movie_resp = await client.delete(f"/movies/{movie_id}")
  assert delete_movie_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get Deleted Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}")
  assert get_movie_resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_movie(client: AsyncClient, movie: Movie) -> None:
  # Create Movie
  create_movie_resp = await client.post("/movies", json=movie.model_dump())
  assert create_movie_resp.status_code == status.HTTP_201_CREATED
  movie_id = create_movie_resp.json()["_id"]
  # Get Movie
  get_movie_resp = await client.get(f"/movies/{movie_id}")
  assert get_movie_resp.status_code == status.HTTP_200_OK
  assert get_movie_resp.json()["_id"] == movie_id
  # Update Movie
  updated_movie = UpdateMovie.model_construct(
    title=movie.title + " Updated",
    num_mflix_comments=-1,
  )
  updated_movie_resp = await client.patch(
    f"/movies/{movie_id}", json=updated_movie.model_dump()
  )
  assert updated_movie_resp.status_code == status.HTTP_200_OK
  # Get Updated Movie
  get_new_movie_resp = await client.get(f"/movies/{movie_id}")
  get_new_movie_resp_json = get_new_movie_resp.json()
  assert get_new_movie_resp.status_code == status.HTTP_200_OK
  assert get_new_movie_resp_json["title"] == updated_movie.title
  assert (
    get_new_movie_resp_json["num_mflix_comments"] == updated_movie.num_mflix_comments
  )
  movie_lastupdated = datetime.fromisoformat(get_new_movie_resp_json["lastupdated"])
  dt_now = datetime.now(UTC)
  assert dt_now >= movie_lastupdated
