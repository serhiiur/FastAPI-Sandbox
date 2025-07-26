import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Self

from beanie import Document, PydanticObjectId, init_beanie
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo import ASCENDING

if TYPE_CHECKING:
  from motor.motor_asyncio import AsyncIOMotorDatabase


load_dotenv()


COLLECTION_NAME = "movies"
DB_NAME = "sample_mflix"
MONGODB_URL = os.getenv("MONGODB_URL")


class Pagination(BaseModel):
  """Schema for pagination."""

  limit: int = Field(10, gt=0)
  skip: int = Field(0, ge=0)


class MovieAwards(BaseModel):
  """Schema to represent movie awards."""

  wins: int
  nominations: int
  text: str


class MovieImdb(BaseModel):
  """Schema to represent movie IMDB."""

  id: int
  rating: int | float
  votes: int


class MovieViewer(BaseModel):
  """Schema to represent movie viewers."""

  rating: float
  num_reviews: int = Field(alias="numReviews")
  meter: int | None = None


class MovieTomatoes(BaseModel):
  """Schema to represent movie tomatoes."""

  viewer: MovieViewer
  last_updated: datetime = Field(alias="lastUpdated")


class Movie(Document):
  """Schema to represent a movie in the database."""

  title: str
  num_mflix_comments: int
  awards: MovieAwards
  lastupdated: str
  year: int
  imdb: MovieImdb
  countries: list[str]
  directors: list[str]
  type: str
  plot: str | None = None
  genres: list[str] | None = None
  runtime: int | None = None
  rated: str | None = None
  cast: list[str] | None = None
  poster: str | None = None
  fullplot: str | None = None
  languages: list[str] | None = None
  released: datetime | None = None
  writers: list[str] | None = None
  tomatoes: MovieTomatoes | None = None
  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "id": "573a1391f29313caabcd6d40",
        "plot": "A tipsy doctor encounters his patient sleepwalking on a building ledge, high above the street.",
        "genres": ["Comedy", "Short"],
        "runtime": 26,
        "rated": "PASSED",
        "cast": ["Harold Lloyd", "Roy Brooks", "Mildred Davis", "Wallace Howe"],
        "num_mflix_comments": 1,
        "poster": "https://m.media-amazon.com/images/M/MV5BODliMjc3ODctYjhlOC00MDM5LTgzNmUtMjQ1MmViNDQ0NzlhXkEyXkFqcGdeQXVyNTM3MDMyMDQ@._V1_SY1000_SX677_AL_.jpg",
        "title": "High and Dizzy",
        "fullplot": "After a long wait, a young doctor finally has a patient come to his office. She is a young woman whose father has brought her to be treated for sleep-walking, but the father becomes annoyed with the doctor, and takes his daughter away. Soon afterward, the young doctor shares in a drinking binge with another doctor who has built a still in his office. After a series of misadventures, the two of them wind up in the same hotel where the daughter and her father are staying, leading to some hazardous predicaments.",
        "languages": ["English"],
        "released": -1561334400000,
        "directors": ["Hal Roach"],
        "writers": ["Frank Terry (story)", "H.M. Walker (titles)"],
        "awards": {"wins": 0, "nominations": 1, "text": "1 nomination."},
        "lastupdated": "2015-08-11 00:35:33.717000000",
        "year": 1920,
        "imdb": {"rating": 7, "votes": 646, "id": 11293},
        "countries": ["USA"],
        "type": "movie",
        "tomatoes": {
          "viewer": {"rating": 3.4, "numReviews": 30, "meter": 70},
          "lastUpdated": "2015-06-27T19:17:10.000Z",
        },
      }
    }
  )


class UpdateMovie(BaseModel):
  """Schema to update a movie."""

  title: str | None = None
  num_mflix_comments: int | None = None
  lastupdated: str = Field(default_factory=lambda: str(datetime.now(UTC)))
  countries: list[str] | None = None


class Movies(BaseModel):
  """Schema to represent a list of movies."""

  movies: list[Movie]
  count: int = 0

  @model_validator(mode="after")
  def count_movies(self) -> Self:
    """Set self.count attr based on length of self.movies attr."""
    self.count = len(self.movies)
    return self


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
  """Init and close the mongo db client on app startup/shutdown."""
  mongo = AsyncIOMotorClient(MONGODB_URL)
  # we redeclare 'app.state.db' object during testing
  if not hasattr(app.state, "db"):
    app.state.db = mongo.get_database(DB_NAME)
  await init_beanie(app.state.db, document_models=[Movie], skip_indexes=True)
  yield
  mongo.close()


app = FastAPI(lifespan=lifespan)


async def get_movies_db(request: Request) -> "AsyncIOMotorDatabase":
  """Return state db object initialized in the app lifespan."""
  return request.app.state.db


@app.get("/ping/")
async def ping(
  db: Annotated["AsyncIOMotorDatabase", Depends(get_movies_db)],
) -> dict[str, bool]:
  """Ping connection with MongoDB server."""
  return await db.command("ping")


@app.get(
  "/movies/{id_}/",
  response_model_by_alias=False,  # replaces _id with id
)
async def get_movie(id_: PydanticObjectId) -> Movie:
  """Get a single movie."""
  if movie := await Movie.get(id_):
    return movie
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"Movie {id_} not found")


@app.get(
  "/movies/",
  response_model_by_alias=False,  # replaces _id with id
)
async def get_movies(pagination: Annotated[Pagination, Depends()]) -> Movies:
  """Get a list of movies."""
  movies = await Movie.find_all(
    skip=pagination.skip, limit=pagination.limit, sort=[("released", ASCENDING)]
  ).to_list()
  return Movies(movies=movies)


@app.delete("/movies/{id_}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(id_: PydanticObjectId) -> Response:
  """Delete a movie."""
  if movie := await Movie.get(id_):
    await movie.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"Movie {id_} not found")


@app.post(
  "/movies/",
  status_code=status.HTTP_201_CREATED,
  response_model_by_alias=False,  # replaces _id with id
)
async def create(movie: Movie) -> Movie:
  """Create a movie."""
  return await movie.create()


@app.put(
  "/movies/{id_}/",
  response_model_by_alias=False,  # replaces _id with id
)
async def update_movie(id_: PydanticObjectId, movie_info: UpdateMovie) -> Movie:
  """Update a movie."""
  updated_movie_info = {
    k: v for k, v in movie_info.model_dump().items() if v is not None
  }
  if len(updated_movie_info) < 1:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
  if movie := await Movie.get(id_):
    return await movie.update({"$set": updated_movie_info})
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"Movie {id_} not found")
