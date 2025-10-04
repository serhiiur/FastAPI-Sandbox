from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, Self, TypeAlias, TypedDict

from bson import ObjectId
from fastapi import (
  APIRouter,
  Depends,
  FastAPI,
  Query,
  Request,
  status,
)
from fastapi.responses import JSONResponse
from pydantic import (
  BaseModel,
  BeforeValidator,
  ConfigDict,
  EmailStr,
  Field,
  model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import ASCENDING, ReturnDocument
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

if TYPE_CHECKING:
  from pymongo.asynchronous.collection import AsyncCollection
  from pymongo.asynchronous.database import AsyncDatabase


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
  title: str = "Users Management API"
  description: str = "CRUD API to manage users in MongoDB"
  version: str = "0.0.1"
  debug: bool = True

  # MongoDB settings
  mongodb_url: str = ""
  db_name: str = "sample_mflix"
  collection_name: str = "users"
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


class UserNotFoundError(Exception):
  """Custom exception to be raised when a user is not found."""

  __slots__ = ("message",)

  default_message: str = "User not found"

  def __init__(self, message: str | None = None) -> None:
    """Set error message."""
    self.message = message or self.default_message


class NothingToUpdate(Exception):  # noqa: N818
  """Custom exception to be raised when there's noting to update."""

  __slots__ = ("message",)

  default_message: str = "Nothing to update"

  def __init__(self, message: str | None = None) -> None:
    """Set error message."""
    self.message = message or self.default_message


class CreateUser(BaseModel):
  """Schema to create a new user."""

  name: str
  email: EmailStr
  password: str


class UpdateUser(BaseModel):
  """Schema to update a user in the database."""

  name: str | None = None
  email: EmailStr | None = None
  password: str | None = None


class User(CreateUser):
  """Schema to represent a user in the database.

  NOTE: id is actually an ObjectId field in the document,
        but in the model it will be interpreted as a str,
        so that it can be serialized to JSON.
  """

  id: Annotated[str, BeforeValidator(str)] = Field(alias="_id")
  model_config = ConfigDict(
    populate_by_name=True,
    arbitrary_types_allowed=True,
    json_schema_extra={
      "example": {
        "id": "2cb8f4911203787d903b1b76",
        "name": "Joe Doe",
        "email": "joedoe@example.com",
        "password": "qwerty12345",
      }
    },
  )


class Users(BaseModel):
  """Schema to represent a list of users from the database."""

  users: list[User]
  count: int = 0

  @model_validator(mode="after")
  def count_users(self) -> Self:
    """Set self.count attribute based on length of self.users."""
    self.count = len(self.users)
    return self


async def user_not_found_error_handler(
  _: Request,
  e: UserNotFoundError,
) -> JSONResponse:
  """Handle user not found error."""
  client_message = {"error": e.message}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def user_already_exists_error_handler(
  _: Request,
  e: DuplicateKeyError,  # noqa: ARG001
) -> JSONResponse:
  """Handle user not found error."""
  client_message = {"error": "User already exists"}
  return JSONResponse(client_message, status.HTTP_409_CONFLICT)


async def user_nothing_to_update_error_handler(
  _: Request,
  e: NothingToUpdate,
) -> JSONResponse:
  """Handle nothing to update error."""
  client_message = {"error": e.message}
  return JSONResponse(client_message, status.HTTP_400_BAD_REQUEST)


# custom type aliases
type DocumentT = Mapping[str, Any]
type DatabaseT = "AsyncDatabase[DocumentT]"
type CollectionT = "AsyncCollection[DocumentT]"


class AppState(TypedDict):
  """Data structure to represent state of the main app."""

  db: DatabaseT
  collection: CollectionT


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init and close the mongo db client on app startup/shutdown."""
  mongo: AsyncMongoClient[Any] = AsyncMongoClient(settings.mongodb_url)
  db = mongo.get_database(settings.db_name)
  collection = db.get_collection(settings.collection_name)
  yield AppState(db=db, collection=collection)
  await mongo.close()


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    NothingToUpdate: user_nothing_to_update_error_handler,
    UserNotFoundError: user_not_found_error_handler,
    DuplicateKeyError: user_already_exists_error_handler,
  },
)
router = APIRouter(prefix="/users", tags=["users"])


async def get_users_db(request: Request) -> DatabaseT:
  """Dependency to get initialized in the lifespan 'db' object."""
  return request.state.db


async def get_users_collection(request: Request) -> CollectionT:
  """Dependency to get initialized in the lifespan 'collection' object."""
  return request.state.collection


@app.get("/ping")
async def ping(
  db: Annotated[DatabaseT, Depends(get_users_db)],
) -> dict[str, bool]:
  """Ping connection with MongoDB server."""
  return await db.command("ping")


Collection: TypeAlias = Annotated[CollectionT, Depends(get_users_collection)]


@router.get(
  "",
  response_model=Users,
  response_model_by_alias=False,
)
async def get_users(
  collection: Collection,
  limit: Annotated[int, Query(gt=0)] = 10,
  skip: Annotated[int, Query(ge=0)] = 0,
) -> DocumentT:
  """List of users."""
  if users := (
    await collection.find().limit(limit).skip(skip).sort("name", ASCENDING).to_list()
  ):
    return {"users": users}
  raise UserNotFoundError


@router.get(
  "/{user_id}",
  response_model=User,
  response_model_by_alias=False,
)
async def get_user(user_id: str, collection: Collection) -> DocumentT:
  """Get a single user."""
  if user := await collection.find_one({"_id": ObjectId(user_id)}):
    return user
  raise UserNotFoundError


@router.post(
  "",
  status_code=status.HTTP_201_CREATED,
  response_model=User,
  response_model_by_alias=False,
)
async def create_user(user: CreateUser, collection: Collection) -> DocumentT:
  """Add a new user."""
  user_data = user.model_dump()
  await collection.insert_one(user_data)
  return user_data


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, collection: Collection) -> None:
  """Delete a user."""
  user = await collection.delete_one({"_id": ObjectId(user_id)})
  if user.deleted_count:
    return
  raise UserNotFoundError


@router.patch(
  "/{user_id}",
  response_model=User,
  response_model_by_alias=False,
)
async def update_user(
  user_id: str,
  user: UpdateUser,
  collection: Collection,
) -> DocumentT:
  """Update a user."""
  user_data = user.model_dump(exclude_none=True)
  if not user_data:
    raise NothingToUpdate
  if update_res := await collection.find_one_and_update(
    {"_id": ObjectId(user_id)},
    {"$set": user_data},
    return_document=ReturnDocument.AFTER,
  ):
    return update_res
  raise UserNotFoundError


app.include_router(router)
