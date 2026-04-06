import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache, partial
from typing import Annotated, TypedDict

import jwt
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings


class FastApiKwargs(TypedDict):
  """Kwargs for FastAPI application."""

  title: str
  description: str
  debug: bool


class Settings(BaseSettings):
  """Application settings."""

  title: str = "JWT API"
  description: str = "OAuth2 with Password (and hashing), Bearer with JWT tokens."
  debug: bool = False
  secret_key: SecretStr = SecretStr(secrets.token_urlsafe(32))
  algorithm: str = "HS256"
  token_expire_minutes: timedelta = timedelta(minutes=30)
  token_type: str = "bearer"

  @property
  def fastapi_kwargs(self) -> FastApiKwargs:
    """Kwargs for FastAPI application."""
    return FastApiKwargs(
      title=self.title,
      description=self.description,
      debug=self.debug,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()
password_hash = PasswordHash.recommended()


class Token(BaseModel):
  """Schema to represent info about auth token."""

  access_token: str
  token_type: str = settings.token_type


class User(BaseModel):
  """Schema to represent public info about user."""

  username: str
  email: str | None = None
  full_name: str | None = None
  disabled: bool | None = None


class DbUser(User):
  """Schema to represent info about user from the database."""

  hashed_password: SecretStr


class TokenClaims(BaseModel):
  """Schema to represent JWT claims."""

  sub: str
  exp: datetime = Field(
    default_factory=lambda: datetime.now(UTC) + settings.token_expire_minutes
  )


class InactiveUserError(Exception):
  """Raise when an inactive user attempts to access a protected route."""


class InvalidCredentialsError(Exception):
  """Raise when the provided username or password does not match stored credentials."""


# Shortcut for JSONResponse containing appropriate WWW-Authenticate header for invalid tokens
BadJSONResponse = partial(
  JSONResponse, headers={"WWW-Authenticate": settings.token_type}
)


async def inactive_user_error_handler(
  _request: Request,
  _exc: InactiveUserError,
) -> JSONResponse:
  """Error handler for 'InactiveUserError' exception."""
  return BadJSONResponse(
    status_code=status.HTTP_400_BAD_REQUEST,
    content={"detail": "Inactive user"},
  )


async def invalid_credentials_handler(
  _request: Request,
  _exc: InvalidCredentialsError,
) -> JSONResponse:
  """Error handler for 'InvalidCredentialsError' exception."""
  return BadJSONResponse(
    status_code=status.HTTP_401_UNAUTHORIZED,
    content={"detail": "Incorrect username or password"},
  )


async def invalid_token_handler(
  _request: Request,
  _exc: InvalidTokenError,
) -> JSONResponse:
  """Error handler for 'InvalidTokenError' exception."""
  return BadJSONResponse(
    status_code=status.HTTP_401_UNAUTHORIZED,
    content={"detail": "Invalid authentication credentials"},
  )


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

app = FastAPI(
  **settings.fastapi_kwargs,
  exception_handlers={
    InvalidCredentialsError: invalid_credentials_handler,
    InvalidTokenError: invalid_token_handler,
    InactiveUserError: inactive_user_error_handler,
  },
)

# Custom data type to specify fake database structure
type DbType = dict[str, DbUser]

# Fake database
db: DbType = {
  "joedoe": DbUser(
    username="joedoe",
    full_name="Joe Doe",
    email="jd@example.com",
    hashed_password=SecretStr(password_hash.hash("joedoe")),
    disabled=False,
  ),
  "sarahdoe": DbUser(
    username="sarahdoe",
    full_name="Sarah Doe",
    email="sd@example.com",
    hashed_password=SecretStr(password_hash.hash("sarahdoe")),
    disabled=True,
  ),
}


def verify_password(plain_password: str, hashed_password: SecretStr) -> bool:
  """Verify if a password matches a given hash."""
  return password_hash.verify(plain_password, hashed_password.get_secret_value())


def get_user(db: DbType, username: str) -> DbUser | None:
  """Return info about user from the database, or None if the user doesn't exist."""
  return db.get(username)


def authenticate_user(db: DbType, username: str, password: str) -> DbUser | None:
  """Return info about user from the database if the credentials are valid, otherwise None."""
  user = get_user(db, username)
  if not user or not verify_password(password, user.hashed_password):
    return None
  return user


def generate_token(username: str) -> str:
  """Generate signed JWT."""
  claims = TokenClaims(sub=username).model_dump()
  return jwt.encode(
    claims,
    key=settings.secret_key.get_secret_value(),
    algorithm=settings.algorithm,
  )


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> DbUser:
  """Return info about user from the database, retrieved from the JWT claims."""
  claims = jwt.decode(
    token,
    key=settings.secret_key.get_secret_value(),
    algorithms=[settings.algorithm],
  )
  username = claims.get("sub")
  if username and (user := get_user(db, username)):
    return user
  raise InvalidCredentialsError


async def get_current_active_user(
  current_user: Annotated[User, Depends(get_current_user)],
) -> User:
  """Return info about current user if one is active."""
  if current_user.disabled:
    raise InactiveUserError
  return current_user


@app.post("/login", include_in_schema=False)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
  """Authenticate the user."""
  if user := authenticate_user(db, form.username, form.password):
    return Token(access_token=generate_token(user.username))
  raise InvalidCredentialsError


@app.get("/users/me/")
async def profile(
  current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
  """Return info about current user."""
  return current_user


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("api:app", reload=settings.debug)
