"""RAG pipeline: retrieves the most relevant chunks for a question from
ChromaDB and asks the LLM to answer using only that context, with sources."""

from __future__ import annotations

import argparse
import logging
import re
from functools import lru_cache

import openai
from openai import OpenAI

from app.config import get_settings
from app.indexer import search

logger = logging.getLogger(__name__)

TOP_K = 5
# Below this many same-language chunks, other-language chunks fill the rest.
MIN_SAME_LANGUAGE = 3
HISTORY_MESSAGES = 4
# Room for a short answer, plus the hidden "thinking" of reasoning models.
MAX_ANSWER_TOKENS = 1000
LLM_TIMEOUT_SECONDS = 30.0

SYSTEM_PROMPT = """You are the assistant on the website of a real estate agency. You answer visitors' questions using ONLY the numbered sources provided with each question. The sources are extracts from the agency's website.

Rules:
1. Always reply in the language of the visitor's latest question (English or French), even when the sources are in the other language. This also applies when you say you don't know or that you can't help.
2. Use only facts found in the sources. Never use outside knowledge and never invent prices, fees, dates, names, addresses or phone numbers.
3. If the sources do not contain the answer, say clearly that you don't know, and suggest contacting the agency (give its contact details only if they appear in the sources). If the question has nothing to do with the agency or its services (weather, news, general knowledge...), say politely that you can only help with questions about the agency and its services.
4. Keep answers short: two to four sentences, or a short list.
5. Cite your sources inline with their numbers, like [1] or [2], right after the facts they support. Every answer that uses a source must contain at least one citation.
6. When the answer is about laws, taxes or procedures, say that it is general information, not legal advice."""

# "[1]", "[2, 3]" or "[1][3]" in the model's answer.
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# gpt-oss models sometimes cite with full-width brackets: "【1】", "【1†source】".
WIDE_CITATION = re.compile(r"【\s*(\d+(?:\s*,\s*\d+)*)[^】]*】")

# Small, frequent words of each language. Counting them is more reliable
# than looking for accents: "What is the weather in Montréal?" is English.
FRENCH_WORDS = {
    "le", "la", "les", "un", "une", "des", "du", "est", "sont", "je", "j", "vous", "votre", "vos",
    "nous", "notre", "il", "elle", "ce", "c", "qui", "que", "qu", "quoi", "quel", "quelle", "quels",
    "quelles", "combien", "comment", "pourquoi", "où", "pour", "avec", "dans", "sur", "peut", "peux",
    "faut", "fait", "et", "ou", "mais", "pas", "bonjour", "merci", "louer", "acheter", "vendre",
    "moi", "parlez", "dites", "svp", "y", "a-t-il",
}
ENGLISH_WORDS = {
    "the", "a", "an", "is", "are", "do", "does", "can", "i", "you", "your", "we", "our", "it", "what",
    "which", "who", "how", "why", "where", "when", "for", "with", "in", "on", "of", "to", "and", "or",
    "but", "not", "hello", "thanks", "rent", "buy", "sell", "me", "my", "about", "tell", "please",
    "much", "many", "there", "have",
}

ERROR_MESSAGES = {
    "timeout": (
        "The assistant is taking too long to answer. Please try again in a moment.",
        "L'assistant met trop de temps à répondre. Merci de réessayer dans un instant.",
    ),
    "auth": (
        "The assistant is not configured correctly (invalid API key). Please contact the agency directly.",
        "L'assistant n'est pas configuré correctement (clé d'API invalide). Merci de contacter l'agence directement.",
    ),
    "rate_limit": (
        "The assistant is receiving too many questions right now. Please try again in a minute.",
        "L'assistant reçoit trop de questions en ce moment. Merci de réessayer dans une minute.",
    ),
    "unavailable": (
        "The assistant is temporarily unavailable. Please try again later or contact the agency directly.",
        "L'assistant est temporairement indisponible. Merci de réessayer plus tard ou de contacter l'agence directement.",
    ),
    "no_index": (
        "The assistant is not ready yet: the website has not been indexed.",
        "L'assistant n'est pas encore prêt : le site n'a pas encore été indexé.",
    ),
    "empty": (
        "Please type a question.",
        "Merci de saisir une question.",
    ),
}


@lru_cache
def _get_client() -> OpenAI:
    """OpenAI-compatible client; with the default settings it talks to the
    Hugging Face router, authenticated with the HF token."""
    settings = get_settings()
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _detect_language(text: str) -> str | None:
    """"fr", "en", or None when the text gives no clear signal.

    Proper names are skipped ("Tell me about Notre-Dame-de-Grâce" is English):
    capitalized hyphenated names, and capitalized words after the first one.
    """
    text = re.sub(r"(?<!^)\b[A-ZÀ-Ý][\w']*(?:-[\w']+)+", " ", text.strip())
    tokens = re.findall(r"[A-Za-zÀ-ÿœŒ]+", text)
    words = [t.lower() for i, t in enumerate(tokens) if i == 0 or not t[0].isupper()]
    french = sum(word in FRENCH_WORDS for word in words)
    english = sum(word in ENGLISH_WORDS for word in words)
    if french > english:
        return "fr"
    if english > french:
        return "en"
    return None


