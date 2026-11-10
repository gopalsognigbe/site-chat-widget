"""Indexer: embeds chunks with the configured embedding model and stores them
in a persistent ChromaDB collection under CHROMA_DIR."""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from functools import lru_cache

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.chunker import chunk_page
from app.config import get_settings
from app.crawler import crawl

logger = logging.getLogger(__name__)

COLLECTION_NAME = "site_chunks"
ADD_BATCH_SIZE = 256

# Reference codes such as "LI-007", "A12" or "MLS12345": a few letters, an
# optional dash, then at least two digits.
CODE_PATTERN = re.compile(r"\b[A-Za-z]{1,5}-?\d{2,}\b")

# What an embedding is: the model turns a piece of text into a list of
# numbers (a vector, 384 numbers for all-MiniLM-L6-v2). Texts with similar
# meaning get vectors that point in similar directions, even when they use
# different words ("commission" vs "fee when I sell"). To search, we embed
# the question the same way and ask Chroma for the closest chunk vectors.


@lru_cache
def _get_model():
    """Load the local embedding model once; later calls reuse it.

    Loading takes a few seconds (and downloads ~90 MB the first time), so we
    never want to do it per request.
    """
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    # When OPENAI_API_KEY is a Hugging Face token (HF router), reuse it for
    # model downloads (higher rate limits, no warning).
    token = settings.openai_api_key if settings.openai_api_key.startswith("hf_") else None
    logger.info("Loading embedding model %s", settings.embedding_model)
    try:
        # Already downloaded: load from the local cache, no network needed.
        return SentenceTransformer(settings.embedding_model, token=token, local_files_only=True)
    except Exception:
        return SentenceTransformer(settings.embedding_model, token=token)


@lru_cache
def _get_openai_client():
    from openai import OpenAI

    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def embed(texts: list[str]) -> list[list[float]]:
    """Turn texts into embedding vectors with the configured provider."""
    settings = get_settings()
    if settings.embedding_provider == "openai":
        response = _get_openai_client().embeddings.create(model=settings.embedding_model, input=texts)
        return [item.embedding for item in response.data]

    # Normalized vectors make cosine similarity a simple, stable comparison.
    vectors = _get_model().encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


@lru_cache
def _get_client() -> chromadb.ClientAPI:
    """A Chroma client that saves the index to disk at CHROMA_DIR."""
    return chromadb.PersistentClient(
        path=get_settings().chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def page_language(url: str) -> str:
    """"fr" for pages under /fr/, "en" otherwise (the site's two languages)."""
    return "fr" if "/fr/" in url else "en"


def _embedding_input(chunk: dict) -> str:
    """The text we embed: title and section heading first, then the chunk.

    A chunk like "4% of the final sale price" says little on its own; with
    "Our fees > Selling" in front, it matches "commission when I sell".
    """
    return f"{chunk['title']}\n{chunk['heading']}\n{chunk['text']}"


def build_index(start_url: str, max_pages: int | None = None) -> int:
    """Crawl the site, chunk every page and (re)build the Chroma collection.

    Returns the number of chunks indexed.
    """
    pages = crawl(start_url, max_pages=max_pages)
    chunks = [chunk for page in pages for chunk in chunk_page(page)]
    logger.info("%d pages -> %d chunks", len(pages), len(chunks))

    client = _get_client()

    # Why we delete first: re-indexing must *replace* the site's content.
    # If we only added new chunks, pages that changed or were removed would
    # leave old chunks behind, and the bot would keep answering with outdated
    # prices or deleted listings. Starting from an empty collection is the
    # simplest way to make the index match the site exactly.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:  # the collection doesn't exist yet (first build)
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,  # we always pass our own vectors
    )

    for start in range(0, len(chunks), ADD_BATCH_SIZE):
        batch = chunks[start:start + ADD_BATCH_SIZE]
        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embed([_embedding_input(c) for c in batch]),
            documents=[c["text"] for c in batch],
            metadatas=[
                {"url": c["url"], "title": c["title"], "heading": c["heading"], "lang": page_language(c["url"])}
                for c in batch
            ],
        )
    return len(chunks)


