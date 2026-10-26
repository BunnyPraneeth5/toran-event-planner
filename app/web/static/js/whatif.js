// What-if sliders: live readouts while dragging, one announcement per settled change, and
// focus kept on the control after the dashboard refreshes. The numbers shown while dragging
// are only the slider's own value; every rebalanced figure comes from the server's engines.
(function () {
  "use strict";

  var LAKH = 100000;
  var CRORE = 10000000;
  var keepFocusId = null;

  function trim(value) {
    return (Math.round(value * 100) / 100).toString();
  }

  // Same display rules as the server: ₹80,000, ₹25 lakh, ₹1.25 crore.
  function shortRupees(amount) {
    if (amount >= CRORE) {
      return "₹" + trim(amount / CRORE) + " crore";
    }
    if (amount >= LAKH) {
      return "₹" + trim(amount / LAKH) + " lakh";
    }
    return "₹" + amount.toLocaleString("en-IN");
  }

  function describe(input) {
    var value = Number(input.value);
    return input.dataset.format === "guests" ? value + " guests" : shortRupees(value);
  }

  function announce(message) {
    var live = document.getElementById("live");
    if (live) {
      live.textContent = message;
    }
  }

  document.addEventListener("input", function (evt) {
    var input = evt.target;
    if (!input.matches || !input.matches("input[type=range][data-format]")) {
      return;
    }
    var text = describe(input);
    input.setAttribute("aria-valuetext", text);
    var output = document.querySelector("[data-output-for='" + input.id + "']");
    if (output) {
      output.textContent = text;
    }
  });

  document.addEventListener("htmx:beforeRequest", function (evt) {
    var elt = evt.detail.elt;
    keepFocusId = elt && elt.hasAttribute && elt.hasAttribute("data-keep-focus") ? elt.id : null;
  });

  // Runs after app.js has focused the new heading, so the control gets focus back.
  document.addEventListener("htmx:afterSettle", function () {
    if (!keepFocusId) {
      return;
    }
    var control = document.getElementById(keepFocusId);
    if (control) {
      control.focus();
    }
    var summary = document.querySelector("#budget-heading + .summary");
    if (summary) {
      announce("Plan updated. " + summary.textContent.trim());
    }
    keepFocusId = null;
  });
})();
