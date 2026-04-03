import asyncio
import threading
import time
from asyncio.events import AbstractEventLoop
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated, TypedDict

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool


class AppState(TypedDict):
  """State of the main app."""

  pool: ThreadPoolExecutor


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init custom thread pool executor.

  The custom executor is used to run synchronous
  blocking functions without blocking the main thread.
  """
  with ThreadPoolExecutor() as pool:
    yield AppState(pool=pool)


async def get_thread_pool_executor(request: Request) -> ThreadPoolExecutor:
  """Return initialized thread pool executor object in the lifespan."""
  return request.state.pool


async def get_running_loop() -> AbstractEventLoop:
  """Return running loop."""
  return asyncio.get_running_loop()


app = FastAPI(lifespan=lifespan)


@app.get("/run-in-custom-executor")
async def run_in_custom_executor(
  loop: Annotated[AbstractEventLoop, Depends(get_running_loop)],
  pool: Annotated[ThreadPoolExecutor, Depends(get_thread_pool_executor)],
) -> None:
  """Execute a synchronous blocking function using custom thread pool executor.

  As a result, the main thread won't be blocked and users
  will be able to continue working with the API.
  """
  await loop.run_in_executor(pool, time.sleep, 30)


@app.get("/run-in-starlette-executor")
async def run_in_starlette_executor() -> None:
  """Execute a synchronous blocking function using Starlette's thread pool executor.

  As a result, the main thread won't be blocked and users
  will be able to continue working with the API.
  """
  await run_in_threadpool(time.sleep, 30)


@app.get("/threads")
async def get_active_threads() -> int:
  """Display the number of Thread objects currently alive."""
  return threading.active_count()
