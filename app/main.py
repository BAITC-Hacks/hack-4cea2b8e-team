"""FastAPI-приложение: API + отдача фронтенда без сборки.

Запуск:  uvicorn app.main:app --reload
Открыть: http://localhost:8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, llm

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ---------------------------------------------------------------- модели ---
class GenerateIn(BaseModel):
    prompt: str
    system: str | None = None


class ItemIn(BaseModel):
    title: str
    payload: dict[str, Any] = {}


# ------------------------------------------------------------------- API ---
@app.get("/api/health")
def health() -> dict[str, Any]:
    """Эндпоинт для быстрой проверки «оно живое». Упомяните его в README."""
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "demo_mode": config.DEMO_MODE,
        "model": config.MODEL,
        **db.stats(),
    }


@app.post("/api/generate")
def generate(body: GenerateIn) -> dict[str, str]:
    if not body.prompt.strip():
        raise HTTPException(400, "prompt пустой")
    text = llm.complete(body.prompt, body.system or "Ты — полезный ассистент.")
    return {"text": text}


@app.post("/api/generate/stream")
def generate_stream(body: GenerateIn) -> StreamingResponse:
    return StreamingResponse(
        llm.stream(body.prompt, body.system or "Ты — полезный ассистент."),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/api/items")
def get_items() -> list[dict[str, Any]]:
    return db.list_items()


@app.post("/api/items")
def post_item(body: ItemIn) -> dict[str, int]:
    return {"id": db.add_item(body.title, body.payload)}


@app.delete("/api/items/{item_id}")
def remove_item(item_id: int) -> dict[str, bool]:
    db.delete_item(item_id)
    return {"ok": True}


# -------------------------------------------------------------- фронтенд ---
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
