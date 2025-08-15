## About
The example shows how to integrate and test an API based on FastAPI with [FastAPI-Cache](https://github.com/long2ice/fastapi-cache) extension based on Redis.

## Runnings

```bash
# run redis
docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest

fastapi dev api.py

# run tests
pytest -vsx test_api.py
```
