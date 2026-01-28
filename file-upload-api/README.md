## About
This is a simple FastAPI application that demonstrates how to handle file uploads both synchronously and asynchronously. It provides two endpoints: one for synchronous file uploads and another for asynchronous file uploads separated by different versions:
- v1 for synchronous uploads
- v2 for asynchronous uploads


## Running
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn api:app
```

## Usage

After running the application, navigate to [/docs](http://127.0.0.1:8000/docs) and start uploading files using either synchronously or asynchronous methods.


## References
- [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/)
