"""One-shot restyle of demo_site/: new header, home page, listing photos,
neighborhood photos, rewritten page titles and the motion/widget scripts.
Facts (prices, fees, addresses, answers) are left untouched."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "demo_site"
HERE = Path(__file__).resolve().parent

NAV = {
    "en": [("buy.html", "Buy"), ("rent.html", "Rent"), ("sell.html", "Sell"), ("listings.html", "Listings"),
           ("neighborhoods.html", "Neighborhoods"), ("fees.html", "Fees"), ("faq.html", "FAQ"), ("about.html", "About")],
    "fr": [("buy.html", "Acheter"), ("rent.html", "Louer"), ("sell.html", "Vendre"), ("listings.html", "Propriétés"),
           ("neighborhoods.html", "Quartiers"), ("fees.html", "Tarifs"), ("faq.html", "FAQ"), ("about.html", "À propos")],
}
CTA = {"en": "Book a visit", "fr": "Réserver une visite"}
NAV_LABEL = {"en": "Main", "fr": "Navigation principale"}

TITLES = {
    "en": {
        "about.html": "An agency built on clarity.",
        "buy.html": "Buying in Montréal, from pre-approval to keys.",
        "contact.html": "Let's talk about your next address.",
        "faq.html": "Questions, answered plainly.",
        "fees.html": "Our fees, in writing, before we start.",
        "listings.html": "Eight addresses, available now.",
        "neighborhoods.html": "Five neighborhoods we know by heart.",
        "rent.html": "Renting a home or an office in Montréal.",
        "sell.html": "Selling at the right price, to the right buyer.",
    },
    "fr": {
        "about.html": "Une agence fondée sur la clarté.",
        "buy.html": "Acheter à Montréal, de la préautorisation aux clés.",
        "contact.html": "Parlons de votre prochaine adresse.",
        "faq.html": "Vos questions, des réponses claires.",
        "fees.html": "Nos tarifs, par écrit, avant de commencer.",
        "listings.html": "Huit adresses, disponibles maintenant.",
        "neighborhoods.html": "Cinq quartiers que nous connaissons par cœur.",
        "rent.html": "Louer un logement ou un bureau à Montréal.",
        "sell.html": "Vendre au juste prix, au bon acheteur.",
    },
}

# id: (type, area slug, price, area label en, area label fr, alt en, alt fr)
LISTINGS = {
    "LI-001": ("sale", "ndg", 1149000, "NDG", "NDG", "Brick semi-detached cottage with a front garden", "Cottage jumelé en brique avec jardin avant"),
    "LI-002": ("rent", "griffintown", 2650, "Griffintown", "Griffintown", "Furnished corner living room above the Lachine Canal", "Salon meublé en coin au-dessus du canal de Lachine"),
    "LI-003": ("sale", "verdun", 789000, "Verdun", "Verdun", "Renovated brick townhouse with a wooden terrace", "Maison de ville rénovée en brique avec terrasse en bois"),
    "LI-004": ("rent", "plateau", 2400, "Plateau", "Plateau", "Empty apartment with high ceilings and hardwood floors", "Appartement vide, hauts plafonds et planchers de bois franc"),
    "LI-005": ("rent", "old-montreal", 5200, "Old Montréal", "Vieux-Montréal", "Open-plan office with exposed brick and timber beams", "Bureau à aire ouverte, brique et poutres apparentes"),
    "LI-006": ("rent", "ndg", 1450, "NDG", "NDG", "Furnished studio with a reading chair", "Studio meublé avec fauteuil de lecture"),
    "LI-007": ("sale", "plateau", 1395000, "Plateau", "Plateau", "Red-brick triplex with a black spiral outdoor staircase", "Triplex en brique rouge avec escalier extérieur en colimaçon"),
    "LI-008": ("sale", "old-montreal", 1250000, "Old Montréal", "Vieux-Montréal", "Roof terrace at dusk above the Old Port", "Terrasse sur le toit au crépuscule au-dessus du Vieux-Port"),
}

HOODS = {
    "plateau": ("n-plateau", "Row of plexes with outdoor staircases", "Rangée de plex avec escaliers extérieurs"),
    "griffintown": ("n-griffintown", "The Lachine Canal path at dawn", "La piste du canal de Lachine à l'aube"),
    "verdun": ("n-verdun", "Riverside park along the St. Lawrence", "Parc riverain le long du Saint-Laurent"),
    "ndg": ("n-ndg", "Leafy street of brick cottages in autumn", "Rue arborée de cottages en brique à l'automne"),
    "old-montreal": ("n-oldmtl", "Cobblestone street in Old Montréal", "Rue pavée du Vieux-Montréal"),
}

ILLUS = {"en": " (illustrative image)", "fr": " (image d'illustration)"}


def header(lang: str, page: str, lang_switch: str) -> str:
    links = []
    for href, label in NAV[lang]:
        cur = ' aria-current="page"' if href == page else ""
        links.append(f'        <a href="{href}"{cur}>{label}</a>')
    cur_cta = ' aria-current="page"' if page == "contact.html" else ""
    brand_cur = ' aria-current="page"' if page == "index.html" else ""
    return (
        '<header class="site-header">\n'
        '    <div class="container header-inner">\n'
        f'      <a class="brand" href="index.html"{brand_cur}>Fleuve <span>Immobilier</span></a>\n'
        '      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="main-nav">'
        '<span class="nav-toggle-bars" aria-hidden="true"></span>Menu</button>\n'
        f'      <nav class="main-nav" id="main-nav" aria-label="{NAV_LABEL[lang]}">\n'
        + "\n".join(links) + "\n"
        f"        {lang_switch}\n"
        f'        <a class="nav-cta" href="contact.html"{cur_cta}>{CTA[lang]}</a>\n'
        "      </nav>\n"
        "    </div>\n"
        "  </header>"
    )


def img_tag(prefix: str, name: str, alt: str, w: int, h: int, extra: str = "") -> str:
    return (f'<img src="{prefix}img/{name}.webp" srcset="{prefix}img/{name}-640.webp 640w, {prefix}img/{name}.webp {w}w" '
            f'sizes="(max-width: 760px) 100vw, 40vw" width="{w}" height="{h}" loading="lazy" decoding="async" alt="{alt}"{extra}>')


def restyle(path: Path) -> None:
    rel = path.relative_to(SITE)
    lang = "fr" if rel.parts[0] == "fr" else "en"
    prefix = "../" if lang == "fr" else ""
    page = rel.name
    s = path.read_text(encoding="utf-8")
    if "nav-toggle" in s:
        print(f"skip (already restyled) {rel}")
        return

    s = s.replace(
        f'<link rel="stylesheet" href="{prefix}styles.css">',
        f'<link rel="preload" href="{prefix}fonts/libre-caslon-display-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
        f'  <link rel="preload" href="{prefix}fonts/hanken-grotesk-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
        f'  <link rel="stylesheet" href="{prefix}styles.css">\n'
        "  <script>document.documentElement.classList.add('js')</script>",
    )

    old_header = re.search(r'<header class="site-header">.*?</header>', s, re.S).group(0)
    lang_switch = re.search(r'<a class="lang-switch"[^>]*>[^<]*</a>', old_header).group(0)
    s = s.replace(old_header, header(lang, page, lang_switch))

    if page == "index.html":
        main = (HERE / f"index-{lang}.main.html").read_text(encoding="utf-8").rstrip("\n")
        s = re.sub(r"  <main id=\"main\">.*?</main>", lambda _: main, s, flags=re.S)
        s = s.replace("<body>", '<body class="has-hero">', 1)
    else:
        title = TITLES[lang].get(page)
        if title:
            s = re.sub(r'(<section class="page-header">\s*<div class="container">\s*)<h1>[^<]*</h1>',
                       lambda m: f"{m.group(1)}<h1>{title}</h1>", s, count=1)

    def listing(m: re.Match) -> str:
        art_id, lid = m.group(1) or "", m.group(4)
        typ, area, price, area_en, area_fr, alt_en, alt_fr = LISTINGS[lid]
        alt = (alt_fr if lang == "fr" else alt_en) + ILLUS[lang]
        label = area_fr if lang == "fr" else area_en
        meta = f'<p class="listing-meta"><span class="listing-area">{label}</span><span class="listing-id">{lid}</span></p>'
        return (
            f'<article class="card listing"{art_id} data-type="{typ}" data-area="{area}" data-price="{price}">\n'
            f'            <figure class="listing-visual">{img_tag(prefix, lid.lower(), alt, 1200, 800)}'
            f'<span class="badge">{m.group(2)}</span></figure>\n'
            '            <div class="listing-body">\n'
            f'              <h3>{m.group(5)}</h3>\n'
            f'              {meta}'
        )

    s = re.sub(
        r'<article class="card listing"( id="LI-\d+")?>\s*<div class="listing-visual[^"]*"><span class="badge">([^<]*)</span><span>([^<]*)</span></div>\s*'
        r'<div class="listing-body">\s*<span class="listing-id">(LI-\d+)</span>\s*<h3>([^<]*)</h3>',
        listing, s)

    if page == "neighborhoods.html":
        def hood(m: re.Match) -> str:
            hid, body = m.group(1), m.group(2)
            name, alt_en, alt_fr = HOODS[hid]
            alt = (alt_fr if lang == "fr" else alt_en) + ILLUS[lang]
            fig = (f'<figure>{img_tag(prefix, name, alt, 800, 1000, " data-parallax-inner")}</figure>')
            return f'<article id="{hid}" class="neighborhood">\n        {fig}\n        <div>{body}</div>\n      </article>'
        s = re.sub(r'<article id="([a-z-]+)">(.*?)</article>', hood, s, flags=re.S)

    if page == "about.html":
        alt = ("Reception of the agency office in a renovated stone building" if lang == "en"
               else "Accueil du bureau de l'agence dans un immeuble de pierre rénové") + ILLUS[lang]
        s = re.sub(r'(<section class="page-header">\s*<div class="container">.*?</p>)',
                   lambda m: m.group(1) + f'\n        <figure class="page-header-media">{img_tag(prefix, "office", alt, 1200, 800, " data-parallax-inner")}</figure>',
                   s, count=1, flags=re.S)

    widget = re.search(r'<script src="http://localhost:8000/widget/widget.js"[^>]*></script>', s).group(0)
    new_widget = widget.replace('data-color="#1e5aa8"', 'data-color="#8b6d47" data-theme="light" data-font="Hanken Grotesk"')
    scripts = (
        f'<script src="{prefix}vendor/lenis.min.js" defer></script>\n'
        f'  <script src="{prefix}vendor/gsap.min.js" defer></script>\n'
        f'  <script src="{prefix}vendor/ScrollTrigger.min.js" defer></script>\n'
        f'  <script src="{prefix}site.js" defer></script>\n'
        f'  <script src="{prefix}motion.js" defer></script>\n'
        f"  {new_widget}"
    )
    s = s.replace(widget, scripts)

    path.write_text(s, encoding="utf-8")
    print(f"restyled {rel}")


if __name__ == "__main__":
    files = sorted(SITE.glob("*.html")) + sorted((SITE / "fr").glob("*.html"))
    for f in files if len(sys.argv) < 2 else [SITE / a for a in sys.argv[1:]]:
        restyle(f)