def _error(kind: str, question: str) -> dict:
    english, french = ERROR_MESSAGES[kind]
    message = french if _detect_language(question) == "fr" else english
    return {"answer": message, "sources": [], "error": kind}


def _format_sources(results: list[dict]) -> str:
    """Number the retrieved chunks so the model can cite them as [1], [2]..."""
    blocks = []
    for n, result in enumerate(results, 1):
        label = " > ".join(part for part in (result["title"], result["heading"]) if part)
        blocks.append(f"[{n}] {label} ({result['url']})\n{result['text']}")
    return "\n\n".join(blocks)


def _history_messages(history: list[dict] | None) -> list[dict]:
    """The last few turns, so follow-ups like "and for renting?" make sense.

    Old answers are kept without their [n] markers: those numbers referred
    to the sources of an earlier question, not to the ones sent now.
    """
    messages = []
    for message in history or []:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if role == "assistant":
            content = re.sub(r"\s+([.,;:!?])", r"\1", CITATION.sub("", content)).strip()
        messages.append({"role": role, "content": content[:2000]})
    return messages[-HISTORY_MESSAGES:]


TRANSLATE_PROMPT = (
    "You translate a website visitor's question from French to English, to be used as a search query. "
    "Keep names, places, reference codes (like LI-004), numbers and amounts unchanged. "
    "Reply with the English question only, nothing else."
)


def _translate_for_search(question: str) -> str | None:
    """English version of a French question, used for search only.

    The embedding model (all-MiniLM-L6-v2) is trained mostly on English, so a
    French question matches English pages poorly. Searching with an English
    translation as well finds them. Returns None if the call fails: search
    then simply uses the original question.
    """
    settings = get_settings()
    options = {}
    if settings.llm_reasoning_effort:
        options["reasoning_effort"] = settings.llm_reasoning_effort
    try:
        response = _get_client().with_options(timeout=10.0, max_retries=0).chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": TRANSLATE_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=300,  # a short sentence, plus a reasoning model's thinking
            **options,
        )
    except openai.OpenAIError as exc:
        logger.warning("Search translation failed, using the French question only: %s", exc)
        return None

    text = (response.choices[0].message.content or "").strip().strip('"«»“”').strip()
    text = text.splitlines()[0].strip() if text else ""
    if not text or text.lower() == question.lower():
        return None
    logger.info("Search query translated: %r -> %r", question, text)
    return text


def _interleave(result_lists: list[list[dict]], limit: int) -> list[dict]:
    """Take results from each list in turn (1st of each, then 2nd of each...),
    skip chunks already taken, and stop at `limit`."""
    merged: dict[str, dict] = {}
    for rank in range(max((len(r) for r in result_lists), default=0)):
        for results in result_lists:
            if rank < len(results):
                merged.setdefault(results[rank]["id"], results[rank])
    return list(merged.values())[:limit]


def _prefer_language(results: list[dict], lang: str | None, limit: int) -> list[dict]:
    """Chunks in the question's language first, in their original order.

    When at least MIN_SAME_LANGUAGE chunks match, only those are kept, so a
    French question cites the /fr/ pages; with fewer, the other language
    fills the remaining places as a fallback.
    """
    if not lang:
        return results[:limit]
    same = [r for r in results if r.get("lang") == lang]
    if len(same) >= MIN_SAME_LANGUAGE:
        return same[:limit]
    return (same + [r for r in results if r.get("lang") != lang])[:limit]


def _retrieve(question: str, history: list[dict] | None) -> list[dict]:
    """Find the TOP_K chunks for the question.

    Searches, merged by alternating their results:
    - the question itself, across the whole site and within the pages in
      the question's language;
    - its English translation when the question is in French (see
      _translate_for_search), again site-wide and within the French pages:
      the translation matches the English pages best, while the French
      pages are the ones a French visitor should be sent to;
    - for follow-ups, the earlier questions plus this one: "Is heating
      included?" doesn't say *what* it is about, so on its own it finds
      nothing about listing LI-004.
    The question's own results come first, so a change of topic still gets
    results for the new question. The merged pool is then re-ranked so the
    question's language comes first (see _prefer_language).
    """
    lang = _detect_language(question)
    queries = [question]
    if lang == "fr":
        english = _translate_for_search(question)
        if english:
            queries.append(english)

    result_lists = []
    for query in queries:
        result_lists.append(search(query, k=TOP_K))
        if lang:
            result_lists.append(search(query, k=TOP_K, lang=lang))

    earlier = [m["content"] for m in _history_messages(history) if m["role"] == "user"]
    if earlier:
        result_lists.append(search("\n".join([*earlier, question]), k=TOP_K, lang=lang))

    return _prefer_language(_interleave(result_lists, TOP_K * 3), lang, TOP_K)


