/* Progressive enhancement for the audit site. Every page works without it. */
(function () {
  "use strict";
  var d = document;
  d.documentElement.classList.add("js");

  function ready(fn) {
    if (d.readyState !== "loading") fn();
    else d.addEventListener("DOMContentLoaded", fn);
  }

  function size(n) {
    return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  }

  ready(function () {
    // Reveal sections as they scroll into view.
    var items = d.querySelectorAll("[data-reveal]");
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      }, { rootMargin: "0px 0px -6% 0px", threshold: 0.06 });
      items.forEach(function (el) { io.observe(el); });
    } else {
      items.forEach(function (el) { el.classList.add("in"); });
    }

    // A soft light that follows the pointer over cards.
    d.addEventListener("pointermove", function (ev) {
      var card = ev.target && ev.target.closest ? ev.target.closest(".spot") : null;
      if (!card) return;
      var r = card.getBoundingClientRect();
      card.style.setProperty("--mx", ev.clientX - r.left + "px");
      card.style.setProperty("--my", ev.clientY - r.top + "px");
    }, { passive: true });

    // The navigation bar gains a background once the page scrolls.
    var nav = d.querySelector(".nav");
    if (nav) {
      var onScroll = function () { nav.classList.toggle("scrolled", window.scrollY > 8); };
      onScroll();
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    // File fields: drag and drop, and the chosen file's name.
    d.querySelectorAll(".drop").forEach(function (zone) {
      var input = zone.querySelector("input[type=file]");
      var out = zone.querySelector(".drop-file");
      if (!input) return;
      ["dragenter", "dragover"].forEach(function (t) {
        zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add("over"); });
      });
      ["dragleave", "dragend", "drop"].forEach(function (t) {
        zone.addEventListener(t, function () { zone.classList.remove("over"); });
      });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          input.files = e.dataTransfer.files;
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
      input.addEventListener("change", function () {
        var f = input.files && input.files[0];
        zone.classList.toggle("has", !!f);
        if (out) out.textContent = f ? f.name + " · " + size(f.size) : "";
      });
    });

    // While an audit runs, show what is happening instead of a frozen page.
    d.querySelectorAll("form[data-busy]").forEach(function (form) {
      form.addEventListener("submit", function () {
        var overlay = d.getElementById(form.getAttribute("data-busy"));
        if (overlay) overlay.classList.add("on");
        var button = form.querySelector("button[type=submit]");
        if (button) button.setAttribute("aria-busy", "true");
      });
    });
    window.addEventListener("pageshow", function () {
      d.querySelectorAll(".busy.on").forEach(function (o) { o.classList.remove("on"); });
      d.querySelectorAll("[aria-busy=true]").forEach(function (b) { b.removeAttribute("aria-busy"); });
    });

    // Copy buttons (the badge code on the verification page).
    d.querySelectorAll("[data-copy]").forEach(function (button) {
      var target = d.getElementById(button.getAttribute("data-copy"));
      if (!target || !navigator.clipboard) return;
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(target.textContent || "").then(function () {
          var label = button.textContent;
          button.textContent = button.getAttribute("data-done") || label;
          setTimeout(function () { button.textContent = label; }, 1800);
        });
      });
    });
  });
})();
