from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import crud_router
from fastcrud.exceptions.http_exceptions import DuplicateValueException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import DateTime, func, String
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AE
from sqlalchemy.orm import (
  DeclarativeBase,
  mapped_column,
  Mapped,
  sessionmaker
)


MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255
MAX_USER_EMAIL_LENGTH = 255
USER_ID_LENGTH = 36

DATABASE_URL = "sqlite+aiosqlite:///./test.db"
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AE, expire_on_commit=False)


class Base(DeclarativeBase):
  """Base declarative database class"""


class User(Base):
  """Database model to represent a user"""
  __tablename__ = "users"
  id: Mapped[str] = mapped_column(
    String(USER_ID_LENGTH),
    primary_key=True,
    default=lambda: str(uuid4()),
  )
  name: Mapped[str] = mapped_column(String(MAX_USER_NAME_LENGTH), nullable=False)
  email: Mapped[str] = mapped_column(
    String(MAX_USER_EMAIL_LENGTH),
    nullable=False,
    unique=True,
    index=True
  )
  created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now()
  )
  updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now()
  )


class CreateUser(BaseModel):
  """Schema to create a user"""
  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH

  )
  email: EmailStr = Field(description="Email of the user")


class UpdateUser(BaseModel):
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


async def get_session() -> AsyncIterator[AE]:
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


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(NoResultFound, db_not_found_error_handler)
app.add_exception_handler(IntegrityError, db_integrity_error_handler)
app.add_exception_handler(DuplicateValueException, db_integrity_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)

user_router = crud_router(
  session=get_session,
  model=User,
  create_schema=CreateUser,
  update_schema=UpdateUser,
  path="/users",
  tags=["users"],
)
app.include_router(user_router)


@app.get(
  "/health",
  description="Simple health-check endpoint",
)
async def health() -> dict[str, str]:
  return {"response": "ok"}
