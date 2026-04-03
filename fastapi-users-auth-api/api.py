import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, TypedDict, cast
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi_users import (
  BaseUserManager,
  FastAPIUsers,
  InvalidPasswordException,
  UUIDIDMixin,
)
from fastapi_users.authentication import (
  AuthenticationBackend,
  BearerTransport,
  JWTStrategy,
)
from fastapi_users.db import (
  BaseUserDatabase,
  SQLAlchemyBaseUserTableUUID,
  SQLAlchemyUserDatabase,
)
from fastapi_users.jwt import SecretType
from fastapi_users.password import PasswordHelperProtocol
from fastapi_users.schemas import BaseUser, BaseUserCreate, BaseUserUpdate
from pydantic_settings import BaseSettings
from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
  from logging import Logger


class FastAPIKwargs(TypedDict):
  """Kwargs for FastAPI app."""

  title: str
  description: str
  version: str
  debug: bool


class LoggingKwargs(TypedDict):
  """Kwargs for logger config."""

  level: int
  format: str
  datefmt: str


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "FastAPI-Users API"
  description: str = "API for managing users authentication using FastAPI-Users library"
  version: str = "0.0.1"
  debug: bool = True

  # Logging settings
  log_name: str = __name__
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"
  log_datefmt: str = "%Y-%m-%d %H:%M:%S"

  # Database settings
  database_url: str = "sqlite+aiosqlite:///./test.db"
  test_database_url: str = "sqlite+aiosqlite:///:memory:"

  # Passwords settings
  min_password_length: int = 5
  max_password_length: int = 50

  # FastAPI Users settings
  secret_key: SecretType = ""

  @property
  def fastapi_kwargs(self) -> FastAPIKwargs:
    """Kwargs for FastAPI app."""
    return FastAPIKwargs(
      title=self.title,
      description=self.description,
      version=self.version,
      debug=self.debug,
    )

  @property
  def logging_kwargs(self) -> LoggingKwargs:
    """Kwargs for logger config."""
    return LoggingKwargs(
      level=self.log_level,
      format=self.log_format,
      datefmt=self.log_datefmt,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


def configure_logging(name: str, options: LoggingKwargs | None = None) -> "Logger":
  """Configure app logging and return logger object."""
  if options is not None:
    logging.basicConfig(**options)
  return logging.getLogger(name)


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
  """Base declarative database class."""

  type_annotation_map: ClassVar[dict[type, Any]] = {
    datetime: DateTime(timezone=True),
    str: String(255),
  }


class User(SQLAlchemyBaseUserTableUUID, Base):
  """Database model to represent a user in the database."""


class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
  """Class for managing authentication of users.

  See: https://fastapi-users.github.io/fastapi-users/latest/configuration/user-manager/#customize-attributes-and-methods
  """

  reset_password_token_secret: SecretType = settings.secret_key
  verification_token_secret: SecretType = settings.secret_key

  def __init__(
    self,
    user_db: BaseUserDatabase[User, UUID],
    password_helper: PasswordHelperProtocol | None = None,
    *,
    logger: "Logger | None" = None,
  ) -> None:
    super().__init__(user_db, password_helper)
    self.logger = logger or logging.getLogger(__name__)

  async def on_after_register(
    self,
    user: User,
    request: Request | None = None,
  ) -> None:
    """Perform logic after successful user registration.

    Typically, you'll want to send a welcome email.
    """
    self.logger.info("User %s has registered.", user.id)

  async def validate_password(
    self,
    password: str,
    user: User | BaseUserCreate,
  ) -> None:
    """Validate the password."""
    min_password_length = settings.min_password_length
    max_password_length = settings.max_password_length
    if not (min_password_length <= len(password) <= max_password_length):
      raise InvalidPasswordException(
        reason=f"Password must contain {min_password_length} - {max_password_length} characters"
      )

  async def on_after_update(
    self,
    user: User,
    update_dict: dict[str, Any],
    request: Request | None = None,
  ) -> None:
    """Perform logic after successful user update."""
    self.logger.info("User %s has been updated with %s.", user.id, update_dict)

  async def on_after_login(
    self,
    user: User,
    request: Request | None = None,
    response: Response | None = None,
  ) -> None:
    """Perform logic after a successful user login."""
    self.logger.info("User %s logged in.", user.id)

  async def on_after_forgot_password(
    self,
    user: User,
    token: str,
    request: Request | None = None,
  ) -> None:
    """Perform logic after successful forgot password request.

    Typically, you'll want to send an e-mail with the link (and the token)
    that allows the user to reset their password.
    """
    self.logger.info("User %s has forgot the password. Reset token: %s", user.id, token)

  async def on_after_reset_password(
    self,
    user: User,
    request: Request | None = None,
  ) -> None:
    """Perform logic after successful password reset.

    For example, you may want to send an email to the concerned user to warn one
    that their password has been changed and that they should take action if they
    think they have been hacked.
    """
    self.logger.info("User %s has reset the password.", user.id)

  async def on_after_delete(
    self,
    user: User,
    request: Request | None = None,
  ) -> None:
    """Perform logic after user delete."""
    self.logger.info("User %s is successfully deleted", user.id)


async def get_jwt_strategy() -> JWTStrategy[User, UUID]:
  """Return instance of JWTStrategy class."""
  return JWTStrategy(settings.secret_key, lifetime_seconds=3600)


async def get_logger(request: Request) -> "Logger":
  """Return logger object, initialized in the lifespan function."""
  return cast("Logger", request.state.logger)


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session object to be used as a dependency."""
  async with async_session() as session:
    yield session


async def get_user_db(
  session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[SQLAlchemyUserDatabase[User, UUID]]:
  """Yield a database adapter for SQLAlchemy's session object and User model."""
  yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
  user_db: Annotated[SQLAlchemyUserDatabase[User, UUID], Depends(get_user_db)],
  logger: Annotated["Logger", Depends(get_logger)],
) -> AsyncIterator[UserManager]:
  """Yield instance of UserManager class for managing authentication of users."""
  yield UserManager(user_db, logger=logger)


