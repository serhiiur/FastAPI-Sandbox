## About
The example shows how to use [RedisOM](https://github.com/redis/redis-om-python) package with FastAPI to create robust async CRUD APIs.

**Note**: currently installed version of Redis OM (0.3.5) can't be fully integrated with [FakeRedis](https://github.com/cunla/fakeredis-py)(2.31.0) package. Some operations of *RedisSearch* module, required by the API, aren't implemented yet. [See](https://fakeredis.readthedocs.io/en/latest/supported-commands/RedisSearch/SEARCH/).

## Running
```bash
# run redis
docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest

# run API
fastapi dev api.py

# run tests
pytest -vx test_api.py
```
