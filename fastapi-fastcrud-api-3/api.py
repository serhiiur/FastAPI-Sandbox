from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging import getLogger
from typing import Any, Annotated, AsyncIterator, Literal, TYPE_CHECKING
from uuid import uuid4, UUID

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import FastCRUD
from pydantic import BaseModel, EmailStr
from sqlmodel import SQLModel, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AS
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
  from logging import Logger


# Settings
MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255
LOGGER_NAME = "uvicorn.error"

# Database
DATABASE_URL = "sqlite+aiosqlite:///./test.db"
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AS, expire_on_commit=False)

# lambda function to return current datetime
dt_now = lambda: datetime.now(timezone.utc)


class Base(SQLModel):
  """Base database model"""
  id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
  created_at: datetime = Field(default_factory=dt_now)
  updated_at: datetime = Field(
    default_factory=dt_now,
    sa_column_kwargs={"onupdate": dt_now}
  )


class CreateUser(SQLModel):
  """Schema to create a user"""
  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH

  )
  email: EmailStr = Field(
    description="Email of the user",
    unique=True,
    index=True
  )


class User(Base, CreateUser, table=True):
  """Database model to represent a user"""


class UpdateUser(SQLModel):
  """Schema to update a user"""
  name: str | None = Field(
    default=None,
    description="New name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH
  )
  email: EmailStr | None = Field(
    default=None,
    description="New email of the user",
  )


class UserSelectFilters(BaseModel):
  """Schema used to select users frm the database using filters"""
  limit: int = Field(
    default=10,
    description="Total number of records to select",
    gt=0,
  )
  offset: int = Field(
    default=0,
    description="Index to start selecting records from",
    ge=0,
  )
  sort_columns: Literal["name", "created_at", "updated_at"] | None = Field(
    default=None,
    description="Field to sort records by",
  )
  sort_orders: Literal["asc", "desc"] | None = Field(
    default=None,
    description="Order to sort records by"
  )


responses = {
  404: {
    "description": "User not found in the database",
    "content": {
      "application/json": {
        "example": {
          "error": "User not found"
        }
      }
    }
  },
  409: {
    "description": "User already exists in the database",
    "content": {
      "application/json": {
        "example": {
          "error": "User already exists"
        }
      }
    }
  },
  422: {
    "description": "Data validation error",
    "content": {
      "application/json": {
        "example": {
          "error": "Value is not a valid email address"
        }
      }
    }
  },
}

RawUserResponse = dict[str, Any]


class UsersResponse(BaseModel):
  """Schema used to display multiple users from the database"""
  data: list[User] = Field(
    description="List of users based on the provided filters"
  )
  total_count: int = Field(
    description="Total users in the database"
  )


async def get_session() -> AsyncIterator[AS]:
  """Yield a database session to be used as a dependency"""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  _: Request,
  e: NoResultFound
) -> JSONResponse:
  """Database. Not found error handler"""
  # log error
  msg = {"error": str(e)}
  return JSONResponse(msg, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  request: Request,
  e: IntegrityError
) -> JSONResponse:
  """Database. Integrity error handler"""
  logger: "Logger" = getattr(request.app.state, "logger")  # type: ignore
  logger.error(f"Database Integrity Error: {e}")
  msg = {"error": "User already exists"}
  return JSONResponse(msg, status.HTTP_409_CONFLICT)


async def validation_error_handler(
  _: Request,
  e: RequestValidationError
) -> JSONResponse:
  """Pydantic validation error handler"""
  msg = {"error": e.errors()[0]["msg"]}
  return JSONResponse(msg, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def unexpected_error_handler(
  request: Request,
  e: Exception
) -> JSONResponse:
  """Error handler for all uncaught exceptions"""
  logger: "Logger" = getattr(request.app.state, "logger")  # type: ignore
  logger.error(f"Internal Server Error: {e}")
  msg = {"error": "Internal server error. Try again later"}
  return JSONResponse(msg, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator:
  """Create the database objects on the application startup"""
  app.state.logger = getLogger(LOGGER_NAME)  # type: ignore
  # Create database objects on the application startup
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(NoResultFound, db_not_found_error_handler)
app.add_exception_handler(IntegrityError, db_integrity_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)

user_crud = FastCRUD(User)


@app.get(
  "/health",
  description="Simple health-check endpoint",
)
async def health() -> dict[str, str]:
  return {"response": "ok"}


@app.get(
  "/users/{id}",
  description="Get information about user from the database",
  response_model=User,
  responses={404: responses[404], 422: responses[422]}
)
async def get_user(
  id: UUID,
  db: Annotated[AS, Depends(get_session)]
) -> RawUserResponse:
  if user := await user_crud.get(db, id=str(id)):
    return user
  raise NoResultFound("User not found")


@app.get(
  "/users",
  description="Get information about users from the database",
  response_model=UsersResponse,
  responses={404: responses[404], 422: responses[422]}
)
async def get_users(
  filters: Annotated[UserSelectFilters, Depends()],
  db: Annotated[AS, Depends(get_session)]
) -> dict[str, list[RawUserResponse] | int]:
  return await user_crud.get_multi(db, **filters.model_dump())


@app.post(
  "/users",
  description="Add a new user to the database",
  response_model=User,
  status_code=status.HTTP_201_CREATED,
  responses={409: responses[409], 422: responses[422]}
)
async def create_user(
  user: CreateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.create(db, user)


@app.delete(
  "/users/{id}",
  description="Delete a user from the database",
  status_code=status.HTTP_204_NO_CONTENT,
  responses={404: responses[404], 422: responses[422]}
)
async def delete_user(
  id: UUID,
  db: Annotated[AS, Depends(get_session)]
) -> None:
  return await user_crud.delete(db, id=str(id))


@app.patch(
  "/users/{id}",
  description="Update existing user in the database",
  response_model=User,
  responses={**responses}
)
async def update_user(
  id: UUID,
  user: UpdateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.update(
    db,
    object=user.model_dump(exclude_defaults=True),
    id=str(id),
    schema_to_select=User,
    return_as_model=True,
  )
