from typing import Annotated

import aiofiles
from fastapi import APIRouter, File, UploadFile, status
from pydantic import BaseModel, Field

CHUNK_SIZE = 1024 * 1024  # 1MB


class FileUploadedSucceeded(BaseModel):
  """Schema to specify successful file upload response."""

  message: str = Field(
    description="Successful file upload message",
    default="File(s) uploaded successfully",
  )


class FileUploadFailed(BaseModel):
  """Schema to specify failed file upload response."""

  message: str = Field(
    description="Failed file upload message",
    default="Failed to upload one or multiple files",
  )
  errors: dict[str | None, str] = Field(
    description="Details of the errors occurred during file upload"
  )


router = APIRouter(tags=["v2"])


@router.post("/upload/one", status_code=status.HTTP_201_CREATED)
async def upload_one_asynchronously(
  file: Annotated[UploadFile, File(...)],
) -> FileUploadedSucceeded | FileUploadFailed:
  """Upload a single file asynchronously."""
  try:
    contents = await file.read()
    async with aiofiles.open(file.filename, "wb") as f:
      await f.write(contents)
  except Exception as e:
    return FileUploadFailed(errors={file.filename: str(e)})
  finally:
    await file.close()
  return FileUploadedSucceeded()


@router.post("/upload/multiple", status_code=status.HTTP_201_CREATED)
async def upload_multiple_asynchronously(
  files: Annotated[list[UploadFile], File(...)],
) -> FileUploadedSucceeded | FileUploadFailed:
  """Upload multiple files asynchronously in chunks."""
  errors: dict[str | None, str] = {}
  for file in files:
    try:
      async with aiofiles.open(file.filename, "wb") as f:
        while contents := await file.read(CHUNK_SIZE):
          await f.write(contents)
    except Exception as e:
      errors[file.filename] = str(e)
    finally:
      await file.close()
  return FileUploadedSucceeded() if not errors else FileUploadFailed(errors=errors)
