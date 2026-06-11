import fastapi, uvicorn
print("fastapi:", fastapi.__version__, "| uvicorn:", uvicorn.__version__)
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
print("All imports OK")
