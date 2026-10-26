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
  };

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
      if (!field.name || field.disabled || field.type === "submit" || field.type === "button") {
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
        var item = {};
        item[field.dataset.listKey || field.name] = value;
        Object.assign(item, JSON.parse(field.dataset.listExtra || "{}"));
        body[field.dataset.list] = (body[field.dataset.list] || []).concat([item]);
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

  // Move keyboard and screen reader focus to the heading of newly swapped content.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var heading = evt.detail.target.querySelector("[data-focus]");
    if (heading) {
      heading.focus();
    }
  });
})();
