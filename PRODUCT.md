# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Visitors of a client's website (first client case: Fleuve Immobilier, a fictional bilingual real estate agency in Montréal) who have a practical question and want the answer without hunting through pages. Secondary audience: the business owner who embeds the widget on their site. (Inferred from the build conversation; not confirmed in an interview.)

## Product Purpose
An embeddable chat widget that answers visitors' questions only from the website's own content (RAG: crawl, chunk, embed, retrieve, answer), in the visitor's language (English or French), and shows the pages it used as sources. Success: the visitor gets a correct, short answer they can verify, or a clear "I don't know, contact the agency".

## Positioning
Answers are grounded in the client's site and cite it: every fact links back to the page it came from.

## Operating Context
Embedded with one `<script>` tag on any client site; the site's own CSS must not affect it (Shadow DOM). Visitors move between pages while chatting, so the conversation persists for the session. Backend: FastAPI `/chat` with an OpenAI-compatible LLM (currently Groq, free plan rate limits).

## Capabilities and Constraints
- Vanilla JavaScript, no framework, no build step.
- Configured by `data-` attributes: API URL, title, brand color (`data-color`), language, theme (`data-theme` light|dark), font (`data-font`, optionally loaded from `data-font-src`), suggested questions.
- Bilingual UI (EN/FR), welcome message, suggested questions, sources under answers, typing indicator, friendly errors.
- Demo data is fictional and must be labeled as such in the widget.

## Brand Commitments
The widget has its own premium signature, "the route" (each answer runs from an origin stop down to numbered source stops), while staying themable per client: the client's colour (`data-color`), name (`data-title`), light or dark theme (`data-theme`) and typeface (`data-font`, `data-font-src`) dress it, and it adds no colour, logo or name of its own.

## Evidence on Hand
Demo site in `demo_site/` (fictional agency, prices, people and listings). No real customers, testimonials or metrics exist; none may be invented.

## Accessibility & Inclusion
Keyboard operable (Enter to send, Escape to close), screen-reader labels, WCAG AA contrast whatever the brand color.
