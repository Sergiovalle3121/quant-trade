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

    // Key figures count up once, the first time they are seen.
    var counters = d.querySelectorAll("[data-count]");
    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if ("IntersectionObserver" in window && !still) {
      var co = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          co.unobserve(e.target);
          var el = e.target, end = parseInt(el.textContent, 10), t0 = null;
          if (!(end > 1) || String(end) !== el.textContent.trim()) return;
          var step = function (t) {
            if (t0 === null) t0 = t;
            var k = Math.min(1, (t - t0) / 1400);
            el.textContent = String(Math.round(end * (1 - Math.pow(1 - k, 3))));
            if (k < 1) window.requestAnimationFrame(step);
          };
          window.requestAnimationFrame(step);
        });
      }, { threshold: 0.4 });
      counters.forEach(function (el) { co.observe(el); });
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

    // Long pages: the index marks the section being read.
    var toc = d.querySelector("[data-toc]");
    if (toc && "IntersectionObserver" in window) {
      var links = {};
      toc.querySelectorAll("a").forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          Object.keys(links).forEach(function (id) { links[id].classList.remove("on"); });
          var link = links[entry.target.id];
          if (!link) return;
          link.classList.add("on");
          // A row that scrolls sideways (the report's) keeps the active link in view.
          var row = link.closest("ol");
          if (row && row.scrollWidth > row.clientWidth) {
            row.scrollTo({ left: link.offsetLeft - 24, behavior: still ? "auto" : "smooth" });
          }
        });
      }, { rootMargin: "-90px 0px -65% 0px" });
      Object.keys(links).forEach(function (id) {
        var heading = d.getElementById(id);
        if (heading) spy.observe(heading);
      });
    }

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
  // Suggest the report's own column names for "name its columns".
  ready(function () {
    var input = d.querySelector("input[type=file][name=report]");
    var list = d.getElementById("report-columns");
    var shown = d.getElementById("report-columns-shown");
    if (!input || !list || !window.FileReader) return;
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      while (list.firstChild) list.removeChild(list.firstChild);
      if (shown) {
        while (shown.children.length > 1) shown.removeChild(shown.lastChild);
        shown.hidden = true;
      }
      if (!file || !/\.(csv|txt|tsv)$/i.test(file.name)) return;
      var reader = new FileReader();
      reader.onload = function () {
        var lines = String(reader.result).split(/\r?\n/).filter(function (l) { return l.trim(); }).slice(0, 15);
        var best = "", sep = ",";
        lines.forEach(function (line) {
          [",", ";", "\t"].forEach(function (c) {
            if (line.split(c).length > best.split(sep).length) { best = line; sep = c; }
          });
        });
        best.split(sep).forEach(function (name) {
          name = name.replace(/^\ufeff/, "").replace(/^"|"$/g, "").trim();
          if (!name) return;
          var option = d.createElement("option");
          option.value = name;
          list.appendChild(option);
          if (shown) {
            var chip = d.createElement("code");
            chip.textContent = name;
            shown.appendChild(chip);
            shown.hidden = false;
          }
        });
      };
      reader.readAsText(file.slice(0, 65536));
    });
  });

  // A PDF takes a few seconds to render: say so on the button that asked for it.
  ready(function () {
    d.querySelectorAll("a[download][data-busy]").forEach(function (link) {
      link.addEventListener("click", function (ev) {
        if (link.getAttribute("aria-busy") === "true") {
          ev.preventDefault();
          return;
        }
        var label = link.textContent;
        link.textContent = link.getAttribute("data-busy");
        link.setAttribute("aria-busy", "true");
        window.setTimeout(function () {
          link.textContent = label;
          link.removeAttribute("aria-busy");
        }, 8000);
      });
    });
  });

  // Passkeys: the page carries the options; the device's answer goes back in
  // an ordinary form post (no fetch, so the CSP keeps connect-src 'none').
  function fromB64(text) {
    var s = text.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out.buffer;
  }
  function toB64(buf) {
    var bytes = new Uint8Array(buf), raw = "";
    for (var i = 0; i < bytes.length; i++) raw += String.fromCharCode(bytes[i]);
    return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  ready(function () {
    d.querySelectorAll("form[data-passkey]").forEach(function (form) {
      var go = form.querySelector("[data-passkey-go]");
      var err = form.querySelector("[data-passkey-error]");
      var field = form.querySelector("input[name=credential]");
      var create = form.getAttribute("data-passkey") === "create";
      function fail() {
        if (err) err.hidden = false;
        if (go) go.disabled = false;
      }
      if (!window.PublicKeyCredential || !navigator.credentials || !field) {
        fail();
        if (go) go.disabled = true;
        return;
      }
      form.addEventListener("submit", function (ev) {
        if (field.value) return;
        ev.preventDefault();
        if (go) go.disabled = true;
        if (err) err.hidden = true;
        var o;
        try {
          o = JSON.parse(form.getAttribute("data-options"));
        } catch (e) {
          fail();
          return;
        }
        o.challenge = fromB64(o.challenge);
        if (create) {
          o.user.id = fromB64(o.user.id);
          (o.excludeCredentials || []).forEach(function (c) { c.id = fromB64(c.id); });
        } else {
          (o.allowCredentials || []).forEach(function (c) { c.id = fromB64(c.id); });
        }
        var ask = create
          ? navigator.credentials.create({ publicKey: o })
          : navigator.credentials.get({ publicKey: o });
        ask.then(function (c) {
          if (!c) return fail();
          var r = c.response;
          var out = {
            id: c.id,
            rawId: toB64(c.rawId),
            type: c.type,
            clientExtensionResults: {},
            response: { clientDataJSON: toB64(r.clientDataJSON) }
          };
          if (c.authenticatorAttachment) out.authenticatorAttachment = c.authenticatorAttachment;
          if (create) {
            out.response.attestationObject = toB64(r.attestationObject);
            if (r.getTransports) out.response.transports = r.getTransports();
          } else {
            out.response.authenticatorData = toB64(r.authenticatorData);
            out.response.signature = toB64(r.signature);
            if (r.userHandle) out.response.userHandle = toB64(r.userHandle);
          }
          field.value = JSON.stringify(out);
          form.submit();
        }, fail);
      });
    });
  });
})();
