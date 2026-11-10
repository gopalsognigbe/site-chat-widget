/*
 * Site chat widget — embeddable, framework-free.
 *
 * <script src="https://your-api/widget/widget.js"
 *         data-api="https://your-api" data-title="Company"
 *         data-color="#1e5aa8" data-lang="auto" defer></script>
 *
 * Optional: data-suggestions="Q1|Q2|Q3" and data-suggestions-fr="Q1|Q2|Q3".
 * Optional: data-label="Ask our assistant" and data-label-fr="…" (launcher text).
 * Optional: data-theme="light|dark", data-font="Family name" (a font the host
 * page already loads), data-font-src="https://…/font.woff2" (loaded for you).
 */
(function () {
  "use strict";

  if (window.__siteChatWidget) return;
  window.__siteChatWidget = true;

  // ---------------------------------------------------------------------------
  // Config
  // ---------------------------------------------------------------------------

  var script =
    document.currentScript ||
    Array.prototype.slice.call(document.querySelectorAll("script[src]")).filter(function (s) {
      return /widget\.js(\?|#|$)/.test(s.src);
    })[0];
  var data = (script && script.dataset) || {};

  var API = (data.api || (script ? new URL(script.src, location.href).origin : location.origin)).replace(/\/+$/, "");
  var TITLE = data.title || document.title || "Assistant";
  var BRAND = normalizeHex(data.color) || "#1e5aa8";
  var LANG = pickLanguage(data.lang);
  var THEME = data.theme === "dark" ? "dark" : "light";
  var FONT = cleanFontName(data.font);
  var FONT_SRC = data.fontSrc && safeUrl(data.fontSrc);
  var STORAGE_KEY = "site-chat-widget:" + API;
  var HISTORY_SENT = 6;
  var MAX_STORED = 60;
  var REQUEST_TIMEOUT_MS = 45000;

  var TEXT = {
    en: {
      launcher: data.label || "Ask our assistant",
      open: (data.label || "Ask our assistant") + ", " + TITLE,
      close: "Close chat",
      subtitle: "Answers from this website",
      welcome: "Hello, I'm the " + TITLE + " assistant. Ask me anything about this website: every answer links to the pages it comes from.",
      suggestionsLabel: "Suggested questions",
      placeholder: "Ask about this website…",
      inputLabel: "Your question",
      send: "Send",
      reset: "Start a new conversation",
      typing: "The assistant is writing an answer",
      sources: "Sources",
      source: "Source",
      footer: "Demo – fictional data",
      network: "I can't reach the assistant right now. Check your connection, then try again.",
      interrupted: "The previous answer was interrupted.",
      retry: "Try again",
      you: "You",
      bot: "Assistant",
      suggestions: ["What services do you offer?", "What are your fees?", "How can I contact you?"],
    },
    fr: {
      launcher: data.labelFr || "Posez votre question",
      open: (data.labelFr || "Posez votre question") + ", " + TITLE,
      close: "Fermer le chat",
      subtitle: "Réponses tirées de ce site",
      welcome: "Bonjour, je suis l'assistant de " + TITLE + ". Posez-moi vos questions sur ce site : chaque réponse renvoie aux pages d'où elle vient.",
      suggestionsLabel: "Questions suggérées",
      placeholder: "Posez une question sur ce site…",
      inputLabel: "Votre question",
      send: "Envoyer",
      reset: "Nouvelle conversation",
      typing: "L'assistant rédige une réponse",
      sources: "Sources",
      source: "Source",
      footer: "Démo – données fictives",
      network: "Impossible de joindre l'assistant pour le moment. Vérifiez votre connexion, puis réessayez.",
      interrupted: "La réponse précédente a été interrompue.",
      retry: "Réessayer",
      you: "Vous",
      bot: "Assistant",
      suggestions: ["Quels services proposez-vous ?", "Quels sont vos tarifs ?", "Comment vous contacter ?"],
    },
  }[LANG];

  var customSuggestions = LANG === "fr" ? data.suggestionsFr : data.suggestions;
  var SUGGESTIONS = customSuggestions
    ? customSuggestions.split("|").map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 3)
    : TEXT.suggestions;

  function cleanFontName(value) {
    var v = String(value || "").replace(/["';{}<>\\]/g, "").trim();
    return v ? v.slice(0, 60) : null;
  }

  function pickLanguage(value) {
    var v = (value || "auto").toLowerCase();
    if (v === "fr" || v === "en") return v;
    // "auto": the page's own language first (a bilingual site's /fr/ pages),
    // then the browser's.
    var pageLang = (document.documentElement.lang || "").toLowerCase();
    if (/^(fr|en)\b/.test(pageLang)) return pageLang.slice(0, 2);
    var langs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "en"];
    return /^fr\b/i.test(langs[0] || "") ? "fr" : "en";
  }

  // ---------------------------------------------------------------------------
  // Colour: derive readable tones from any brand colour
  // ---------------------------------------------------------------------------

  function normalizeHex(value) {
    if (!value) return null;
    var v = String(value).trim();
    if (/^#[0-9a-f]{3}$/i.test(v)) v = "#" + v[1] + v[1] + v[2] + v[2] + v[3] + v[3];
    return /^#[0-9a-f]{6}$/i.test(v) ? v.toLowerCase() : null;
  }

  function hexToRgb(hex) {
    var n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function rgbToHex(rgb) {
    return "#" + rgb.map(function (c) { return ("0" + Math.round(c).toString(16)).slice(-2); }).join("");
  }

  function mix(hex, otherHex, amount) {
    var a = hexToRgb(hex), b = hexToRgb(otherHex);
    return rgbToHex(a.map(function (c, i) { return c + (b[i] - c) * amount; }));
  }

  function luminance(hex) {
    return hexToRgb(hex).reduce(function (sum, c, i) {
      var s = c / 255;
      s = s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      return sum + s * [0.2126, 0.7152, 0.0722][i];
    }, 0);
  }

  function contrast(a, b) {
    var la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }

  var PALETTE = {
    light: { surface: "#ffffff", tone: "#f5f3f0", ink: "#1a1917", muted: "#625d56", line: "#e5e1db", control: "#8f887e", voice: "#1a1917", onVoice: "#ffffff", danger: "#a4251c", dangerSoft: "#fbf0ee" },
    dark: { surface: "#151617", tone: "#1e2022", ink: "#f1eee8", muted: "#a8a198", line: "#2f3235", control: "#7c766e", voice: "#f1eee8", onVoice: "#151617", danger: "#f0a59b", dangerSoft: "#2c1d1b" },
  }[THEME];

  // Text on the brand colour: white when it reads, otherwise a dark ink.
  var ON_BRAND = contrast(BRAND, "#ffffff") >= 4.5 ? "#ffffff" : "#111111";
  // Brand used as text or line on the panel: pushed away from the surface
  // (darker on light, lighter on dark) until it passes AA.
  var BRAND_INK = BRAND;
  var away = THEME === "dark" ? "#ffffff" : "#000000";
  for (var step = 0; contrast(BRAND_INK, PALETTE.surface) < 4.5 && step < 20; step++) {
    BRAND_INK = mix(BRAND_INK, away, 0.08);
  }

  if (FONT && FONT_SRC && !document.querySelector("style[data-scw-font]")) {
    var face = document.createElement("style");
    face.setAttribute("data-scw-font", "");
    face.textContent = "@font-face{font-family:\"" + FONT + "\";src:url(\"" + FONT_SRC.replace(/"/g, "%22") + "\") format(\"woff2\");font-weight:400 700;font-display:swap}";
    document.head.appendChild(face);
  }
  var FONT_STACK = (FONT ? "\"" + FONT + "\"," : "") + "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif";

  // ---------------------------------------------------------------------------
  // Icons (authored SVG, 24px grid, 1.8 stroke)
  // ---------------------------------------------------------------------------

  var SVG_NS = "http://www.w3.org/2000/svg";
  var ICONS = {
    chat: ["M5 18.5V6.8A2.8 2.8 0 0 1 7.8 4h8.4A2.8 2.8 0 0 1 19 6.8v6.4a2.8 2.8 0 0 1-2.8 2.8H9.6L5 18.5Z", "M9 9.2h6", "M9 12h3.6"],
    close: ["M6.5 6.5l11 11", "M17.5 6.5l-11 11"],
    send: ["M12 19V5.5", "M6.5 11L12 5.5l5.5 5.5"],
    reset: ["M4.8 12a7.2 7.2 0 1 0 2.1-5.1", "M4.5 4.8v3.6h3.6"],
    retry: ["M19.2 12a7.2 7.2 0 1 1-2.1-5.1", "M19.5 4.8v3.6h-3.6"],
    arrow: ["M5 12h13", "M13 7l5 5-5 5"],
  };

  function icon(name) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    ICONS[name].forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  // ---------------------------------------------------------------------------
  // DOM helper (never uses innerHTML: every string becomes a text node)
  // ---------------------------------------------------------------------------

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
      });
    }
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function safeUrl(url) {
    try {
      var u = new URL(url, location.href);
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Markdown (bold, lists, line breaks, [n] citations) -> DOM nodes
  // ---------------------------------------------------------------------------

  var INLINE = /(\*\*[^*\n]+\*\*|__[^_\n]+__|\[\d+(?:\s*,\s*\d+)*\])/g;
  var LIST_ITEM = /^\s*([-*•]|\d+[.)])\s+(.*)$/;

  function renderInline(text, citeFor) {
    var frag = document.createDocumentFragment();
    text.split(INLINE).forEach(function (part) {
      if (!part) return;
      var bold = /^\*\*([^*]+)\*\*$/.exec(part) || /^__([^_]+)__$/.exec(part);
      if (bold) {
        frag.appendChild(el("strong", { text: bold[1] }));
      } else if (/^\[\d/.test(part)) {
        part.slice(1, -1).split(",").forEach(function (n) {
          var cite = citeFor(parseInt(n, 10));
          if (cite) frag.appendChild(cite);
        });
      } else {
        frag.appendChild(document.createTextNode(typo(part)));
      }
    });
    return frag;
  }

  function renderMarkdown(text, citeFor) {
    var frag = document.createDocumentFragment();
    var lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    var paragraph = [];
    var list = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      var p = el("p");
      paragraph.forEach(function (line, i) {
        if (i) p.appendChild(el("br"));
        p.appendChild(renderInline(line, citeFor));
      });
      frag.appendChild(p);
      paragraph = [];
    }

    lines.forEach(function (raw) {
      var line = raw.replace(/\s+$/, "").replace(/^#{1,6}\s+/, "");
      var item = LIST_ITEM.exec(line);
      if (item) {
        flushParagraph();
        var ordered = /\d/.test(item[1]);
        if (!list || list.ordered !== ordered) {
          list = { ordered: ordered, node: el(ordered ? "ol" : "ul") };
          frag.appendChild(list.node);
        }
        list.node.appendChild(el("li", null, [renderInline(item[2], citeFor)]));
      } else if (!line.trim()) {
        flushParagraph();
        list = null;
      } else {
        list = null;
        paragraph.push(line.trim());
      }
    });
    flushParagraph();
    return frag;
  }

  function shortTitle(title) {
    // "Our fees – Fleuve Immobilier" -> "Our fees"
    var parts = String(title || "").split(/\s+[–—|-]\s+/);
    return parts.length > 1 ? parts.slice(0, -1).join(" – ") : String(title || "");
  }

  function sourceParts(source) {
    // The page is named by its <title> (the name the site gives it in tabs
    // and search results), the section by the last heading of the chunk:
    // "Our fees" · "Selling". Marketing h1s are often a sentence, not a name.
    var path = String(source.heading || "").split(" > ").filter(Boolean);
    return {
      page: shortTitle(source.title) || path[0] || "",
      section: path.length > 1 ? path[path.length - 1] : "",
    };
  }

  function sourceText(source) {
    var parts = sourceParts(source);
    return parts.section ? parts.page + " — " + parts.section : parts.page;
  }

  // Keep "?", "!", ":", ";" attached to the word before them (French puts a
  // space there, and a lone "?" must never start a line).
  function typo(text) {
    return String(text).replace(/ ([?!:;»])/g, "\u00a0$1").replace(/« /g, "«\u00a0");
  }

  // ---------------------------------------------------------------------------
  // State (kept in sessionStorage so it survives page navigation)
  // ---------------------------------------------------------------------------

  var state = load();

  function load() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
      if (saved && Array.isArray(saved.messages)) return { open: !!saved.open, messages: saved.messages };
    } catch (e) { /* storage blocked or corrupt: start fresh */ }
    return { open: false, messages: [] };
  }

  function save() {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ open: state.open, messages: state.messages.slice(-MAX_STORED) })
      );
    } catch (e) { /* private mode or quota: the chat still works, just not across pages */ }
  }

  // ---------------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------------

  var CSS = [
    ":host{all:initial}",
    ".scw{--brand:" + BRAND + ";--on-brand:" + ON_BRAND + ";--brand-ink:" + BRAND_INK + ";",
    "--surface:" + PALETTE.surface + ";--tone:" + PALETTE.tone + ";--ink:" + PALETTE.ink + ";--muted:" + PALETTE.muted + ";",
    "--line:" + PALETTE.line + ";--control:" + PALETTE.control + ";--voice:" + PALETTE.voice + ";--on-voice:" + PALETTE.onVoice + ";",
    "--danger:" + PALETTE.danger + ";--danger-soft:" + PALETTE.dangerSoft + ";",
    "--brand-wash:color-mix(in srgb,var(--brand) 12%,var(--surface));--brand-mist:color-mix(in srgb,var(--brand) 6%,var(--surface));",
    "--ease:cubic-bezier(.16,1,.3,1);color-scheme:" + THEME + ";",
    "font-family:" + FONT_STACK + ";",
    "font-size:15px;line-height:1.55;color:var(--ink);-webkit-font-smoothing:antialiased;}",
    ".scw *,.scw *::before,.scw *::after{box-sizing:border-box}",
    ".scw ::selection{background:var(--brand-wash);color:var(--ink)}",
    /* Resets use :where() (zero specificity) so component rules always win. */
    ":where(.scw) button{font:inherit;color:inherit;cursor:pointer;border:0;background:none;padding:0;margin:0}",
    ":where(.scw) svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}",
    ":where(.scw) :focus-visible{outline:2px solid var(--brand-ink);outline-offset:2px}",

    /* Launcher */
    /* Closed: a labelled pill so visitors notice the assistant; open: the circle that closes it */
    ".launcher{position:fixed;right:22px;bottom:22px;z-index:2147483646;height:58px;padding:0 24px 0 17px;border-radius:999px;",
    "display:flex;align-items:center;background:var(--brand);color:var(--on-brand);",
    "box-shadow:0 10px 28px -8px color-mix(in srgb,var(--brand) 70%,transparent),0 2px 6px rgba(0,0,0,.14);",
    "transition:transform .3s var(--ease),box-shadow .3s var(--ease),padding .4s var(--ease)}",
    ".launcher-icon{flex:none;display:grid;width:24px;height:24px}",
    ".launcher-label{display:block;max-width:240px;margin-left:10px;overflow:hidden;white-space:nowrap;font-size:15px;font-weight:600;letter-spacing:-.005em;",
    "transition:max-width .4s var(--ease),margin .4s var(--ease),opacity .2s}",
    ".scw.is-open .launcher{padding:0 17px}",
    ".scw.is-open .launcher-label{max-width:0;margin-left:0;opacity:0}",
    ".scw.intro:not(.is-open) .launcher-label{animation:scw-label-in .9s var(--ease) .5s both}",
    "@keyframes scw-label-in{from{max-width:0;margin-left:0;opacity:0}to{max-width:240px;margin-left:10px;opacity:1}}",
    ".launcher:hover{transform:translateY(-2px);box-shadow:0 14px 32px -8px color-mix(in srgb,var(--brand) 75%,transparent),0 3px 8px rgba(0,0,0,.16)}",
    ".launcher:active{transform:translateY(0) scale(.97)}",
    ".launcher:focus-visible{outline-offset:4px}",
    ".launcher svg{width:24px;height:24px;grid-area:1/1;transition:transform .4s var(--ease),opacity .2s}",
    ".launcher .i-close{opacity:0;transform:rotate(-90deg) scale(.6)}",
    ".scw.is-open .launcher .i-chat{opacity:0;transform:rotate(90deg) scale(.6)}",
    ".scw.is-open .launcher .i-close{opacity:1;transform:none}",

    /* Panel */
    ".panel{position:fixed;right:22px;bottom:94px;z-index:2147483647;width:392px;height:min(660px,calc(100vh - 118px));",
    "display:flex;flex-direction:column;background:var(--surface);border-radius:20px;overflow:hidden;",
    "box-shadow:0 30px 70px -20px rgba(0,0,0,.34),0 6px 18px rgba(0,0,0,.08);border:1px solid color-mix(in srgb,var(--ink) 8%,transparent);",
    "transform-origin:calc(100% - 29px) calc(100% + 45px);opacity:0;transform:translateY(14px) scale(.94);visibility:hidden;",
    "transition:opacity .22s var(--ease),transform .42s var(--ease),visibility 0s linear .42s}",
    ".scw.is-open .panel{opacity:1;transform:none;visibility:visible;transition:opacity .22s var(--ease),transform .42s var(--ease),visibility 0s}",
    ".scw.no-anim .panel,.scw.no-anim .launcher,.scw.no-anim .launcher svg,.scw.no-anim .launcher-label{transition:none}",

    /* Header */
    ".header{display:flex;align-items:center;gap:12px;padding:14px 10px 14px 16px;background:var(--tone);border-bottom:1px solid var(--line)}",
    ".mark{flex:none;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:var(--brand);color:var(--on-brand)}",
    ".mark{font-size:15px;font-weight:600;line-height:1}",
    ".header-text{flex:1;min-width:0}",
    ".title{margin:0;font-size:15px;font-weight:600;line-height:1.25;letter-spacing:-.005em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".subtitle{margin:1px 0 0;font-size:12.5px;line-height:1.3;color:var(--muted)}",
    ".icon-btn{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;color:var(--muted);transition:background .2s,color .2s}",
    ".icon-btn:hover{background:color-mix(in srgb,var(--ink) 7%,transparent);color:var(--ink)}",
    ".icon-btn svg{width:19px;height:19px}",
    ".title:focus-visible{border-radius:4px}",

    /* Messages */
    ".log{flex:1;overflow-y:auto;overscroll-behavior:contain;padding:22px 18px 10px 16px;display:flex;flex-direction:column;gap:20px;",
    "scrollbar-width:thin;scrollbar-color:var(--line) transparent}",
    ".log:focus-visible{outline-offset:-2px}",
    ".log::-webkit-scrollbar{width:8px}.log::-webkit-scrollbar-thumb{background:var(--line);border-radius:8px;border:2px solid var(--surface)}",
    ".msg{display:flex;flex-direction:column;max-width:88%}",
    ".msg.user{align-self:flex-end;align-items:flex-end}",
    ".msg.bot{align-self:stretch;max-width:none;position:relative;padding-left:32px}",
    ".bubble{overflow-wrap:anywhere;text-wrap:pretty}",
    ".msg.user .bubble{background:var(--voice);color:var(--on-voice);padding:10px 15px;border-radius:18px 18px 6px 18px;white-space:pre-wrap}",
    ".msg.bot .bubble{padding-top:1px}",
    ".msg.error .bubble{background:var(--danger-soft);color:var(--danger);padding:10px 14px;border-radius:14px}",
    ".bubble p{margin:0}.bubble p+p,.bubble p+ul,.bubble p+ol,.bubble ul+p,.bubble ol+p{margin-top:8px}",
    ".bubble ul,.bubble ol{margin:6px 0 0;padding-left:18px}.bubble li+li{margin-top:4px}",
    ".bubble li::marker{color:var(--muted)}",
    ".bubble strong{font-weight:650}",
    ".sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}",

    /* The route: every answer starts at an origin stop and runs down a line to the pages it used */
    ".msg.bot::before{content:'';position:absolute;left:4px;top:4px;width:16px;height:16px;border-radius:50%;",
    "background:var(--brand);box-shadow:0 0 0 4px var(--brand-wash)}",
    ".msg.error::before{background:var(--danger);box-shadow:0 0 0 4px var(--danger-soft)}",
    ".msg.has-sources::after{content:'';position:absolute;left:11px;top:20px;bottom:15px;width:2px;border-radius:2px;",
    "background:var(--brand-ink);transform-origin:top;z-index:0}",
    ".cite{display:inline-grid;place-items:center;min-width:17px;height:17px;padding:0 4px;margin:0 1px 0 3px;",
    "border-radius:999px;background:var(--surface);color:var(--brand-ink);font-size:10.5px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums;",
    "text-decoration:none;vertical-align:2px;box-shadow:inset 0 0 0 1.5px var(--brand-ink);transition:background .2s,color .2s}",
    ".cite:hover,.cite.is-linked{background:var(--brand);color:var(--on-brand);box-shadow:inset 0 0 0 1.5px var(--brand)}",
    ".sources-label{margin:14px 0 2px;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}",
    ".sources{margin:2px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:0;width:100%}",
    ".source a{position:relative;display:flex;align-items:center;min-height:30px;padding:5px 10px;margin-left:-4px;border-radius:10px;color:var(--ink);",
    "font-size:13.5px;line-height:1.3;text-decoration:none;transition:background .2s,color .2s}",
    ".source a:hover,.source.is-linked a{background:var(--brand-mist);color:var(--brand-ink)}",
    ".source-n{position:absolute;z-index:1;left:-26px;top:50%;margin-top:-10px;display:grid;place-items:center;width:20px;height:20px;border-radius:50%;",
    "font-size:10.5px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--on-brand);background:var(--brand);",
    "transition:box-shadow .2s,transform .2s}",
    ".source.is-linked .source-n,.source a:hover .source-n{box-shadow:0 0 0 4px var(--brand-wash);transform:scale(1.08)}",
    ".source-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".source-page{font-weight:500}",
    ".source-section{color:var(--muted)}",
    ".source a:hover .source-page{text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px}",

    /* A new answer draws its route, then its stops arrive one by one */
    ".msg.arrive.has-sources::after{animation:scw-draw .7s var(--ease) both}",
    ".msg.arrive .sources-label,.msg.arrive .source{animation:scw-stop .5s var(--ease) both;animation-delay:calc(.18s + var(--i,0) * .09s)}",
    ".msg.arrive::before{animation:scw-origin .5s var(--ease) both}",
    "@keyframes scw-draw{from{transform:scaleY(0)}to{transform:none}}",
    "@keyframes scw-stop{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}",
    "@keyframes scw-origin{from{transform:scale(.4);opacity:0}to{transform:none;opacity:1}}",

    /* Suggestions: the first stops a visitor can take */
    ".chips{display:flex;flex-direction:column;gap:8px;margin:14px 0 0}",
    ".chip{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:10px 12px 10px 14px;border-radius:12px;",
    "font-size:14px;line-height:1.35;text-align:left;color:var(--ink);background:var(--surface);box-shadow:inset 0 0 0 1px var(--line);",
    "transition:background .2s,box-shadow .2s}",
    ".chip svg{flex:none;width:16px;height:16px;color:var(--brand-ink);transition:transform .3s var(--ease)}",
    ".chip:hover{background:var(--brand-mist);box-shadow:inset 0 0 0 1px var(--brand-ink)}",
    ".chip:hover svg{transform:translateX(3px)}",

    /* Retry */
    ".retry{align-self:flex-start;display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:7px 13px 7px 10px;border-radius:999px;",
    "font-size:13px;font-weight:600;color:var(--danger);background:var(--surface);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--danger) 35%,var(--surface))}",
    ".retry svg{width:16px;height:16px}.retry:hover{background:var(--danger-soft)}",

    /* Typing: the origin stop pulses while the answer is written */
    ".typing .bubble{display:flex;gap:5px;padding:7px 0 3px}",
    ".typing::before{animation:scw-pulse 1.4s var(--ease) infinite}",
    ".dot{width:6px;height:6px;border-radius:50%;background:var(--brand-ink);animation:scw-dot 1.2s infinite var(--ease)}",
    ".dot:nth-child(2){animation-delay:.15s}.dot:nth-child(3){animation-delay:.3s}",
    "@keyframes scw-dot{0%,60%,100%{transform:translateY(0);opacity:.3}30%{transform:translateY(-3px);opacity:1}}",
    "@keyframes scw-pulse{0%,100%{box-shadow:0 0 0 4px var(--brand-wash)}50%{box-shadow:0 0 0 8px var(--brand-mist)}}",

    /* Composer */
    ".composer{display:flex;align-items:flex-end;gap:8px;margin:10px 14px 0;padding:6px 6px 6px 16px;border-radius:24px;",
    "background:var(--surface);box-shadow:inset 0 0 0 1px var(--control);transition:box-shadow .2s}",
    ".composer:focus-within{box-shadow:inset 0 0 0 2px var(--brand-ink)}",
    ".input{flex:1;min-width:0;max-height:120px;margin:0;padding:9px 0;border:0;outline:0;resize:none;background:transparent;",
    "font:inherit;font-size:16px;line-height:1.4;color:var(--ink);caret-color:var(--brand-ink)}",
    ".input::placeholder{color:var(--muted);opacity:1}",
    ".send{flex:none;width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--brand);color:var(--on-brand);",
    "transition:background .2s,color .2s,transform .2s}",
    ".send:hover{transform:translateY(-1px)}",
    ".send:disabled{background:var(--tone);color:var(--control);cursor:default;transform:none}",
    ".footer{margin:0;padding:9px 16px 12px;text-align:center;font-size:12px;letter-spacing:.01em;color:var(--muted)}",

    /* Small screens: the panel takes the whole screen */
    "@media (max-width:480px){",
    ".panel{inset:0;width:auto;height:auto;height:100dvh;border-radius:0;border:0;transform-origin:50% 100%}",
    ".scw.is-open .launcher{opacity:0;visibility:hidden;pointer-events:none}",
    ".header{padding-top:max(14px,env(safe-area-inset-top))}",
    ".footer{padding-bottom:max(12px,env(safe-area-inset-bottom))}",
    ".msg{max-width:92%}}",

    "@media (prefers-reduced-motion:reduce){.scw *,.scw *::before,.scw *::after{transition-duration:0s!important;animation:none!important}",
    ".panel{transform:none!important}.dot{opacity:.7}}",
  ].join("");

  // ---------------------------------------------------------------------------
  // Build the UI
  // ---------------------------------------------------------------------------

  var host = el("div", { id: "site-chat-widget" });
  var shadow = host.attachShadow({ mode: "open" });
  shadow.appendChild(el("style", { text: CSS }));

  var launcherIcons = [icon("chat"), icon("close")];
  launcherIcons[0].setAttribute("class", "i-chat");
  launcherIcons[1].setAttribute("class", "i-close");

  var launcher = el(
    "button",
    { class: "launcher", type: "button", "aria-label": TEXT.open, "aria-expanded": "false", "aria-controls": "scw-panel", onclick: toggle },
    [
      el("span", { class: "launcher-icon", "aria-hidden": "true" }, launcherIcons),
      el("span", { class: "launcher-label", "aria-hidden": "true", text: TEXT.launcher }),
    ]
  );

  var log = el("div", { class: "log", role: "log", "aria-live": "polite", "aria-relevant": "additions", "aria-label": TITLE });
  var status = el("p", { class: "sr", role: "status" });

  var input = el("textarea", {
    class: "input",
    rows: "1",
    maxlength: "1000",
    placeholder: TEXT.placeholder,
    "aria-label": TEXT.inputLabel,
    enterkeyhint: "send",
  });
  var sendButton = el("button", { class: "send", type: "submit", "aria-label": TEXT.send, disabled: true }, [icon("send")]);
  var form = el("form", { class: "composer", onsubmit: onSubmit }, [input, sendButton]);

  var panel = el(
    "section",
    { class: "panel", id: "scw-panel", role: "dialog", "aria-modal": "false", "aria-labelledby": "scw-title", "aria-hidden": "true" },
    [
      el("header", { class: "header" }, [
        el("span", { class: "mark", "aria-hidden": "true", text: (TITLE.trim()[0] || "?").toUpperCase() }),
        el("div", { class: "header-text" }, [
          el("h2", { class: "title", id: "scw-title", tabindex: "-1", text: TITLE }),
          el("p", { class: "subtitle", text: TEXT.subtitle }),
        ]),
        el("button", { class: "icon-btn", type: "button", "aria-label": TEXT.reset, title: TEXT.reset, onclick: resetConversation }, [icon("reset")]),
        el("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, title: TEXT.close, onclick: close }, [icon("close")]),
      ]),
      log,
      status,
      form,
      el("p", { class: "footer", text: TEXT.footer }),
    ]
  );

  var root = el("div", { class: "scw no-anim", lang: LANG }, [panel, launcher]);
  shadow.appendChild(root);

  var pending = false;
  var typingNode = null;

  function mount() {
    document.body.appendChild(host);
    renderAll();
    if (state.open) open({ focus: false });
    else playIntroOnce();
    // Enable transitions only after the first paint, so a panel restored
    // open on a new page doesn't animate in again.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { root.classList.remove("no-anim"); });
    });
  }

  // The launcher's label slides out on the first page of a visit only, so it
  // catches the eye once without replaying on every navigation.
  function playIntroOnce() {
    var key = STORAGE_KEY + ":intro";
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch (e) { return; }
    root.classList.add("intro");
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  // Full rebuild (page load, reset, retry). The live region is muted while
  // it happens, so screen readers don't read the whole conversation again;
  // new messages are appended one by one in ask() and announced normally.
  function renderAll() {
    log.setAttribute("aria-live", "off");
    log.textContent = "";
    log.appendChild(renderWelcome());
    state.messages.forEach(function (message, index) {
      log.appendChild(renderMessage(message, index));
    });
    if (lastUnanswered()) log.appendChild(renderInterrupted());
    scrollToEnd();
    requestAnimationFrame(function () { log.setAttribute("aria-live", "polite"); });
  }

  function appendMessage(index) {
    var node = renderMessage(state.messages[index], index);
    node.classList.add("arrive");
    log.appendChild(node);
    scrollToEnd();
  }

  function renderWelcome() {
    var hasUserMessages = state.messages.some(function (m) { return m.role === "user"; });
    var node = el("div", { class: "msg bot" }, [
      el("span", { class: "sr", text: TEXT.bot + ": " }),
      el("div", { class: "bubble" }, [el("p", { text: typo(TEXT.welcome) })]),
    ]);
    if (!hasUserMessages && SUGGESTIONS.length) {
      node.appendChild(
        el(
          "div",
          { class: "chips", role: "group", "aria-label": TEXT.suggestionsLabel },
          SUGGESTIONS.map(function (q) {
            return el("button", { class: "chip", type: "button", onclick: function () { ask(q); } }, [el("span", { text: typo(q) }), icon("arrow")]);
          })
        )
      );
    }
    return node;
  }

  function renderMessage(message, index) {
    if (message.role === "user") {
      return el("div", { class: "msg user" }, [
        el("span", { class: "sr", text: TEXT.you + ": " }),
        el("div", { class: "bubble", text: typo(message.content) }),
      ]);
    }

    var node = el("div", { class: "msg bot" + (message.error ? " error" : "") });
    // Stops are renumbered 1..k in the server's order: the server numbers
    // retrieved chunks, so the ones the answer cites can skip (1, 3).
    var sources = (message.sources || []).filter(function (s) { return safeUrl(s.url); });
    var byNumber = {};
    var perPage = {};
    sources.forEach(function (s, i) {
      byNumber[s.n] = { source: s, d: i + 1 };
      var page = sourceParts(s).page;
      perPage[page] = (perPage[page] || 0) + 1;
    });

    function link(n, on) {
      Array.prototype.forEach.call(node.querySelectorAll('[data-n="' + n + '"]'), function (item) {
        item.classList.toggle("is-linked", on);
      });
    }

    function citeFor(n) {
      var hit = byNumber[n];
      if (!hit) return null;
      var source = hit.source, d = hit.d;
      return el("a", {
        class: "cite",
        href: safeUrl(source.url),
        "data-n": String(d),
        "aria-label": TEXT.source + " " + d + ": " + sourceText(source),
        title: sourceText(source),
        text: String(d),
        onmouseenter: function () { link(d, true); },
        onmouseleave: function () { link(d, false); },
        onfocus: function () { link(d, true); },
        onblur: function () { link(d, false); },
      });
    }

    node.appendChild(el("span", { class: "sr", text: TEXT.bot + ": " }));
    node.appendChild(el("div", { class: "bubble" }, [renderMarkdown(message.content, citeFor)]));

    if (sources.length) {
      node.classList.add("has-sources");
      node.appendChild(el("p", { class: "sources-label", "aria-hidden": "true", text: TEXT.sources }));
      node.appendChild(
        el(
          "ul",
          { class: "sources", "aria-label": TEXT.sources },
          sources.map(function (source, i) {
            // Each row names its page; the section is added only when two
            // sources come from the same page and need telling apart.
            var parts = sourceParts(source);
            var label = el("span", { class: "source-label" }, [el("span", { class: "source-page", text: parts.page })]);
            if (parts.section && perPage[parts.page] > 1) {
              label.appendChild(el("span", { class: "source-section", text: " · " + parts.section }));
            }
            var d = i + 1;
            return el("li", { class: "source", "data-n": String(d), style: "--i:" + d }, [
              el(
                "a",
                {
                  href: safeUrl(source.url),
                  title: sourceText(source),
                  onmouseenter: function () { link(d, true); },
                  onmouseleave: function () { link(d, false); },
                  onfocus: function () { link(d, true); },
                  onblur: function () { link(d, false); },
                },
                [
                  el("span", { class: "source-n", "aria-hidden": "true", text: String(d) }),
                  label,
                ]
              ),
            ]);
          })
        )
      );
    }

    if (message.error && message.retry && index === state.messages.length - 1) {
      node.appendChild(retryButton(message.retry));
    }
    return node;
  }

  function retryButton(question) {
    return el("button", { class: "retry", type: "button", onclick: function () { retry(question); } }, [icon("retry"), TEXT.retry]);
  }

  function renderInterrupted() {
    var last = state.messages[state.messages.length - 1];
    return el("div", { class: "msg bot error interrupted" }, [
      el("div", { class: "bubble" }, [el("p", { text: TEXT.interrupted })]),
      retryButton(last.content),
    ]);
  }

  function lastUnanswered() {
    var last = state.messages[state.messages.length - 1];
    return !pending && last && last.role === "user";
  }

  function showTyping(on) {
    if (on && !typingNode) {
      typingNode = el("div", { class: "msg bot typing" }, [
        el("div", { class: "bubble", "aria-hidden": "true" }, [el("span", { class: "dot" }), el("span", { class: "dot" }), el("span", { class: "dot" })]),
      ]);
      log.appendChild(typingNode);
      status.textContent = TEXT.typing;
      scrollToEnd();
    } else if (!on && typingNode) {
      typingNode.remove();
      typingNode = null;
      status.textContent = "";
    }
  }

  function scrollToEnd() {
    // Twice: once after layout, once after late layout shifts (web fonts,
    // a panel restored open while the page is still loading).
    requestAnimationFrame(function () { log.scrollTop = log.scrollHeight; });
    setTimeout(function () { log.scrollTop = log.scrollHeight; }, 150);
  }

  // ---------------------------------------------------------------------------
  // Open / close
  // ---------------------------------------------------------------------------

  var smallScreen = window.matchMedia("(max-width: 480px)");
  var savedOverflow = null;

  function lockPageScroll(on) {
    var html = document.documentElement;
    if (on && smallScreen.matches && savedOverflow === null) {
      savedOverflow = html.style.overflow;
      html.style.overflow = "hidden";
    } else if (!on && savedOverflow !== null) {
      html.style.overflow = savedOverflow;
      savedOverflow = null;
    }
  }

  function open(options) {
    state.open = true;
    root.classList.add("is-open");
    panel.setAttribute("aria-hidden", "false");
    // Full screen on phones: it behaves as a modal there.
    panel.setAttribute("aria-modal", smallScreen.matches ? "true" : "false");
    launcher.setAttribute("aria-expanded", "true");
    launcher.setAttribute("aria-label", TEXT.close);
    lockPageScroll(true);
    save();
    scrollToEnd();
    if (!options || options.focus !== false) {
      // On phones, focusing the input would pop the keyboard over the
      // welcome message and suggestions; focus the title instead.
      var target = smallScreen.matches ? panel.querySelector(".title") : input;
      setTimeout(function () { target.focus(); }, 60);
    }
  }

  function close() {
    state.open = false;
    root.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-label", TEXT.open);
    lockPageScroll(false);
    save();
    launcher.focus();
  }

  function toggle() {
    state.open ? close() : open();
  }

  panel.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
      return;
    }
    // Full-screen panel on phones: keep Tab inside it.
    if (event.key === "Tab" && smallScreen.matches) {
      var focusable = Array.prototype.filter.call(
        panel.querySelectorAll("button, a[href], textarea"),
        function (node) { return !node.disabled && node.offsetParent !== null; }
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      var current = shadow.activeElement;
      if (event.shiftKey && focusable.indexOf(current) <= 0) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  // ---------------------------------------------------------------------------
  // Asking
  // ---------------------------------------------------------------------------

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
    sendButton.disabled = pending || !input.value.trim();
  }

  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      onSubmit(event);
    }
  });

  function onSubmit(event) {
    event.preventDefault();
    var question = input.value.trim();
    if (!question || pending) return;
    input.value = "";
    autoGrow();
    ask(question);
  }

  function historyForApi() {
    return state.messages
      .filter(function (m) { return !m.error && (m.role === "user" || m.role === "assistant"); })
      .slice(-HISTORY_SENT)
      .map(function (m) { return { role: m.role, content: String(m.content).slice(0, 4000) }; });
  }

  function retry(question) {
    // Drop the failed attempt (error bubble and/or the unanswered question).
    while (state.messages.length) {
      var last = state.messages[state.messages.length - 1];
      if (last.error || (last.role === "user" && last.content === question)) state.messages.pop();
      else break;
    }
    renderAll();
    ask(question);
  }

  function removeAll(selector) {
    Array.prototype.forEach.call(log.querySelectorAll(selector), function (node) { node.remove(); });
  }

  function ask(question) {
    if (pending) return;
    var history = historyForApi();
    state.messages.push({ role: "user", content: question.slice(0, 1000) });
    save();
    pending = true;
    // Suggestions, old retry buttons and "interrupted" notes are spent once
    // a new question is asked.
    removeAll(".chips, .retry, .interrupted");
    appendMessage(state.messages.length - 1);
    showTyping(true);
    autoGrow();

    var controller = "AbortController" in window ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, REQUEST_TIMEOUT_MS);

    fetch(API + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question.slice(0, 1000), history: history }),
      signal: controller ? controller.signal : undefined,
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (result) {
        state.messages.push({
          role: "assistant",
          content: String(result.answer || ""),
          sources: Array.isArray(result.sources) ? result.sources : [],
          error: result.error ? true : undefined,
          retry: result.error ? question : undefined,
        });
      })
      .catch(function () {
        state.messages.push({ role: "assistant", content: TEXT.network, sources: [], error: true, retry: question });
      })
      .then(function () {
        clearTimeout(timer);
        pending = false;
        showTyping(false);
        save();
        appendMessage(state.messages.length - 1);
        autoGrow();
        if (state.open && !smallScreen.matches) input.focus();
      });
  }

  function resetConversation() {
    if (pending) return;
    state.messages = [];
    save();
    renderAll();
    input.focus();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
