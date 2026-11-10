"""Chunker: splits extracted page text into overlapping chunks sized for
embedding, preserving source metadata for citations."""

from __future__ import annotations

import argparse
import logging
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Why we clean: menus, headers and footers are repeated on every page, and
# scripts/styles aren't readable text. If we kept them, every chunk would
# contain "Home Buy Rent Sell..." and a search would match the menu instead
# of the real answer. Cleaning keeps only the content that answers questions.
REMOVED_TAGS = ("nav", "header", "footer", "script", "style", "noscript", "template", "svg")

# Form controls are UI, not content: a search form's options ("Up to
# $800,000") would otherwise read like facts the site states.
CONTROL_TAGS = ("select", "option", "button", "input", "textarea")

# Class or id fragments that usually mean "site chrome", not content.
NOISE_WORDS = ("nav", "menu", "footer", "cookie")

# Never delete these, even if their class or id contains a noise word
# (e.g. <body class="has-nav">), or we would lose the whole page.
PROTECTED_TAGS = {"html", "body", "main", "article"}

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}

# Tags whose text is one paragraph of its own.
TEXT_BLOCK_TAGS = {
    "p", "dt", "dd", "h4", "h5", "h6",
    "blockquote", "pre", "caption", "figcaption", "address",
}

# Tags that live inside a sentence (links, bold...): their text joins the
# surrounding text instead of starting a new paragraph.
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "dfn", "em",
    "i", "img", "kbd", "label", "mark", "q", "s", "samp", "small", "span",
    "strong", "sub", "sup", "time", "u", "var", "wbr",
}

EMPTY_CELLS = {"", "-", "–", "—"}

