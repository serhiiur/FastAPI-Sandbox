## About
The example shows how to use Websockets with FastAPI, producing incoming to the websocket messages into a Redis Stream. There's also an aiohttp-based websocket [client](client.py) that connects to the websocket server and sends random messages in an infinite loop. Finally, the [consumer](consumer.py) listens to incoming messages from the Redis Stream and prints them to the console.


## Project Structure
```bash
.
├── client.py # aiohttp-based WebSocket client to send messages to the websocket server
├── consumer.py # listens to incoming messages to the Redis stream and prints them to the console
├── main.py # main FastAPI application using WebSockets and Redis Streams
├── test_main.py # integration tests for testing websockets
└── requirements.txt # project dependencies
```


## Running
```bash
# run Redis
docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest

# run API
fastapi dev main.py

# run consumer to read incoming messages from the Redis Stream
python consumer.py

# run websocket client to send message to the websocke
python client.py

# run tests
pytest -v test_main.py
```

## References
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI tips on using Websockets #1](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#3-use-async-for-instead-of-while-true-on-websocket)
- [FastAPI tips on using Websockets #2](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#4-ignore-the-websocketdisconnect-exception)
- [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)
- [Redis Sorted Sets](https://redis.io/docs/latest/develop/data-types/sorted-sets/)
- [Aiohttp WebSockets](https://docs.aiohttp.org/en/stable/client_quickstart.html#websockets)
