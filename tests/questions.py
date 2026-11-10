"""The evaluation questions, shared by tests/test_questions.py and
scripts/run_eval.py, and the checks applied to each answer."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

API_URL = "http://localhost:8000"
REQUEST_TIMEOUT_SECONDS = 60.0
# Groq's free plan allows 30 requests per minute; a French question costs two
# (search translation + answer).
PAUSE_SECONDS = 2.0


@dataclass
class Case:
    question: str
    lang: str  # "en" or "fr"
    # The answer passes when every group matches: a group is a list of
    # alternatives, any one of which may match.
    source_any: list[str] = field(default_factory=list)  # substrings of a source URL
    answer_any: list[list[str]] = field(default_factory=list)  # substrings of the answer
    refusal: bool = False  # expect "I can only help with the agency" and no sources


CASES = [
    Case("What documents do I need to rent?", "en", source_any=["/rent.html"]),
    Case("What is your commission to sell a house?", "en",
         source_any=["/fees.html", "/sell.html"], answer_any=[["4"]]),
    Case("Tell me about LI-002", "en", answer_any=[["LI-002"]]),
    Case("Which neighborhoods do you cover?", "en", source_any=["/neighborhoods.html"]),
    Case("Do you sell cars?", "en", refusal=True),
    Case("Quels documents faut-il pour louer ?", "fr", source_any=["/fr/rent.html"]),
    Case("Quelle est votre commission pour vendre ?", "fr", source_any=["/fr/"], answer_any=[["4"]]),
    Case("Avez-vous un condo à Verdun ?", "fr", answer_any=[["LI-003", "townhouse", "maison de ville"]]),
    Case("Comment vous contacter ?", "fr", source_any=["/fr/contact.html"]),
    Case("Vendez-vous des voitures ?", "fr", refusal=True),
]

# Small, frequent words of each language: enough to tell which one a short
# answer is written in. Kept separate from app/rag.py on purpose, so the test
# does not check the app with the app's own logic.
FRENCH = {"le", "la", "les", "un", "une", "des", "du", "de", "est", "sont", "vous", "votre", "vos",
          "nous", "notre", "nos", "pour", "avec", "dans", "sur", "et", "ou", "pas", "ne", "que",
          "qui", "au", "aux", "ce", "cette", "il", "elle", "peut", "être", "si"}
ENGLISH = {"the", "a", "an", "is", "are", "you", "your", "we", "our", "for", "with", "in", "on",
           "and", "or", "not", "that", "which", "to", "of", "it", "can", "be", "if", "do", "this"}

REFUSAL_HINTS = {
    "en": ["only help", "only answer", "can't help", "cannot help", "not able", "don't", "do not",
           "sorry", "unfortunately", "only"],
    "fr": ["uniquement", "seulement", "ne peux", "ne pouvons", "désolé", "malheureusement",
           "ne vend", "pas de", "ne propos"],
}


def answer_language(text: str) -> str | None:
    # Place names are not evidence of a language ("Le Plateau-Mont-Royal",
    # "Notre-Dame-de-Grâce" in an English answer): drop hyphenated names and
    # capitalized words before counting.
    text = re.sub(r"[\wÀ-ÿ']+(?:[-‑‐][\wÀ-ÿ']+)+", " ", text)
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿœŒ]+", text) if not w[0].isupper()]
    words = [w.lower() for w in words]
    fr = sum(w in FRENCH for w in words)
    en = sum(w in ENGLISH for w in words)
    if fr == en:
        return None
    return "fr" if fr > en else "en"


@dataclass
class Result:
    case: Case
    status: int
    answer: str
    sources: list[str]
    latency: float
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


RATE_LIMIT_RETRIES_SECONDS = (15, 30)


def ask(case: Case, client: httpx.Client) -> Result:
    """Ask one question. A provider rate limit (Groq free plan: tokens per
    minute) is not an answer to judge, so it is retried after a wait; the
    latency reported is the one of the final call."""
    for wait in (0, *RATE_LIMIT_RETRIES_SECONDS):
        time.sleep(wait)
        started = time.perf_counter()
        response = client.post(f"{API_URL}/chat", json={"question": case.question})
        latency = time.perf_counter() - started
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if body.get("error") != "rate_limit":
            break
    answer = str(body.get("answer") or "")
    sources = [s.get("url", "") for s in body.get("sources") or []]
    return Result(case, response.status_code, answer, sources, latency, check(case, response.status_code, body))


def check(case: Case, status: int, body: dict) -> list[str]:
    """Every reason the answer fails its case (empty list: it passes)."""
    failures = []
    # Models often write codes with a non-breaking hyphen ("LI‑002", U+2011):
    # same text for a reader, so compare with plain hyphens.
    answer = re.sub(r"[‐‑‒–]", "-", str(body.get("answer") or "")).strip()
    sources = [s.get("url", "") for s in body.get("sources") or []]
    if status != 200:
        failures.append(f"status {status}")
    if body.get("error"):
        failures.append(f"API error: {body['error']}")
    if not answer:
        failures.append("empty answer")
        return failures
    lang = answer_language(answer)
    if lang != case.lang:
        failures.append(f"answer language {lang}, expected {case.lang}")
    if case.refusal:
        if sources:
            failures.append(f"expected no sources, got {sources}")
        if not any(hint in answer.lower() for hint in REFUSAL_HINTS[case.lang]):
            failures.append("answer does not read as a refusal")
    if case.source_any and not any(want in url for url in sources for want in case.source_any):
        failures.append(f"no source matching {case.source_any} in {sources}")
    for group in case.answer_any:
        if not any(want.lower() in answer.lower() for want in group):
            failures.append(f"answer contains none of {group}")
    return failures


def api_is_up() -> bool:
    try:
        return httpx.get(f"{API_URL}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False