def _cited_numbers(answer: str, available: int) -> list[int]:
    numbers = {int(n) for group in CITATION.findall(answer) for n in group.split(",")}
    return sorted(n for n in numbers if 1 <= n <= available)


def _long_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zàâçéèêëîïôûùüÿœ0-9$%]+", text.lower()) if len(w) >= 5}


def _implicit_sources(answer: str, results: list[dict]) -> list[int]:
    """Sources an answer clearly uses even though the model forgot to cite them.

    Small models sometimes skip the [n] markers. A source counts as used when
    the answer shares at least half of its long words (and 5 or more) with
    it. "I don't know" answers share almost nothing, so they get no source.
    """
    words = _long_words(answer)
    if len(words) < 5:
        return []
    used = []
    for n, result in enumerate(results, 1):
        shared = words & _long_words(result["text"])
        if len(shared) >= 5 and len(shared) / len(words) >= 0.5:
            used.append(n)
    return used


def answer(question: str, history: list[dict] | None = None) -> dict:
    """Answer a visitor's question from the indexed website.

    Returns {"answer": str, "sources": [{"n", "title", "heading", "url"}]}
    with only the sources the answer cites. On failure, "answer" holds a
    short message for the visitor and "error" says what went wrong.
    """
    question = (question or "").strip()
    if not question:
        return _error("empty", question)

    # No score threshold: MiniLM similarities are low even for good matches,
    # and exact-reference matches (e.g. "LI-007") score close to 0.
    try:
        results = _retrieve(question, history)
    except RuntimeError:
        return _error("no_index", question)

    # Small models sometimes drift to English (the language of the prompt),
    # so we also state the expected language next to the question.
    language = {"fr": "\n\nAnswer in French.", "en": "\n\nAnswer in English."}.get(_detect_language(question) or "", "")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": f"Sources:\n\n{_format_sources(results)}\n\nQuestion: {question}{language}"},
    ]

    settings = get_settings()
    options = {}
    if settings.llm_reasoning_effort:
        options["reasoning_effort"] = settings.llm_reasoning_effort
    try:
        response = _get_client().chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0.2,
            max_tokens=MAX_ANSWER_TOKENS,
            **options,
        )
    except openai.APITimeoutError:
        logger.warning("LLM timeout")
        return _error("timeout", question)
    except openai.AuthenticationError:
        logger.error("LLM rejected the API key (401): check OPENAI_API_KEY")
        return _error("auth", question)
    except openai.RateLimitError:
        logger.warning("LLM rate limit reached (429)")
        return _error("rate_limit", question)
    except openai.APIStatusError as exc:
        if exc.status_code == 402:
            logger.error("LLM provider asks for payment (402): no credits left on this account")
        else:
            logger.error("LLM call failed: %s", exc)
        return _error("unavailable", question)
    except openai.APIConnectionError as exc:
        logger.error("Could not reach the LLM at %s: %s", settings.openai_base_url, exc)
        return _error("unavailable", question)

    text = WIDE_CITATION.sub(r"[\1]", response.choices[0].message.content or "").strip()
    if not text:
        return _error("unavailable", question)

    cited = _cited_numbers(text, len(results)) or _implicit_sources(text, results)
    sources = [
        {
            "n": n,
            "title": results[n - 1]["title"],
            "heading": results[n - 1]["heading"],
            "url": results[n - 1]["url"],
        }
        for n in cited
    ]
    return {"answer": text, "sources": sources}


def main() -> None:
    """Command line: python -m app.rag "What is your commission when I sell?" """
    from app.indexer import setup_cli_logging

    parser = argparse.ArgumentParser(description="Ask the website assistant a question.")
    parser.add_argument("question", help='e.g. "What is your commission when I sell?"')
    args = parser.parse_args()
    setup_cli_logging()

    result = answer(args.question)
    print(f"\n{result['answer']}\n")
    if result["sources"]:
        print("Sources:")
        for source in result["sources"]:
            label = " > ".join(part for part in (source["title"], source["heading"]) if part)
            print(f"  [{source['n']}] {label}\n      {source['url']}")
    if result.get("error"):
        print(f"(error: {result['error']})")


if __name__ == "__main__":
    main()
