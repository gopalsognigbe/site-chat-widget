"""FastAPI entrypoint: exposes HTTP endpoints to index a site and to chat,
and serves the JS widget and demo site as static files."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import indexer, rag
from app.config import get_settings

logger = logging.getLogger(__name__)

# Uvicorn only configures its own loggers: show ours too (e.g. the
# translated search query), without the libraries' chatter.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("app").setLevel(logging.INFO)

ROOT = Path(__file__).resolve().parent.parent
DEMO_SITE_DIR = ROOT / "demo_site"
WIDGET_DIR = ROOT / "widget"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)


class Source(BaseModel):
    n: int
    title: str
    heading: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the embedding model at startup, so the first visitor doesn't
    # wait several seconds for it.
    try:
        indexer.embed(["warm-up"])
    except Exception as exc:
        logger.warning("Could not preload the embedding model: %s", exc)
    yield


app = FastAPI(title="Site chat widget", lifespan=lifespan)

# Open to every origin for the demo, so the widget can be embedded on any
# site. In production, list the client's domains instead of "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    chunks = indexer.index_size()
    return {
        "status": "ok",
        "index_ready": chunks > 0,
        "indexed_chunks": chunks,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    # A plain (non-async) function: FastAPI runs it in a worker thread, so a
    # slow LLM call doesn't block other visitors.
    history = [message.model_dump() for message in request.history]
    return rag.answer(request.question, history)


# Static files are mounted last: "/" would otherwise catch /chat and /health.
WIDGET_DIR.mkdir(exist_ok=True)
app.mount("/widget", StaticFiles(directory=WIDGET_DIR), name="widget")
app.mount("/", StaticFiles(directory=DEMO_SITE_DIR, html=True), name="demo_site")
