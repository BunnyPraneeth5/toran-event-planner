// Toran plan state. The server is stateless: the plan lives in this browser's localStorage.
// Every plan-changing response carries the plan in #plan-state; this file saves it, adds it
// to requests that need it, and handles export, import and changes from other tabs.
(function () {
  "use strict";

  var KEY = "toran.plan";
  var PREVIOUS_KEY = "toran.plan.previous";
  var SCHEMA_VERSION = 1;

  function announce(message) {
    var live = document.getElementById("live");
    if (live) {
      live.textContent = message;
    }
  }

  function read(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (ignored) {
      return null;
    }
  }

  function write(key, value) {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch (ignored) {
      announce("This browser could not save the plan. Download the plan file to keep it.");
      return false;
    }
  }

  // The saved plan, or null. A plan from another schema version is set aside, not used.
  function load() {
    var raw = read(KEY);
    if (!raw) {
      return null;
    }
    try {
      var plan = JSON.parse(raw);
      if (plan.schema_version === SCHEMA_VERSION) {
        return plan;
      }
    } catch (ignored) {
      // fall through: unreadable data is set aside below
    }
    write(PREVIOUS_KEY, raw);
    try {
      window.localStorage.removeItem(KEY);
    } catch (ignored) {
      // nothing more to do
    }
    announce("Your saved plan is from an older version of Toran and was set aside. Download it below.");
    return null;
  }

  function save(raw) {
    if (!write(KEY, raw)) {
      return;
    }
    if (navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(function () {});
    }
  }

  // Save the plan from freshly swapped content, if it carries one.
  function saveFrom(root) {
    var holder = root.querySelector ? root.querySelector("#plan-state") : null;
    if (!holder || !holder.dataset.plan) {
      return;
    }
    try {
      var plan = JSON.parse(holder.dataset.plan);
      if (plan.schema_version === SCHEMA_VERSION) {
        save(holder.dataset.plan);
      }
    } catch (ignored) {
      announce("The plan could not be read, so it was not saved.");
    }
  }

  function download(raw, filename) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([raw], { type: "application/json" }));
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () {
      URL.revokeObjectURL(link.href);
    }, 1000);
  }

  function showDashboard(html) {
    var target = document.getElementById("dashboard");
    if (!target) {
      return;
    }
    target.innerHTML = html;
    htmx.process(target);
    saveFrom(target);
    var heading = target.querySelector("[data-focus]");
    if (heading) {
      heading.focus();
    }
  }

  // Imports go through the server, which validates every field before anything is saved.
  function importFile(file) {
    var reader = new FileReader();
    reader.onload = function () {
      var plan;
      try {
        plan = JSON.parse(String(reader.result));
      } catch (ignored) {
        announce("That file is not a Toran plan.");
        return;
      }
      fetch("/api/plan/recompute", {
        method: "POST",
        headers: { "Content-Type": "application/json", "HX-Request": "true" },
        body: JSON.stringify({ plan: plan }),
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error(String(response.status));
          }
          return response.text();
        })
        .then(function (html) {
          showDashboard(html);
          announce("Plan opened from the file.");
        })
        .catch(function () {
          announce("That file is not a valid Toran plan.");
        });
    };
    reader.readAsText(file);
  }

  document.addEventListener("htmx:afterSwap", function (evt) {
    saveFrom(evt.detail.target);
  });

  document.addEventListener("click", function (evt) {
    var button = evt.target.closest ? evt.target.closest("[data-action]") : null;
    if (!button) {
      return;
    }
    if (button.dataset.action === "export-plan") {
      var raw = read(KEY) || read(PREVIOUS_KEY);
      if (raw) {
        download(raw, "toran-plan.json");
      } else {
        announce("There is no plan saved in this browser yet.");
      }
    }
  });

  document.addEventListener("change", function (evt) {
    var input = evt.target;
    if (input.dataset && input.dataset.action === "import-plan" && input.files.length) {
      importFile(input.files[0]);
      input.value = "";
    }
  });

  window.addEventListener("storage", function (evt) {
    if (evt.key === KEY) {
      announce("This plan was changed in another tab. Reload the page to see the latest version.");
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var plan = load();
    document.querySelectorAll("[data-when-saved]").forEach(function (el) {
      el.hidden = !plan;
    });
    document.querySelectorAll("[data-when-empty]").forEach(function (el) {
      el.hidden = Boolean(plan);
    });
    var loader = document.querySelector("[data-load-saved-plan]");
    if (loader && plan) {
      htmx.trigger(loader, "toran:load");
    }
  });

  window.ToranState = { load: load };
})();
