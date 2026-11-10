/* Fleuve Immobilier — navigation, header state and listing search. No dependencies. */
(function () {
  "use strict";
  var doc = document.documentElement;
  var fr = doc.lang === "fr";

  /* Mobile menu */
  var header = document.querySelector(".site-header");
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("main-nav");
  if (toggle && nav && header) {
    var setOpen = function (open) {
      toggle.setAttribute("aria-expanded", String(open));
      nav.classList.toggle("is-open", open);
      header.classList.toggle("nav-open", open);
    };
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("is-open")) { setOpen(false); toggle.focus(); }
    });
    window.matchMedia("(min-width: 1081px)").addEventListener("change", function (mq) { if (mq.matches) setOpen(false); });
  }

  /* Header over the hero turns solid once the hero scrolls away */
  if (header && document.body.classList.contains("has-hero")) {
    var hero = document.querySelector(".hero");
    var update = function () {
      var limit = hero ? hero.offsetHeight - header.offsetHeight - 40 : 40;
      header.classList.toggle("is-solid", window.scrollY > limit);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
  }

  /* Home search: budget options follow Buy / Rent */
  var form = document.querySelector("form.search");
  if (form) {
    var budget = form.querySelector("[data-budget]");
    var syncBudget = function () {
      var type = (form.querySelector("input[name=type]:checked") || {}).value || "sale";
      Array.prototype.forEach.call(budget.options, function (o) {
        var t = o.getAttribute("data-type");
        o.hidden = o.disabled = Boolean(t && t !== type);
      });
      if (budget.selectedOptions[0] && budget.selectedOptions[0].disabled) budget.value = "";
    };
    form.addEventListener("change", syncBudget);
    syncBudget();
  }

  /* Listings page: filter cards from ?type=&area=&max= */
  var cards = document.querySelectorAll(".listing[data-type]");
  var params = new URLSearchParams(location.search);
  var type = params.get("type"), area = params.get("area"), max = Number(params.get("max")) || 0;
  if (cards.length && document.querySelector("[aria-current=page][href='listings.html']") && (type || area || max)) {
    var shown = 0;
    cards.forEach(function (card) {
      var ok = (!type || card.dataset.type === type) &&
               (!area || card.dataset.area === area) &&
               (!max || Number(card.dataset.price) <= max);
      card.hidden = !ok;
      if (ok) shown++;
    });
    document.querySelectorAll("main h2").forEach(function (h2) {
      var grid = h2.nextElementSibling;
      if (grid && grid.classList.contains("grid")) {
        var any = grid.querySelector(".listing:not([hidden])");
        h2.hidden = grid.hidden = !any;
      }
    });
    var status = document.createElement("div");
    status.className = "filter-status";
    status.setAttribute("role", "status");
    var text = fr
      ? shown + " propriété" + (shown > 1 ? "s" : "") + " sur " + cards.length + " correspond" + (shown > 1 ? "ent" : "") + " à votre recherche."
      : shown + " of " + cards.length + " listings match your search.";
    if (!shown) text += fr ? " Élargissez le quartier ou le budget." : " Try another neighborhood or budget.";
    status.innerHTML = "<p></p><a href='listings.html'></a>";
    status.querySelector("p").textContent = text;
    status.querySelector("a").textContent = fr ? "Voir les 8 propriétés" : "Show all 8 listings";
    var notice = document.querySelector("main .notice");
    if (notice) notice.after(status);
  }
})();