def search(query: str, k: int = 4, lang: str | None = None) -> list[dict]:
    """Return the `k` chunks closest in meaning to `query`.

    Each result: {"id", "text", "url", "title", "heading", "lang", "score"},
    where score is the cosine similarity (1 = same meaning, 0 = unrelated).
    With `lang` ("en" or "fr"), only chunks from pages in that language.
    """
    try:
        collection = _get_client().get_collection(COLLECTION_NAME, embedding_function=None)
    except Exception as exc:
        raise RuntimeError("The index is empty. Run: python -m app.indexer build <url>") from exc

    query_vector = embed([query])
    include = ["documents", "metadatas", "distances"]
    where = {"lang": lang} if lang else None

    # Embeddings capture meaning, not exact codes: "LI-007" or "H2X 1Y4"
    # look like noise to the model. When the question contains such a code,
    # chunks that contain it exactly go first.
    results: list[dict] = []
    codes = dict.fromkeys(v for c in CODE_PATTERN.findall(query) for v in (c, c.upper()))
    for code in codes:
        exact = _to_results(collection.query(
            query_embeddings=query_vector,
            n_results=max(k, 20),
            where=where,
            where_document={"$contains": code},
            include=include,
        ))
        # A chunk that mentions only this code (a listing's own card) is
        # more about it than a summary table listing every code.
        exact.sort(key=lambda r: (len(set(CODE_PATTERN.findall(r["text"]))), -r["score"]))
        results.extend(exact)

    results.extend(_to_results(collection.query(query_embeddings=query_vector, n_results=k, where=where, include=include)))

    unique: dict[str, dict] = {}
    for result in results:
        unique.setdefault(result["id"], result)
    return list(unique.values())[:k]


def _to_results(result: dict) -> list[dict]:
    return [
        {
            "id": chunk_id,
            "text": document,
            "url": metadata["url"],
            "title": metadata["title"],
            "heading": metadata["heading"],
            "lang": metadata.get("lang") or page_language(metadata["url"]),
            "score": round(1 - distance, 4),
        }
        for chunk_id, document, metadata, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]


def index_size() -> int:
    """Number of chunks currently indexed (0 if the index was never built)."""
    try:
        return _get_client().get_collection(COLLECTION_NAME, embedding_function=None).count()
    except Exception:
        return 0


def setup_cli_logging() -> None:
    """Show our own progress logs only; libraries stay quiet."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


def main() -> None:
    """Command line:
    python -m app.indexer build http://localhost:8000/index.html
    python -m app.indexer search "What is your commission when I sell?"
    """
    parser = argparse.ArgumentParser(description="Build or query the site's search index.")
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build", help="Crawl a site and rebuild the index")
    build_cmd.add_argument("url", help="Start URL, e.g. http://localhost:8000/index.html")
    build_cmd.add_argument("--max-pages", type=int, default=None, help="Page limit (default: MAX_PAGES)")

    search_cmd = commands.add_parser("search", help="Search the index")
    search_cmd.add_argument("query", help='e.g. "What is your commission when I sell?"')
    search_cmd.add_argument("-k", type=int, default=4, help="Number of results (default: 4)")

    args = parser.parse_args()
    setup_cli_logging()

    if args.command == "build":
        started = time.perf_counter()
        count = build_index(args.url, max_pages=args.max_pages)
        elapsed = time.perf_counter() - started
        print(f"\nIndexed {count} chunks in {elapsed:.1f}s -> {get_settings().chroma_dir}")
        return

    results = search(args.query, k=args.k)
    print(f'\nTop {len(results)} results for: "{args.query}"\n')
    for rank, result in enumerate(results, 1):
        preview = " ".join(result["text"].split())[:160]
        print(f"{rank}. score {result['score']:.3f} | {result['heading']}")
        print(f"   {result['url']}")
        print(f"   {preview}...\n")


if __name__ == "__main__":
    main()
