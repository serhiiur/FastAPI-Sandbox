import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator, TypedDict, TYPE_CHECKING

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool

if TYPE_CHECKING:
  from asyncio.unix_events import _UnixSelectorEventLoop


class AppState(TypedDict):
  """State of the main app"""
  pool: ThreadPoolExecutor


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """
  Initialize a custom thread pool executor
  in which we can run synchronous blocking function
  without blocking the main thread.
  """
  with ThreadPoolExecutor() as pool:
    yield AppState(pool=pool)


async def get_thread_pool_executor(request: Request) -> ThreadPoolExecutor:
  """Return initialized thread pool executor object in the lifespan"""
  return getattr(request.state, "pool")


async def get_running_loop() -> "_UnixSelectorEventLoop":
  """Return running loop"""
  return asyncio.get_running_loop()


app = FastAPI(lifespan=lifespan)


@app.get("/run-in-custom-executor")
async def run_in_custom_executor(
  loop: Annotated["_UnixSelectorEventLoop", Depends(get_running_loop)],
  pool: Annotated[ThreadPoolExecutor, Depends(get_thread_pool_executor)]
) -> None:
  """
  Execute a blocking synchronous function (time.sleep)
  in a separate thread using custom executor.
  
  As a result, the main thread won't be blocked and users
  will be able to continue working with the API.
  """
  await loop.run_in_executor(pool, time.sleep, 30)


@app.get("/run-in-starlette-executor")
async def run_in_starlette_executor() -> None:
  """
  Execute a blocking synchronous function (time.sleep)
  in using Starlette's 'run_in_threadpool' function.
  
  As a result, the main thread won't be blocked and users
  will be able to continue working with the API.
  """
  await run_in_threadpool(time.sleep, 30)


@app.get(
  "/threads",
  description="Display the number of Thread objects currently alive"
)
async def get_active_threads() -> int:
  return threading.active_count()
