import asyncio

from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientConnectionResetError
from faker import Faker


async def main() -> None:
  """Client to send random messages to the websocket channel."""
  faker = Faker()
  url = "ws://localhost:8000/ws"
  async with ClientSession() as session, session.ws_connect(url) as ws:
    while True:
      try:
        await ws.send_str(faker.sentence())
      except ClientConnectionResetError:
        print("Client disconnected")
        return


if __name__ == "__main__":
  asyncio.run(main())