async def unexpected_error_handler(
  request: Request,
  e: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger = await get_logger(request)
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Service is temporarily unavailable"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


class AppState(TypedDict):
  """Data structure to represent state of the main application."""

  logger: "Logger"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
  """Run database migrations and define application state objects."""
  logger = getattr(
    app.state,
    "logger",
    configure_logging(settings.log_name, settings.logging_kwargs),
  )
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield AppState(logger=logger)
  await engine.dispose()


bearer_transport = BearerTransport(tokenUrl="/jwt/auth/login")
auth_backend = AuthenticationBackend(
  name="jwt",
  transport=bearer_transport,
  get_strategy=get_jwt_strategy,
)
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, auth_backends=[auth_backend])
current_active_user = fastapi_users.current_user(active=True)

app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={Exception: unexpected_error_handler},
)
app.include_router(
  fastapi_users.get_auth_router(auth_backend),
  prefix="/jwt/auth",
  tags=["auth"],
)
app.include_router(
  fastapi_users.get_register_router(BaseUser, BaseUserCreate),
  prefix="/auth",
  tags=["auth"],
)
app.include_router(
  fastapi_users.get_reset_password_router(),
  prefix="/auth",
  tags=["auth"],
)
app.include_router(
  fastapi_users.get_verify_router(BaseUser),
  prefix="/auth",
  tags=["auth"],
)
app.include_router(
  fastapi_users.get_users_router(BaseUser, BaseUserUpdate),
  prefix="/users",
  tags=["users"],
)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT, tags=["meta"])
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


@app.get("/greet")
async def greet(user: Annotated[User, Depends(current_active_user)]) -> dict[str, str]:
  """Welcome the current authenticated user."""
  return {"message": f"Hi, {user.email}"}
