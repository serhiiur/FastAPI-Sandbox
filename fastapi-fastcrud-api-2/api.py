
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import crud_router
from fastcrud.exceptions.http_exceptions import DuplicateValueException
from pydantic import EmailStr
from sqlmodel import SQLModel, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255

DATABASE_URL = "sqlite+aiosqlite:///./test.db"
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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


async def get_session() -> AsyncIterator[AsyncSession]:
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
  e: IntegrityError | DuplicateValueException
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


user_router = crud_router(
  session=get_session,
  model=User,
  create_schema=CreateUser,
  update_schema=UpdateUser,
  path="/users",
  tags=["users"],
)
app = FastAPI(lifespan=lifespan)
app.include_router(user_router)
app.add_exception_handler(NoResultFound, db_not_found_error_handler)
app.add_exception_handler(IntegrityError, db_integrity_error_handler)
app.add_exception_handler(DuplicateValueException, db_integrity_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)


@app.get(
  "/health",
  description="Simple health-check endpoint",
)
async def health() -> dict[str, str]:
  return {"response": "ok"}
