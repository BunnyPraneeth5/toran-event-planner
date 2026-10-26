// Calendar file download: posts the saved plan, receives an .ics file, saves it as
// toran-plan.ics. Built by the server's calendar engine; no AI involved.
(function () {
  "use strict";

  function announce(message) {
    var live = document.getElementById("live");
    if (live) {
      live.textContent = message;
    }
  }

  document.addEventListener("click", function (evt) {
    var button = evt.target.closest ? evt.target.closest("[data-action='download-ics']") : null;
    if (!button) {
      return;
    }
    var plan = window.ToranState ? window.ToranState.load() : null;
    if (!plan) {
      announce("There is no plan saved in this browser yet.");
      return;
    }
    button.disabled = true;
    fetch("/api/calendar/ics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: plan }),
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.blob();
      })
      .then(function (blob) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "toran-plan.ics";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () {
          URL.revokeObjectURL(link.href);
        }, 1000);
        announce("Calendar file downloaded. Open it to add every task and function to your calendar.");
      })
      .catch(function () {
        announce("The calendar file could not be made. Please try again.");
      })
      .finally(function () {
        button.disabled = false;
      });
  });
})();
