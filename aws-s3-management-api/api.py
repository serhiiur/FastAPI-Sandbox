import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import (
  TYPE_CHECKING,
  Annotated,
  Any,
  Literal,
  Self,
  TypeAlias,
  TypedDict,
  cast,
)

# import aiofiles
from aiobotocore.session import get_session
from botocore.exceptions import ClientError
from fastapi import (
  Depends,
  FastAPI,
  File,
  Query,
  Request,
  Response,
  UploadFile,
  status,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
  from logging import Logger

  from starlette.middleware.base import RequestResponseEndpoint
  from types_aiobotocore_s3.client import S3Client


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


class AWSClientKwargs(TypedDict):
  """Kwargs for AWS S3 client."""

  aws_access_key_id: str
  aws_secret_access_key: str


class Settings(BaseSettings):
  """API settings."""

  model_config = SettingsConfigDict(
    env_file=Path(__file__).parent / ".env",
    env_file_encoding="utf-8",
  )

  # FastAPI settings
  title: str = "AWS S3 Management API"
  description: str = "API to manage AWS S3 buckets and objects"
  version: str = "0.0.1"
  debug: bool = False

  # Logging settings
  log_name: str = "api"
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"
  log_datefmt: str = "%Y-%m-%d %H:%M:%S"

  # AWS S3 settings
  aws_access_key_id: str = ""
  aws_secret_access_key: str = ""

  # Files upload settings
  max_file_upload_size: int = 1_000_000  # 1MB

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

  @property
  def aws_s3_kwargs(self) -> AWSClientKwargs:
    """Kwargs for AWS S3 client."""
    return AWSClientKwargs(
      aws_access_key_id=self.aws_access_key_id,
      aws_secret_access_key=self.aws_secret_access_key,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


def configure_logging(name: str, options: "LoggingKwargs | None" = None) -> "Logger":
  """Configure app logging and return logger object."""
  if options is not None:
    logging.basicConfig(**options)
  return logging.getLogger(name)


class MaxUploadFileSizeMiddleware(BaseHTTPMiddleware):
  """Middleware to validate size of the uploaded file."""

  async def dispatch(
    self,
    request: Request,
    call_next: "RequestResponseEndpoint",
  ) -> Response:
    """Check size of the uploaded file by validating Content-Length header.

    :param request: Request object
    :param call_next: Response object
    :return: 411/413 response if validation fails, otherwise proceed to next middleware
    """
    if request.method == "POST":
      content_length = request.headers.get("content-length")
      if not content_length:
        return Response(status_code=status.HTTP_411_LENGTH_REQUIRED)
      if int(content_length) > settings.max_file_upload_size:
        max_file_size_in_mb = settings.max_file_upload_size // 1_000_000
        return PlainTextResponse(
          content=f"File is to big. Max file size is {max_file_size_in_mb} MB",
          status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    return await call_next(request)


class EmptyBucketError(Exception):
  """Custom exception to be raised when the target S3 bucket is empty."""

  __slots__ = ("message",)

  def __init__(self, message: str = "S3 bucket is empty") -> None:
    """Set error message."""
    self.message = message


async def bucket_empty_error_handler(_: Request, e: EmptyBucketError) -> JSONResponse:
  """Handle s3 bucket empty error."""
  client_message = {"error": e.message}
  return JSONResponse(client_message, status.HTTP_400_BAD_REQUEST)


async def aws_client_error_handler(request: Request, e: ClientError) -> JSONResponse:
  """AWS client error handler."""
  error = f"Client Error: {e}"
  logger = await get_logger(request)
  logger.error(error)
  status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
  # No such bucket error handling
  if e.response["Error"]["Code"] == "NoSuchBucket":
    error = e.response["Error"]["Message"]
    status_code = status.HTTP_404_NOT_FOUND
  return JSONResponse(error, status_code)


# error handlers mapping to be registered in the main FastAPI app
error_handlers: dict[
  int | type[Exception],
  Callable[[Request, Any], Coroutine[Any, Any, Response]],
] = {
  ClientError: aws_client_error_handler,
  EmptyBucketError: bucket_empty_error_handler,
}


class AppState(TypedDict):
  """Data structure to represent state of the main FastAPI app."""

  logger: "Logger"
  s3_client: "S3Client"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
  """Define the client to interact with AWS S3.

  NOTE: logger object can be redefined during testing, by adding it
        to the app.state, like app.state.logger = ...
        Otherwise, default logger will be created via configure_logging function.
  """
  logger = getattr(
    app.state,
    "logger",
    configure_logging(settings.log_name, options=settings.logging_kwargs),
  )
  s3_session = get_session()
  async with s3_session.create_client("s3", **settings.aws_s3_kwargs) as s3_client:
    yield AppState(s3_client=s3_client, logger=logger)


async def get_s3_client(request: Request) -> "S3Client":
  """Return the client to interact with S3 declared in the app's lifespan."""
  return cast("S3Client", request.state.s3_client)


async def get_logger(request: Request) -> "Logger":
  """Return logger declared in the app's lifespan."""
  return cast("Logger", request.state.logger)


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={**error_handlers},
)
app.add_middleware(MaxUploadFileSizeMiddleware)

# Query param to specify name of S3 bucket
BucketQueryParam = Query(
  description="Name of S3 bucket",
  examples=["my-bucket-cace19b497e8"],
)


class VersionInfo(BaseModel):
  """Schema to represent version info of the API."""

  version: str = Field(description="Version of the API", examples=["0.0.1"])


class S3BucketName(BaseModel):
  """Schema to specify name of S3 bucket."""

  name: str = Field(
    alias="bucket",
    description="Name of S3 bucket",
    examples=["my-bucket-cace19b497e8"],
  )


class S3ObjectInfo(BaseModel):
  """Schema to specify info about object in S3 bucket.

  NOTE: we wrap Query into Field because without it
        some extra params such as title, description,
        example, etc. aren't displayed in the OpenAPI
        schema.

        See: https://github.com/fastapi/fastapi/issues/4700

  NOTE: when using a Pydantic model for POST-based routes, then
        Query argument can be ignored and an example of field can
        be declared within a pydantic's Field method like this:
        Field(examples=['test']) instead of Field(Query(examples=['test']))
  """

  bucket: str = Field(BucketQueryParam, serialization_alias="Bucket")
  object: str = Field(
    Query(
      description="Name of object in S3 bucket",
      examples=["hehe.png"],
    ),
    serialization_alias="Key",
  )
  version: str | None = Field(
    Query(
      None,
      description="Version of object in S3 bucket",
      examples=["9fda9ee0-58fd-44f9-8816-d90e377079c0"],
    ),
    serialization_alias="VersionId",
  )
  model_config = ConfigDict(populate_by_name=True)


class AWSResponseListObjects(BaseModel):
  """Schema to represent info about objects in S3 bucket."""

  bucket: str = Field(BucketQueryParam)
  objects: list[str] = Field(default_factory=list)
  count: int = 0

  @model_validator(mode="after")
  def count_objects(self) -> Self:
    """Set self.count attribute based on length of self.objects attribute."""
    self.count = len(self.objects)
    return self


class S3ObjectURL(BaseModel):
  """Schema to represent a URL of the object in S3 bucket."""

  url: str = Field(description="URL to S3 object")


class Status(BaseModel):
  """Schema to specify status of the operation."""

  status: Literal["created", "uploaded"]


# Reused S3-client annotation with dependency
S3_Client: TypeAlias = Annotated["S3Client", Depends(get_s3_client)]
S3_Object: TypeAlias = Annotated[S3ObjectInfo, Depends()]


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Return health status of the API."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "health"},
  )


@app.get("/version")
async def version() -> VersionInfo:
  """Return version of the API."""
  return VersionInfo(version=settings.version)


@app.post(
  "/bucket/create",
  status_code=status.HTTP_201_CREATED,
  tags=["s3 bucket"],
)
async def create_bucket(bucket: S3BucketName, s3_client: S3_Client) -> Status:
  """Create S3 Bucket.

  NOTE: the endpoint returns an HTTP 200 response even if
        specified bucket already exists in the default location.
        Once a LocationConstraint is set, the corresponding exception
        will be thrown.

        See: https://is.gd/H67mMr
  """
  await s3_client.create_bucket(Bucket=bucket.name)
  return Status(status="created")


@app.delete(
  "/bucket/delete",
  status_code=status.HTTP_204_NO_CONTENT,
  tags=["s3 bucket"],
)
async def delete_bucket(bucket: S3BucketName, s3_client: S3_Client) -> None:
  """Delete S3 bucket."""
  objects = await s3_client.list_objects_v2(Bucket=bucket.name)
  # bucket isn't empty
  if "Contents" in objects:
    objects = [{"Key": obj["Key"]} for obj in objects["Contents"]]
    # Delete all objects of the bucket
    await s3_client.delete_objects(Bucket=bucket.name, Delete={"Objects": objects})
  # Delete empty bucket
  await s3_client.delete_bucket(Bucket=bucket.name)


@app.post("/bucket/objects/upload", tags=["s3 object"])
async def upload_file(
  bucket: S3BucketName,
  s3_client: S3_Client,
  file: Annotated[UploadFile, File(description="File to upload into S3 bucket")],
) -> Status:
  """Upload file into S3 bucket."""
  try:
    file_content = await file.read()
    await s3_client.put_object(
      Bucket=bucket.name,
      Key=file.filename,
      Body=file_content,
    )
  finally:
    await file.close()
  return Status(status="uploaded")


@app.get("/bucket/objects/list/{bucket}", tags=["s3 object"])
async def list_objects(bucket: str, s3_client: S3_Client) -> AWSResponseListObjects:
  """List of objects in S3 bucket.

  NOTE: only first 1000 objects of the bucket are returned.
  To return all objects you need to pagination.
  """
  objects = await s3_client.list_objects_v2(Bucket=bucket)
  if "Contents" not in objects:
    raise EmptyBucketError
  return AWSResponseListObjects(
    bucket=bucket,
    objects=[obj["Key"] for obj in objects["Contents"]],
  )


@app.delete(
  "/bucket/objects/delete",
  tags=["s3 object"],
  status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_object(s3_client: S3_Client, s3_object: S3_Object) -> None:
  """Delete object in S3 bucket.

  NOTE: if there's no such object in the bucket,
  204 response will be returned anyway.
  """
  await s3_client.delete_object(
    **s3_object.model_dump(by_alias=True, exclude_none=True)
  )


@app.get(
  "/bucket/objects/download",
  tags=["s3 object"],
  responses={
    200: {
      "description": "Download link",
      "headers": {
        "Content-Disposition": "attachment;filename=hehe.png",
        "Content-Type": "application/octet-stream",
      },
      "content": {"application/octet-stream": {}},
    }
  },
)
async def download_object(s3_client: S3_Client, s3_object: S3_Object) -> Response:
  """Generate download link to object from S3 bucket."""
  resp = await s3_client.get_object(
    **s3_object.model_dump(by_alias=True, exclude_none=True)
  )
  data = await resp["Body"].read()
  # async with aiofiles.open(s3_object.object, "wb") as f:
  #   await f.write(data)
  return Response(
    content=data,
    headers={
      "Content-Disposition": f"attachment;filename={s3_object.object}",
      "Content-Type": "application/octet-stream",
    },
  )


@app.get("/bucket/objects/presign-url", tags=["s3 object"])
async def presign_object_url(s3_client: S3_Client, s3_object: S3_Object) -> S3ObjectURL:
  """Generate presigned URL for object in S3 bucket."""
  presigned_url = await s3_client.generate_presigned_url(
    "get_object",
    Params=s3_object.model_dump(by_alias=True, exclude_none=True),
  )
  return S3ObjectURL(url=presigned_url)
