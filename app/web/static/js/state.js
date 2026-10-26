// Toran plan state. The server is stateless: the plan lives in this browser's localStorage.
// Every plan-changing response carries the plan in #plan-state; this file saves it, adds it
// to requests that need it, keeps one level of undo, and handles export, import and changes
// from other tabs.
(function () {
  "use strict";

  var KEY = "toran.plan";
  var PREVIOUS_KEY = "toran.plan.previous";
  // One level of undo: the plan as it was before the last change, including a new plan or
  // the sample replacing a saved one.
  var UNDO_KEY = "toran.plan.undo";
  // Notices from a new plan, shown once on /plan after the home page hands over.
  var FLASH_KEY = "toran.flash";
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

  function remove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (ignored) {
      // nothing more to do
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
    remove(KEY);
    announce("Your saved plan is from an older version of Toran and was set aside. Download it below.");
    return null;
  }

  // Save a plan. The plan it replaces becomes the undo point, unless `keepUndo` is set.
  function save(raw, keepUndo) {
    var current = read(KEY);
    if (!keepUndo && current && current !== raw) {
      write(UNDO_KEY, current);
    }
    if (!write(KEY, raw)) {
      return false;
    }
    if (navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(function () {});
    }
    return true;
  }

  // The "Saved in this browser" text and the undo buttons follow what is stored.
  function showStatus(saved) {
    document.querySelectorAll("[data-save-status]").forEach(function (el) {
      el.textContent = saved ? "Saved in this browser." : "Not saved. Download the plan file to keep it.";
    });
    var canUndo = Boolean(read(UNDO_KEY));
    document.querySelectorAll("[data-action='undo-plan']").forEach(function (button) {
      button.hidden = !canUndo;
    });
  }

  function keepFlash(root) {
    var notices = Array.prototype.map.call(root.querySelectorAll(".notice"), function (el) {
      return el.textContent.trim();
    });
    try {
      window.sessionStorage.setItem(FLASH_KEY, JSON.stringify(notices));
    } catch (ignored) {
      // the notices are a courtesy; the plan itself is saved
    }
  }

  // Show notices handed over from the home page once, as plain text.
  function showFlash(root) {
    var raw = null;
    try {
      raw = window.sessionStorage.getItem(FLASH_KEY);
      window.sessionStorage.removeItem(FLASH_KEY);
    } catch (ignored) {
      return;
    }
    var heading = root.querySelector ? root.querySelector("#plan-heading") : null;
    if (!raw || !heading) {
      return;
    }
    var after = heading.parentNode.querySelector(".meta") || heading;
    JSON.parse(raw).forEach(function (text) {
      var p = document.createElement("p");
      p.className = "notice";
      p.textContent = text;
      after.insertAdjacentElement("afterend", p);
      after = p;
    });
  }

  // Save the plan from freshly swapped content, if it carries one. On the home page the
  // new plan then opens on /plan; if it could not be saved it is shown where it is.
  function saveFrom(root, keepUndo) {
    var holder = root.querySelector ? root.querySelector("#plan-state") : null;
    if (!holder || !holder.dataset.plan) {
      return;
    }
    var saved = false;
    try {
      var plan = JSON.parse(holder.dataset.plan);
      if (plan.schema_version === SCHEMA_VERSION) {
        saved = save(holder.dataset.plan, keepUndo);
      }
    } catch (ignored) {
      announce("The plan could not be read, so it was not saved.");
    }
    showStatus(saved);
    if (root.dataset && root.dataset.openPlan) {
      if (saved) {
        keepFlash(root);
        window.location.assign(root.dataset.openPlan);
      } else {
        root.hidden = false;
      }
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

  function showDashboard(html, keepUndo) {
    var target = document.getElementById("dashboard");
    if (!target) {
      return;
    }
    target.innerHTML = html;
    htmx.process(target);
    saveFrom(target, keepUndo);
    document.dispatchEvent(new CustomEvent("toran:shown", { detail: { target: target } }));
    var heading = target.querySelector("[data-focus]");
    if (heading) {
      heading.focus();
    }
  }

  // Plans from a file or the undo point go through the server, which validates every field
  // before anything is saved.
  function openPlan(plan, keepUndo) {
    return fetch("/api/plan/recompute", {
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
        showDashboard(html, keepUndo);
      });
  }

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
      openPlan(plan)
        .then(function () {
          announce("Plan opened from the file. Undo last change brings back the plan you had.");
        })
        .catch(function () {
          announce("That file is not a valid Toran plan.");
        });
    };
    reader.readAsText(file);
  }

  // Undo is one level: after it, the undo point is gone.
  function undo() {
    var raw = read(UNDO_KEY);
    if (!raw) {
      announce("There is nothing to undo.");
      return;
    }
    var plan;
    try {
      plan = JSON.parse(raw);
    } catch (ignored) {
      remove(UNDO_KEY);
      announce("The earlier plan could not be read.");
      return;
    }
    openPlan(plan, true)
      .then(function () {
        remove(UNDO_KEY);
        showStatus(true);
        announce("Undone. The plan is back to how it was before the last change.");
      })
      .catch(function () {
        announce("The earlier plan could not be opened.");
      });
  }

  document.addEventListener("htmx:afterSwap", function (evt) {
    saveFrom(evt.detail.target);
    showFlash(evt.detail.target);
  });

  document.addEventListener("click", function (evt) {
    var button = evt.target.closest ? evt.target.closest("[data-action]") : null;
    if (!button) {
      return;
    }
    if (button.dataset.action === "undo-plan") {
      undo();
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
