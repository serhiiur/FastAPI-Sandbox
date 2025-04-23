## Introduction
Theory + practice for using RabbitMQ


## Navigation

- [example_0. Upload one and multiple files synchronously and asynchronously](file-upload):
```bash
poetry run fastapi dev file-upload/api.py
```

- [example_1. Different ways to run a synchonous CPU-bound task in the async code without blocking the event loop](fastapi-threadpool-executor):
```bash
poetry run fastapi dev fastapi-threadpool-executor/api.py
```





## Notes
* When you declare an endpoint with normal `def` instead of `async def`, it is run in an external threadpool that is then awaited, instead of being called directly (as it would block the server).

* If you are using a third party library that communicates with something (a database, an API, the file system, etc.) and doesn't have support for using `await`, then declare your endpoints as normally, with just `def`.

* You can mix `def` and `async def` in your endpoints as much as you need and define each one using the best option for you.

* FastAPI/Starlette uses *AnyIO* threads to run blocking functions, such as endpoints defined with normal def, in an external threadpool and then await them (so that FastAPI would still work asynchronously), in order to prevent them from blocking the event loop (of the main thread), and hence, the entire server.

* Every time an HTTP request arrives at an endpoint defined with normal `def`, a new thread will be spawned (or an idle thread will be used, if available). So you might need to adjust the maximum number of threads in that threadpool.

* You should always aim at using asynchronous code (i.e., using async/await), wherever is possible, as async code runs directly in the event loop which runs in a single thread (in this case, the main thread).

* In order to run an endpoint or a function described above in a separate thread and await it, FastAPI uses Starlette's asynchronous [run_in_threadpool()](https://github.com/encode/starlette/blob/b8ea367b4304a98653ec8ce9c794ad0ba6dcaf4b/starlette/concurrency.py#L35) function, which, under the hood, calls `anyio.to_thread.run_sync()`.

* The default number of worker threads of that external threadpool is 40 and can be adjusted as required. [See](https://stackoverflow.com/a/77941425/17865804).

* When using a web browser to call the same endpoint for the second (third, and so on) time, please remember to do that from a tab that is isolated from the browser's main session; otherwise, succeeding requests (i.e., coming after the first one) might be blocked by the browser (i.e., on client side), as the browser might be waiting for a response to the previous request from the server, before sending the next request. This is a common behaviour for the Chrome web browser at least, due to waiting to see the result of a request and check if the result can be cached, before requesting the same resource again (Also, note that every browser has a specific limit for parallel connections to a given hostname).


* Use more server workers to take advantage of multi-core CPUs, in order to run multiple processes in parallel and be able to serve more requests. For example, uvicorn main:app --workers 4. When using 1 worker, only one process is run. When using multiple workers, this will spawn multiple processes (all single threaded). Each process has a separate GIL, as well as its own event loop, which runs in the main thread of each process and executes all tasks in its thread. That means, there is only one thread that can take a lock on the interpreter of each process; unless, of course, you employ additional threads, either outside or inside the event loop, e.g., when using run_in_threadpool, a custom ThreadPoolExecutor

*  In FastAPI, when using the async methods of `UploadFile`, such as `await file.read()` and a`wait file.close()`, FastAPI/Starlette, behind the scenes, actually calls the corresponding synchronous `File` methods in a separate thread from the external threadpool described earlier (using `fastapi.concurrency.run_in_threadpool()`) and awaits it; otherwise, such methods/operations would block the event loop.

* The `SpooledTemporaryFile` used by FastAPI/Starlette has the `max_size` attribute set to 1 MB, meaning that the data are spooled in memory until the file size exceeds 1 MB, at which point the data are written to a temporary file on disk, under the OS's temp directory. Hence, if you uploaded a file larger than 1 MB, it wouldn't be stored in memory, and calling `file.file.read()` would actually read the data from disk into memory. Thus, if the file is too large to fit into your server's RAM, you should rather read the file in chunks and process one chunk at a time.

* Another approach is explained and demonstrated on how to upload large files in chunks, using Starlette's `request.stream()`, which results in considerably minimizing the time required to upload files, as well as avoiding the use of threads from the external threadpool.

* In case you had to upload a rather large file that wouldn't fit into your client's RAM (if, for instance, you had 2 GB available RAM on the client's device and attempted to load a 4 GB file), you should rather use a streaming upload on client side as well, which would allow you to send large streams or files without reading them into memory (might take a bit more time to upload though, depending on the chunk size, which you may customize by reading the file in chunks instead and setting the chunk size as desired)

* To run tasks in the background, without waiting for them to complete, in order to proceed with executing the rest of the code in an endpoint, you could use FastAPI's `BackgroundTasks`, as shown here and here. If the background task function is defined with `async def`, FastAPI will run it directly in the event loop, whereas if it is defined with normal `def`, FastAPI will use `run_in_threadpool()` and `await` the returned coroutine (same concept as API endpoints). 

* Another option when you need to run an `async def` function in the background, but not necessarily having it trigerred after returning a FastAPI response (which is the case in BackgroundTasks), is to use `asyncio.create_task()`.






## Useful Links
- [StackOverflow. How to Upload File using FastAPI?](https://stackoverflow.com/questions/63048825/how-to-upload-file-using-fastapi)
- [StackOverflow. FastAPI UploadFile is slow compared to Flask](https://stackoverflow.com/questions/65342833/fastapi-uploadfile-is-slow-compared-to-flask/70667530#70667530)
- [StackOverflow. Conurrency and Parallelism in FastAPI](https://stackoverflow.com/questions/71516140/fastapi-runs-api-calls-in-serial-instead-of-parallel-fashion/71517830#71517830)