HEADING_LINE = re.compile(r"^(#{1,3}) (.+)$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _clean(text: str) -> str:
    """Collapse all runs of spaces, tabs and newlines into single spaces."""
    return " ".join(text.split())


def _join(parts: list[str]) -> str:
    """Glue text pieces as a browser would, then collapse whitespace.

    A space is added between two pieces only when both touch on a letter or
    digit ("For sale" + "NDG" -> "For sale NDG"), so links don't get stray
    spaces before punctuation ("contact page" + ", and" -> "contact page, and").
    """
    out = ""
    for part in parts:
        if out and part and not out[-1].isspace() and not part[0].isspace():
            if out[-1].isalnum() and part[0].isalnum():
                out += " "
        out += part
    return _clean(out)


def _text(node: Tag) -> str:
    """All the text inside a tag, joined with `_join`."""
    return _join([str(s) for s in node.find_all(string=True) if not isinstance(s, Comment)])


# ---------------------------------------------------------------------------
# 1. HTML -> clean text
# ---------------------------------------------------------------------------


def clean_html(html: str) -> str:
    """Turn a page's HTML into clean text, one paragraph per block.

    Headings stay on their own line, marked "#", "##", "###" (h1-h3) so the
    chunker can split on them; FAQ questions (<summary>) count as "###".
    Paragraphs are separated by a blank line.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove site chrome and non-text tags. A <header>/<footer> inside an
    # article or <main> is part of the content (e.g. an article's title), so
    # we keep those.
    for tag in soup.find_all(REMOVED_TAGS):
        if tag.decomposed:
            continue
        if tag.name in ("header", "footer") and tag.find_parent(["article", "main"]):
            continue
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "search"}) + soup.find_all(CONTROL_TAGS):
        if not tag.decomposed:
            tag.decompose()

    # Remove elements whose class or id looks like a menu, footer or cookie
    # banner, unless they wrap the main content.
    for tag in soup.find_all(True):
        if tag.decomposed or tag.name in PROTECTED_TAGS:
            continue
        names = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
        if any(word in names.lower() for word in NOISE_WORDS) and not tag.find("main"):
            tag.decompose()

    # Prefer <main>: on most sites it holds exactly the page's own content.
    root = soup.find("main") or soup.body or soup
    return "\n\n".join(_blocks(root))


def _blocks(node: Tag) -> list[str]:
    """Walk the HTML tree and return its text as a list of paragraphs."""
    blocks: list[str] = []
    inline: list[str] = []  # loose text waiting to become a paragraph
    has_plain_text = False  # False while the loose text is only link text

    def flush() -> None:
        nonlocal has_plain_text
        text = _join(inline)
        # Loose text made only of links ("See all listings", "View details")
        # is a button or a menu, not content.
        if text and has_plain_text:
            blocks.append(text)
        inline.clear()
        has_plain_text = False

    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            inline.append(str(child))
            has_plain_text = has_plain_text or bool(child.strip())
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name
        if name in INLINE_TAGS:
            text = _text(child)
            inline.append(text)
            has_plain_text = has_plain_text or (name != "a" and bool(text))
            continue

        flush()
        if name in HEADING_LEVELS:
            text = _text(child)
            if text:
                blocks.append("#" * HEADING_LEVELS[name] + " " + text)
        elif name == "summary":
            # An FAQ question: treat it as a small heading so that each
            # question and its answer become their own section.
            text = _text(child)
            if text:
                blocks.append("### " + text)
        elif name == "table":
            blocks.extend(_table_lines(child))
        elif name == "dl":
            blocks.extend(_definition_lines(child))
        elif name == "li":
            blocks.extend(_list_item(child))
        elif name in TEXT_BLOCK_TAGS:
            text = _text(child)
            if text and not (name == "p" and _is_link_list(child, text)):
                blocks.append(text)
        else:
            # A container (div, section, ul, details...): look inside it.
            blocks.extend(_heading_first(_blocks(child)))

    flush()
    return blocks


def _is_link_list(paragraph: Tag, text: str) -> bool:
    """True for a short paragraph that is mostly a list of links, like
    "See also: listings, neighborhoods, buying, renting, selling".

    These "where to go next" lines are navigation: they add noise to the
    chunk they end up in and pull unrelated questions towards it. Real
    content rarely packs 4+ links into a few short sentences.
    """
    links = paragraph.find_all("a")
    if len(links) < 4 or len(text) > 400:
        return False
    link_chars = sum(len(_text(a)) for a in links)
    return link_chars / len(text) >= 0.25


def _heading_first(blocks: list[str]) -> list[str]:
    """Move short labels that come just before a container's heading to after it.

    Cards often put a badge or an ID above their title ("For sale", "LI-001",
    then "<h3>Cottage</h3>"). Those labels belong to that card, not to the
    section before it, so the heading must come first.
    """
    for i, block in enumerate(blocks):
        if HEADING_LINE.match(block):
            if 0 < i and sum(len(b) for b in blocks[:i]) <= 120:
                return [block] + blocks[:i] + blocks[i + 1:]
            return blocks
    return blocks


def _list_item(li: Tag) -> list[str]:
    """A list item as "- text". A leading bold title gets a colon:
    "<strong>Valuation</strong>We visit..." -> "- Valuation: We visit..."."""
    blocks = _blocks(li)
    if not blocks:
        return []

    first = next((c for c in li.children if not (isinstance(c, NavigableString) and not c.strip())), None)
    if isinstance(first, Tag) and first.name in ("strong", "b"):
        lead = _text(first)
        rest = blocks[0][len(lead):].lstrip()
        if lead and blocks[0].startswith(lead) and rest[:1].isalnum():
            separator = " " if lead[-1] in ":.!?–—-" else ": "
            blocks[0] = f"{lead}{separator}{rest}"

    blocks[0] = "- " + blocks[0]
    return blocks


def _table_lines(table: Tag) -> list[str]:
    """Write each table row as one self-contained line.

    Plain text would put every cell on its own line and lose which price
    belongs to which service. Instead:
    "- Commission, exclusive contract — Fee: 4% — Paid by / when: Seller"
    """
    lines: list[str] = []
    caption = table.find("caption")
    if caption:
        text = _text(caption)
        if text:
            lines.append(text)

    rows = table.find_all("tr")
    headers: list[str] = []
    if rows and all(cell.name == "th" for cell in rows[0].find_all(["th", "td"], recursive=False)):
        headers = [_text(c) for c in rows[0].find_all("th", recursive=False)]
        rows = rows[1:]

    for row in rows:
        cells = [_text(c) for c in row.find_all(["th", "td"], recursive=False)]
        if not any(c not in EMPTY_CELLS for c in cells):
            continue
        if headers and len(headers) == len(cells):
            parts = [cells[0]] + [
                f"{header}: {value}"
                for header, value in zip(headers[1:], cells[1:])
                if value not in EMPTY_CELLS
            ]
            lines.append("- " + " — ".join(parts))
        else:
            lines.append("- " + " | ".join(c for c in cells if c not in EMPTY_CELLS))
    return lines


def _definition_lines(dl: Tag) -> list[str]:
    """<dt>Phone</dt><dd>+1 514...</dd> -> "- Phone: +1 514..."."""
    lines: list[str] = []
    term: str | None = None
    term_used = False
    for child in dl.find_all(["dt", "dd"]):
        text = _text(child)
        if child.name == "dt":
            if term and not term_used:
                lines.append(f"- {term}")
            term, term_used = text, False
        elif text:
            lines.append(f"- {term}: {text}" if term else f"- {text}")
            term_used = True
    if term and not term_used:
        lines.append(f"- {term}")
    return lines


# ---------------------------------------------------------------------------
# 2. Clean text -> chunks
# ---------------------------------------------------------------------------


def chunk_page(page: dict, chunk_size: int = 800, overlap: int = 120) -> list[dict]:
    """Split one crawled page into chunks of about `chunk_size` characters.

    Each chunk: {"id", "text", "url", "title", "heading"}. "heading" is the
    path of section titles above the chunk, e.g. "Our fees > Selling".
    """
    text = clean_html(page["html"])
    chunks: list[dict] = []

    # Split by headings first: a section is about one topic, so a chunk
    # never mixes, say, selling fees with renting fees.
    for heading, paragraphs in _sections(text):
        for body in _merge(paragraphs, chunk_size, overlap):
            chunks.append({
                "id": f"{page['url']}#{len(chunks)}",
                "text": body,
                "url": page["url"],
                "title": page["title"],
                "heading": heading,
            })
    return chunks


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Group paragraphs under the heading path they belong to."""
    sections: list[tuple[str, list[str]]] = []
    path: list[str] = []  # current [h1, h2, h3] titles
    paragraphs: list[str] = []

    for block in text.split("\n\n"):
        match = HEADING_LINE.match(block)
        if not match:
            paragraphs.append(block)
            continue
        if paragraphs:
            sections.append((" > ".join(path), paragraphs))
            paragraphs = []
        level = len(match.group(1))
        path = path[: level - 1] + [match.group(2)]

    if paragraphs:
        sections.append((" > ".join(path), paragraphs))
    return sections


def _merge(paragraphs: list[str], size: int, overlap: int) -> list[str]:
    """Pack paragraphs into chunks of at most `size` characters.

    Why overlap: when a long section is cut in two, the sentence at the cut
    loses its context ("It is paid at the signing" — what is "it"?). Repeating
    the end of the previous chunk at the start of the next one keeps that
    context, so a search can still match the idea that spans the cut.
    """
    # Each piece remembers how it joins the text before it: a blank line
    # between paragraphs, a line break between two list items, a space
    # between two halves of one long paragraph.
    pieces: list[tuple[str, str]] = []
    previous = ""
    for paragraph in paragraphs:
        joiner = "\n" if paragraph.startswith("- ") and previous.startswith("- ") else "\n\n"
        if len(paragraph) <= size:
            pieces.append((paragraph, joiner))
        else:
            # Leave room for the overlap so the next chunk still fits.
            parts = _split_long(paragraph, max(size - overlap, 1))
            pieces.append((parts[0], joiner))
            pieces.extend((part, " ") for part in parts[1:])
        previous = paragraph

    chunks: list[str] = []
    current = ""
    for piece, joiner in pieces:
        if not current:
            current = piece
            continue
        if len(current) + len(joiner) + len(piece) <= size:
            current += joiner + piece
            continue

        # The chunk is full: close it, and start the next one with the end of
        # this one (the overlap), as long as everything still fits in `size`.
        chunks.append(current)
        room = size - len(piece) - len(joiner)
        tail = _tail(current, overlap, max_size=min(room, overlap * 3 // 2)) if room >= 20 else ""
        current = tail + joiner + piece if tail else piece

    if current:
        chunks.append(current)
    return chunks


def _split_long(paragraph: str, limit: int) -> list[str]:
    """Split a paragraph longer than `limit`, at sentence ends when possible,
    otherwise between words. Never cuts inside a word."""
    units: list[str] = []
    for sentence in SENTENCE_END.split(paragraph):
        units.extend([sentence] if len(sentence) <= limit else sentence.split())

    parts: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}" if current else unit
        if len(candidate) <= limit or not current:
            current = candidate
        else:
            parts.append(current)
            current = unit
    if current:
        parts.append(current)
    return parts


def _tail(text: str, size: int, max_size: int | None = None) -> str:
    """The end of `text` to repeat as overlap: about `size` characters,
    never more than `max_size`.

    It starts at the beginning of a line or sentence when one is close
    enough, so the overlap reads naturally ("- First month's rent: ..."
    rather than "what is included (heating, ..."). Otherwise it starts on a
    whole word.
    """
    max_size = size if max_size is None else max_size
    if size <= 0 or max_size <= 0:
        return ""
    if len(text) <= min(size, max_size):
        return text

    # Line and sentence starts in the last `max_size` characters; keep the
    # one whose overlap length is closest to `size`.
    window_start = max(len(text) - max_size, 0)
    starts = [window_start] if window_start == 0 or text[window_start - 1] == "\n" else []
    starts += [
        window_start + m.start(1)
        for m in re.finditer(r"(?:\n|[.!?]\s)\s*(\S)", text[window_start:])
    ]
    starts = [s for s in starts if len(text) - s >= size // 3]
    if starts:
        best = min(starts, key=lambda s: abs((len(text) - s) - size))
        return text[best:].strip()

    size = min(size, max_size)
    start = len(text) - size
    if not text[start - 1].isspace():
        next_space = re.search(r"\s", text[start:])
        if not next_space:
            return ""
        start += next_space.end()
    return text[start:].strip()


# ---------------------------------------------------------------------------
# 3. Command line
# ---------------------------------------------------------------------------


def main() -> None:
    """Command line: python -m app.chunker http://localhost:8766/index.html"""
    from app.crawler import crawl

    parser = argparse.ArgumentParser(description="Crawl a site, chunk its pages and show examples.")
    parser.add_argument("url", help="Start URL, e.g. http://localhost:8766/index.html")
    parser.add_argument("--max-pages", type=int, default=None, help="Page limit (default: MAX_PAGES)")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--overlap", type=int, default=120)
    parser.add_argument("--show", type=int, default=3, help="Number of example chunks to print")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    pages = crawl(args.url, max_pages=args.max_pages)
    chunks = [
        chunk
        for page in pages
        for chunk in chunk_page(page, chunk_size=args.chunk_size, overlap=args.overlap)
    ]

    print(f"\n{len(pages)} page(s) -> {len(chunks)} chunk(s)")
    if not chunks:
        return

    sizes = [len(c["text"]) for c in chunks]
    print(f"Chunk size: min {min(sizes)}, avg {sum(sizes) // len(sizes)}, max {max(sizes)} characters\n")
    for page in pages:
        count = sum(1 for c in chunks if c["url"] == page["url"])
        print(f"  {count:3d}  {page['url']}")

    # Examples spread across the whole site (first, middle, last...).
    show = min(args.show, len(chunks))
    picks = [round(i * (len(chunks) - 1) / max(show - 1, 1)) for i in range(show)]
    for n, index in enumerate(picks, 1):
        chunk = chunks[index]
        print(f"\n{'=' * 72}\nExample {n}/{show}")
        print(f"id:      {chunk['id']}")
        print(f"title:   {chunk['title']}")
        print(f"heading: {chunk['heading']}")
        print(f"length:  {len(chunk['text'])} characters\n{'-' * 72}")
        print(chunk["text"])


if __name__ == "__main__":
    main()
