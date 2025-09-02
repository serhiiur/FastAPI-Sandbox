from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, Self, TypedDict

from beanie import Document, PydanticObjectId, SortDirection, init_beanie
from fastapi import (
  APIRouter,
  Depends,
  FastAPI,
  HTTPException,
  Query,
  Request,
  Response,
  status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo.asynchronous.mongo_client import AsyncMongoClient

if TYPE_CHECKING:
  from pymongo.asynchronous.database import AsyncDatabase
  from pymongo.typings import _DocumentType


class FastAPIKwargs(TypedDict):
  """Kwargs for FastAPI app."""

  title: str
  description: str
  version: str
  debug: bool


class Settings(BaseSettings):
  """API settings."""

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

  # FastAPI settings
  title: str = "Movies Management API"
  description: str = "CRUD API to manage movies in MongoDB"
  version: str = "0.0.1"
  debug: bool = True

  # MongoDB settings
  mongodb_url: str = ""
  db_name: str = "sample_mflix"
  collection_name: str = "movies"
  # mock database used in testing
  test_db_name: str = "test_sample_mflix"

  @property
  def fastapi_kwargs(self) -> FastAPIKwargs:
    """Kwargs for FastAPI app."""
    return FastAPIKwargs(
      title=self.title,
      description=self.description,
      version=self.version,
      debug=self.debug,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


class MovieNotFound(Exception):  # noqa: N818
  """Custom exception to be raised when a movie is not found."""

  __slots__ = ("message",)

  default_message: str = "Movie not found"

  def __init__(self, message: str | None = None) -> None:
    """Set error message."""
    self.message = message or self.default_message


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
  awards: MovieAwards
  lastupdated: str
  year: int
  imdb: MovieImdb
  countries: list[str]
  directors: list[str]
  type: str
  num_mflix_comments: int | None = None
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

  class Settings:
    name = settings.collection_name

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "_id": "573a1391f29313caabcd6d40",
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
    },
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


async def get_db(request: Request) -> "AsyncDatabase[Mapping[str, Any]]":
  """Return state db object initialized in the app lifespan."""
  return request.app.state.db


async def movie_not_found_error_handler(
  _: Request,
  e: MovieNotFound,
) -> JSONResponse:
  """Handle movie not found error."""
  client_message = {"error": e.message}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Init and close the mongo db client on app startup/shutdown."""
  mongo: AsyncMongoClient[Any] = AsyncMongoClient(settings.mongodb_url)
  # we redeclare 'app.state.db' object during testing
  if not hasattr(app.state, "db"):
    app.state.db = mongo.get_database(settings.db_name)
  await init_beanie(app.state.db, document_models=[Movie], skip_indexes=True)
  yield
  await mongo.close()


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={MovieNotFound: movie_not_found_error_handler},
)
router = APIRouter(prefix="/movies", tags=["movies"])


@app.get("/ping")
async def ping(
  db: Annotated["AsyncDatabase[_DocumentType]", Depends(get_db)],
) -> dict[str, bool]:
  """Ping connection with MongoDB server."""
  return await db.command("ping")


@router.get("/{movie_id}")
async def get_movie(movie_id: PydanticObjectId) -> Movie:
  """Get a single movie."""
  if movie := await Movie.get(movie_id):
    return movie
  raise MovieNotFound


@router.get("")
async def get_movies(
  limit: Annotated[int, Query(gt=0)] = 10,
  skip: Annotated[int, Query(ge=0)] = 0,
) -> Movies:
  """Get a list of movies."""
  sort = [("released", SortDirection.ASCENDING)]
  movies = await Movie.find_all(skip, limit, sort).to_list()
  return Movies(movies=movies)


@router.delete("/{movie_id}")
async def delete_movie(movie_id: PydanticObjectId) -> Response:
  """Delete a movie."""
  if movie := await Movie.get(movie_id):
    await movie.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
  raise MovieNotFound


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(movie: Movie) -> Movie:
  """Create a movie."""
  return await movie.create()


@router.patch("/{movie_id}")
async def update_movie(
  movie_id: PydanticObjectId,
  movie_info: UpdateMovie,
) -> Movie:
  """Update a movie."""
  updated_movie_info = {
    k: v for k, v in movie_info.model_dump().items() if v is not None
  }
  if len(updated_movie_info) < 1:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
  if movie := await Movie.get(movie_id):
    return await movie.update({"$set": updated_movie_info})
  raise MovieNotFound


app.include_router(router)
