## Running
```bash
# run redis
docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest

# run API
uv run fastapi dev api.py

# run tests
uv run pytest -v test_api.py
```
