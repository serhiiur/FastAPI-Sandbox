import aiofiles
from fastapi import FastAPI, File, UploadFile


app = FastAPI()



@app.post("/upload/one/sync/")
def upload_one_file_sync(file: UploadFile = File(...)) -> dict[str, str]:
  """Upload one file synchronously"""
  try:
    contents = file.file.read()
    with open(file.filename, "wb") as f:
      f.write(contents)
  except Exception as e:
    print(f"Error occured while uploading {file.filename}: {e}")
  finally:
    file.file.close()
  return {"response": "Uploaded 1 file synchronously"}


@app.post("/upload/many/sync")
def upload_multiple_files_sync(files: list[UploadFile] = File(...)) -> dict[str, str]:
  """Upload multiple files synchronously in chunks"""
  total_files_uploaded = 0
  for file in files:
    try:
      contents = file.file.read()
      with open(file.filename, "wb") as f:
        while contents := file.file.read(1024 * 1024):  # 1MB per chunk
          f.write(contents)
    except Exception as e:
      print(f"Error occured while uploading {file.filename}: {e}")
    finally:
      file.file.close()
  return {"response": f"Uploaded {total_files_uploaded} files synchronously"}


@app.post("/upload/one/async")
async def upload_one_file_async(file: UploadFile = File(...)) -> dict[str, str]:
  """Upload one file asynchronously"""
  try:
    contents = await file.read()
    async with aiofiles.open(file.filename, "wb") as f:
      await f.write(contents)
  except Exception as e:
    print(f"Error occured while uploading {file.filename}: {e}")
  finally:
    await file.close()
  return {"response": "Uploaded 1 file asynchronously"}


@app.post("/upload/many/async")
async def upload_multiple_files_async(files: list[UploadFile] = File(...)) -> dict[str, str]:
  """Upload multiple files in chunks asynchronously"""
  total_files_uploaded = 0
  for file in files:
    try:
      async with aiofiles.open(file.filename, "wb") as f:
        while contents := await file.read(1024 * 1024):  # 1MB per chunk
          await f.write(contents)
      total_files_uploaded += 1
    except Exception as e:
      print(f"Error occured while uploading {file.filename}: {e}")
    finally:
      await file.close()
  return {"response": f"Uploaded {total_files_uploaded} files asynchronously"}
