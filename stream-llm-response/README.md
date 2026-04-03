## About

A minimal FastAPI application demonstrating two approaches to streaming LLM responses, primarily **ChatOpenAI** from **langchain_openai** package.


## Installation

Step 1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Step 2. Set up <ins>.env</ins> file and provide a valid *OPENAI_API_KEY*. You can use <ins>.env.example</ins> as a template.

Step 3. Run the API:
```bash
python api.py
```


## Usage

The API exposes 2 endpoints that both stream a response from an OpenAI model given a text prompt:

| Endpoint | Approach | FastAPI version |
|---|---|---|
| `POST /stream-llm-old` | `StreamingResponse` | < 0.134 |
| `POST /stream-llm-new` | Native Python iterator + `EventSourceResponse` | >= 0.134 |


You can test the streaming API endpoints using different HTTP clients such as *cURL*, *httpie*, etc.

Example of using [httpie](https://httpie.io/):

```bash
# Old approach
http POST :8000/stream-llm-old --raw '{"text": "Give me a quick travel plan for a trip to Japan"}' 

# New approach
http POST :8000/stream-llm-new --raw '{"text": "Give me a quick travel plan for a trip to Japan"}' 
```

As a result the response to the prompt will be streamed to the console.


## References
- [FastAPI docs — Streaming responses](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)
- [FastAPI SSE (Server Sent Events)](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [LangChain — ChatOpenAI streaming](https://python.langchain.com/docs/integrations/chat/openai/)
