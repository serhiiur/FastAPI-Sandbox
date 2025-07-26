import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Self, TypedDict

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import (
  BaseModel,
  BeforeValidator,
  ConfigDict,
  EmailStr,
  Field,
  model_validator,
)
from pymongo import ASCENDING, ReturnDocument

if TYPE_CHECKING:
  from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase


load_dotenv()


COLLECTION_NAME = "users"
DB_NAME = "sample_mflix"
MONGODB_URL = os.getenv("MONGODB_URL")


class Pagination(BaseModel):
  """Schema for pagination."""

  limit: int = Field(10, gt=0)
  skip: int = Field(0, ge=0)


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

  NOTE: id Represents an ObjectId field in the database.
        It will be represented as a `str` on the model,
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
    """Set self.count attribute based on length of self.users attribute."""
    self.count = len(self.users)
    return self


class AppState(TypedDict):
  """Data structure to represent state of the main app."""

  db: "AsyncIOMotorDatabase"
  collection: "AsyncIOMotorCollection"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init and close the mongo db client on app startup/shutdown."""
  mongo = AsyncIOMotorClient(MONGODB_URL)
  db = mongo.get_database(DB_NAME)
  collection = db.get_collection(COLLECTION_NAME)
  # app.state.db = db
  # app.state.collection = collection
  # yield
  yield AppState(db=db, collection=collection)
  mongo.close()


app = FastAPI(lifespan=lifespan)


async def get_users_db(request: Request) -> "AsyncIOMotorDatabase":
  """Dependency to get initialized in the lifespan 'db' object."""
  # return request.app.state.db
  return request.state.db


async def get_users_collection(request: Request) -> "AsyncIOMotorCollection":
  """Dependency to get initialized in the lifespan 'collection' object."""
  # return request.app.state.collection
  return request.state.collection


@app.get(
  "/ping/",
  description="Ping connection with MongoDB server",
  responses={
    200: {
      "description": "Ping response from the server",
      "content": {"application/json": {"example": {"ok": True}}},
    }
  },
)
async def ping(
  db: Annotated["AsyncIOMotorDatabase", Depends(get_users_db)],
) -> dict[str, bool]:
  """Ping connection with MongoDB server."""
  return await db.command("ping")


@app.get("/users/", response_model_by_alias=False)
async def get_users(
  pagination: Annotated[Pagination, Depends()],
  collection: Annotated["AsyncIOMotorCollection", Depends(get_users_collection)],
) -> Users:
  """List of all users."""
  users = (
    await collection.find()
    .limit(pagination.limit)
    .skip(pagination.skip)
    .sort("name", ASCENDING)
    .to_list()
  )
  return Users(users=users)


@app.get("/users/{id_}/", response_model_by_alias=False)
async def get_user(
  id_: str,
  collection: Annotated["AsyncIOMotorCollection", Depends(get_users_collection)],
) -> User:
  """Get a single user."""
  if user := await collection.find_one({"_id": ObjectId(id_)}):
    return user
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {id_} not found")


@app.post(
  "/users/",
  status_code=status.HTTP_201_CREATED,
  response_model_by_alias=False,
)
async def create(
  user: CreateUser,
  collection: Annotated["AsyncIOMotorCollection", Depends(get_users_collection)],
) -> User:
  """Add a new user."""
  new_user = await collection.insert_one(user.model_dump())
  return await collection.find_one({"_id": new_user.inserted_id})


@app.delete("/users/{id_}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
  id_: str,
  collection: Annotated["AsyncIOMotorCollection", Depends(get_users_collection)],
) -> Response:
  """Delete a user."""
  user = await collection.delete_one({"_id": ObjectId(id_)})
  if user.deleted_count:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {id_} not found")


@app.put("/users/{id_}/", response_model_by_alias=False)
async def update_user(
  id_: str,
  user: UpdateUser,
  collection: Annotated["AsyncIOMotorCollection", Depends(get_users_collection)],
) -> User:
  """Update a user."""
  if user := {k: v for k, v in user.model_dump().items() if v is not None}:
    update_res = await collection.find_one_and_update(
      {"_id": ObjectId(id_)}, {"$set": user}, return_document=ReturnDocument.AFTER
    )
    if update_res:
      return update_res
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {id_} not found")

  # The update is empty, but we should still return the matching document
  if existing_user := await collection.find_one({"_id": id_}):
    return existing_user
  raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {id_} not found")
