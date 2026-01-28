from typing import Annotated

from fastapi import APIRouter, File, UploadFile

CHUNK_SIZE = 1024 * 1024 * 3  # 3MB


class FileUploadError(Exception):
  """Custom exception to be raised when a file wasn't uploaded due to error."""

  __slots__ = ("message",)

  def __init__(self, message: str = "File not uploaded") -> None:
    """Set error message."""
    self.message = message


router = APIRouter(tags=["v1"])


@router.post("/upload/one")
def upload_one_synchronously(file: Annotated[UploadFile, File(...)]) -> dict[str, str]:
  """Upload a single file synchronously."""
  try:
    contents = file.file.read()
    with open(file.filename, "wb") as f:  # noqa: PTH123
      f.write(contents)
  except Exception as e:
    raise FileUploadError from e
  finally:
    file.file.close()
  return {"response": "uploaded 1 file"}


@router.post("/upload/many")
def upload_many_synchronously(
  files: Annotated[list[UploadFile], File(...)],
) -> dict[str, str]:
  """Upload multiple files synchronously in chunks."""
  for file in files:
    try:
      contents = file.file.read()
      with open(file.filename, "wb") as f:  # noqa: PTH123
        while contents := file.file.read(CHUNK_SIZE):
          f.write(contents)
    except Exception as e:
      raise FileUploadError from e
    finally:
      file.file.close()
  return {"response": f"uploaded {len(files)} files"}
