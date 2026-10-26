// Toran front end. Loaded as a static file: the strict CSP allows no inline scripts.
(function () {
  "use strict";

  // Top-level keys each request shape may send. Anything else in the form is left out,
  // because the API rejects unknown fields.
  var SHAPES = {
    intake: ["text", "answers"],
    generate: ["brief", "brief_source"],
    recompute: ["plan"],
    whatif: ["plan", "changes"],
    adapt: ["plan", "change"],
    apply: ["plan", "change", "option"],
    sample: ["city"],
    people: ["plan", "change"],
    lines: ["plan", "change"],
  };

  function getPath(target, path) {
    return path.split(".").reduce(function (node, part) {
      return node ? node[part] : undefined;
    }, target);
  }

  function setPath(target, path, value) {
    var parts = path.split(".");
    var node = target;
    for (var i = 0; i < parts.length - 1; i++) {
      node[parts[i]] = node[parts[i]] || {};
      node = node[parts[i]];
    }
    node[parts[parts.length - 1]] = value;
  }

  // Build a JSON body from the form: numbers stay numbers, dotted names nest
  // ("brief.city"), answers to follow-up questions become a list, empty fields are left out.
  // Fixed values come from a data-body attribute, and the saved plan is added when the
  // shape needs one.
  function buildBody(elt) {
    var form = elt.closest("form") || elt;
    var shapeName = elt.dataset.shape || form.dataset.shape;
    var shape = SHAPES[shapeName] || null;
    var body = {};
    var answers = [];
    [form.dataset.body, elt.dataset.body].forEach(function (fixed) {
      if (fixed) {
        Object.assign(body, JSON.parse(fixed));
      }
    });
    if (shape && shape.indexOf("plan") !== -1 && window.ToranState) {
      body.plan = window.ToranState.load();
    }
    // A control that triggers its own request (a what-if slider) sends only itself.
    var fields = elt.matches("input, select, textarea") ? [elt] : form.elements || [];
    Array.prototype.forEach.call(fields, function (field) {
      // :disabled also covers fields inside a disabled fieldset; field.disabled does not.
      if (!field.name || field.matches(":disabled") || field.type === "submit" || field.type === "button") {
        return;
      }
      var raw = field.value.trim();
      if (raw === "") {
        return;
      }
      if (field.dataset.answerFor) {
        answers.push({ question: field.dataset.answerFor, answer: raw });
        return;
      }
      var value = field.dataset.type === "int" ? Number(raw) : raw;
      if (field.dataset.list) {
        // Fields with data-list="changes" each add one item, e.g. {"change": "set_total", ...}.
        // The list name may be dotted ("change.shares").
        var item = {};
        item[field.dataset.listKey || field.name] = value;
        Object.assign(item, JSON.parse(field.dataset.listExtra || "{}"));
        setPath(body, field.dataset.list, (getPath(body, field.dataset.list) || []).concat([item]));
        return;
      }
      setPath(body, field.name, value);
    });
    if (answers.length) {
      body.answers = answers;
    }
    if (!shape) {
      return body;
    }
    var shaped = {};
    shape.forEach(function (key) {
      if (key in body) {
        shaped[key] = body[key];
      }
    });
    return shaped;
  }

  htmx.defineExtension("toran-json", {
    onEvent: function (name, evt) {
      if (name === "htmx:configRequest") {
        evt.detail.headers["Content-Type"] = "application/json";
      }
    },
    encodeParameters: function (xhr, parameters, elt) {
      xhr.overrideMimeType("text/html");
      return JSON.stringify(buildBody(elt));
    },
  });

  function announce(message) {
    var live = document.getElementById("live");
    if (live) {
      live.textContent = message;
    }
  }

  function errorMessage(xhr) {
    if (xhr.status === 429) {
      return "Too many requests. Please wait a minute and try again.";
    }
    if (xhr.status === 422) {
      try {
        var detail = JSON.parse(xhr.responseText).detail;
        if (typeof detail === "string") {
          return detail.charAt(0).toUpperCase() + detail.slice(1) + ".";
        }
        var fields = (detail || []).map(function (item) {
          return String(item.loc[item.loc.length - 1]).replace(/_/g, " ");
        });
        return "Please check: " + fields.join(", ") + ".";
      } catch (ignored) {
        return "Please check the form and try again.";
      }
    }
    return "Something went wrong on our side. Please try again.";
  }

  document.addEventListener("htmx:beforeRequest", function () {
    announce("");
  });

  document.addEventListener("htmx:responseError", function (evt) {
    announce(errorMessage(evt.detail.xhr));
  });

  document.addEventListener("htmx:sendError", function () {
    announce("Could not reach Toran. Check your connection and try again.");
  });

  // Forms with a kind select ("Something changed", "Who pays"): only the fields for the
  // chosen kind are shown and sent (disabled fields are left out of the request, and the
  // API rejects unknown fields).
  function syncKind(select) {
    select.form.querySelectorAll("[data-change-kind]").forEach(function (fieldset) {
      var active = fieldset.dataset.changeKind === select.value;
      fieldset.hidden = !active;
      fieldset.disabled = !active;
    });
  }

  function syncChangeKind(root) {
    if (root.querySelectorAll) {
      root.querySelectorAll("[data-change-kind-select]").forEach(syncKind);
    }
  }

  document.addEventListener("change", function (evt) {
    if (evt.target.matches && evt.target.matches("[data-change-kind-select]")) {
      syncKind(evt.target);
    }
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    syncChangeKind(evt.detail.target);
  });

  // Open <details> sections, and choices marked data-keep-value, survive the dashboard being
  // rebuilt around them, so assigning payers line by line does not start over each time.
  var kept = { open: [], values: {} };

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var target = evt.detail.target;
    kept.open = Array.prototype.map.call(target.querySelectorAll("details[open][id]"), function (details) {
      return details.id;
    });
    kept.values = {};
    target.querySelectorAll("[data-keep-value][id]").forEach(function (field) {
      kept.values[field.id] = field.value;
    });
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    kept.open.forEach(function (id) {
      var details = document.getElementById(id);
      if (details) {
        details.open = true;
      }
    });
    Object.keys(kept.values).forEach(function (id) {
      var field = document.getElementById(id);
      if (field && field.querySelector("option[value='" + CSS.escape(kept.values[id]) + "']")) {
        field.value = kept.values[id];
      }
    });
    kept = { open: [], values: {} };
    syncChangeKind(evt.detail.target);
  });

  // Move keyboard and screen reader focus to the heading of newly swapped content.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var heading = evt.detail.target.querySelector("[data-focus]");
    if (heading) {
      heading.focus();
    }
  });
})();
