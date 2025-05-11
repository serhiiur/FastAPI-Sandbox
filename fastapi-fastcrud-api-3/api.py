from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import FastCRUD
from pydantic import BaseModel, EmailStr
from sqlmodel import SQLModel, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AS
from sqlalchemy.orm import sessionmaker


MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255

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
  _: Request,
  e: IntegrityError
) -> JSONResponse:
  """Database. Integrity error handler"""
  # log error
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
  _: Request,
  e: Exception
) -> JSONResponse:
  """Error handler for all uncaught exceptions"""
  # log error
  msg = {"error": "Internal server error. Try again later"}
  return JSONResponse(msg, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator:
  """Create the database objects on the application startup"""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield


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
)
async def get_user(id: str, db: Annotated[AS, Depends(get_session)]):
  if user := await user_crud.get(db, id=id):
    return user
  raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")


@app.get(
  "/users",
  description="Get information about users from the database",
  response_model=UsersResponse,
)
async def get_users(
  filters: Annotated[UserSelectFilters, Depends()],
  db: Annotated[AS, Depends(get_session)]
) -> UsersResponse:
  return await user_crud.get_multi(db, **filters.model_dump())


@app.post(
  "/users",
  description="Add a new user to the database",
  response_model=User,
  status_code=status.HTTP_201_CREATED
)
async def create_user(
  user: CreateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.create(db, user)


@app.delete(
  "/users/{id}",
  description="Delete a user from the database",
  status_code=status.HTTP_204_NO_CONTENT
)
async def delete_user(
  id: str,
  db: Annotated[AS, Depends(get_session)]
) -> Response:
  await user_crud.delete(db, id=id)
  return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.patch(
  "/users/{id}",
  description="Update existing user in the database",
  response_model=User,
)
async def update_user(
  id: str,
  user: UpdateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.update(
    db,
    object=user.model_dump(exclude_defaults=True),
    id=id,
    schema_to_select=User,
    return_as_model=True,
  )
