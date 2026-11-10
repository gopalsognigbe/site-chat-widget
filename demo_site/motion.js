/* Fleuve Immobilier — scroll motion (Lenis + GSAP ScrollTrigger).
   Content is visible without this file; reduced motion skips it entirely. */
(function () {
  "use strict";
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (!window.gsap || !window.ScrollTrigger) return;
  var gsap = window.gsap;
  gsap.registerPlugin(window.ScrollTrigger);

  if (window.Lenis) {
    var lenis = new window.Lenis({ duration: 1.1, easing: function (t) { return 1 - Math.pow(1 - t, 4); } });
    lenis.on("scroll", window.ScrollTrigger.update);
    gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
      a.addEventListener("click", function (e) {
        var target = document.querySelector(a.getAttribute("href"));
        if (target) { e.preventDefault(); lenis.scrollTo(target, { offset: -96 }); target.focus({ preventScroll: true }); }
      });
    });
  }

  var expo = "expo.out";

  /* Signature moment: the hero headline rises line by line while the photo settles and drifts */
  var hero = document.querySelector(".hero");
  if (hero) {
    var lines = hero.querySelectorAll(".reveal-line > span");
    var tl = gsap.timeline({ defaults: { ease: expo } });
    tl.from(hero.querySelector(".hero-media img"), { scale: 1.12, duration: 2.4 }, 0)
      .from(lines, { yPercent: 110, duration: 1.4, stagger: 0.12 }, 0.15)
      .from(hero.querySelectorAll(".hero-lede, .search, .hero-foot"), { y: 24, opacity: 0, duration: 1.2, stagger: 0.1 }, 0.55);
    gsap.to(hero.querySelector(".hero-media img"), {
      yPercent: 10, ease: "none",
      scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true }
    });
    gsap.to(hero.querySelector(".hero-inner"), {
      yPercent: -12, opacity: 0.2, ease: "none",
      scrollTrigger: { trigger: hero, start: "40% top", end: "bottom top", scrub: true }
    });
  }

  /* Inner page titles */
  var pageTitle = document.querySelector(".page-header h1");
  if (pageTitle) {
    gsap.from(pageTitle, { y: 36, opacity: 0, duration: 1.3, ease: expo });
    gsap.from(".page-header p", { y: 20, opacity: 0, duration: 1.2, ease: expo, delay: 0.12 });
  }

  /* Photographs drift inside their frames */
  document.querySelectorAll("[data-parallax-inner]").forEach(function (img) {
    gsap.fromTo(img, { yPercent: -6 }, {
      yPercent: 6, ease: "none",
      scrollTrigger: { trigger: img.parentElement, start: "top bottom", end: "bottom top", scrub: true }
    });
  });

  /* Section headings and rows arrive once */
  gsap.utils.toArray("main h2:not(.hero h2)").forEach(function (h) {
    if (h.closest(".page-header")) return;
    gsap.from(h, { y: 28, opacity: 0, duration: 1.1, ease: expo, scrollTrigger: { trigger: h, start: "top 88%", once: true } });
  });
  gsap.utils.toArray(".grid, .hoods, .guide-index, .services, .steps, .faq").forEach(function (group) {
    var items = group.children;
    gsap.from(items, {
      y: 32, opacity: 0, duration: 1, ease: expo, stagger: 0.08,
      scrollTrigger: { trigger: group, start: "top 85%", once: true }
    });
  });
})();
