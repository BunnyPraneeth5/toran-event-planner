// Contents panel. On wide screens it is an open left rail; on phones a one-line status bar
// that opens the list. The section in view is marked with aria-current. Plain links do the
// navigation, so the panel works without this file too.
(function () {
  "use strict";

  var WIDE = window.matchMedia("(min-width: 64rem)");
  var observer = null;

  function panel() {
    return document.querySelector("[data-plan-nav]");
  }

  // Open on wide screens; on phones closed until tapped.
  function fit() {
    var details = panel();
    if (details) {
      details.open = WIDE.matches;
    }
  }

  function mark(id) {
    var details = panel();
    if (!details) {
      return;
    }
    details.querySelectorAll("a[href^='#']").forEach(function (link) {
      if (link.getAttribute("href") === "#" + id) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  // Highlight the topmost section that is in the upper part of the viewport.
  function watch() {
    var details = panel();
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    if (!details || !("IntersectionObserver" in window)) {
      return;
    }
    var visible = {};
    observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          visible[entry.target.id] = entry.isIntersecting;
        });
        var first = Array.prototype.find.call(details.querySelectorAll("a[href^='#']"), function (link) {
          return visible[link.getAttribute("href").slice(1)];
        });
        if (first) {
          mark(first.getAttribute("href").slice(1));
        }
      },
      { rootMargin: "0px 0px -60% 0px" }
    );
    details.querySelectorAll("a[href^='#']").forEach(function (link) {
      var section = document.getElementById(link.getAttribute("href").slice(1));
      if (section) {
        observer.observe(section);
      }
    });
  }

  function setUp() {
    fit();
    watch();
  }

  // On phones, choosing a section closes the list so the section is not hidden behind it.
  document.addEventListener("click", function (evt) {
    var link = evt.target.closest ? evt.target.closest("[data-plan-nav] a[href^='#']") : null;
    if (link && !WIDE.matches) {
      panel().open = false;
    }
  });

  if (WIDE.addEventListener) {
    WIDE.addEventListener("change", fit);
  }
  document.addEventListener("htmx:afterSwap", setUp);
  document.addEventListener("toran:shown", setUp);
})();
