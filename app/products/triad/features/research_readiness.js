(function () {
  "use strict";
  var CATALOG = "/api/core/research-readiness";
  var EVAL = "/api/core/research-readiness/evaluate";
  var $ = function (id) { return document.getElementById(id); };
  var ids = ["source", "dataset", "symbols", "start", "end", "mode", "universe", "membership", "evaluate"];
  var catalog = null;
  var seq = 0;
  var busy = false;

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function notice(msg, cls) {
    var n = $("notice");
    n.textContent = msg;
    n.className = cls || "";
  }
  function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function label(k) { return String(k).replace(/_/g, " "); }

  function render(v, depth) {
    if (v === null || v === undefined || v === "") return el("span", "none recorded");
    if (Array.isArray(v)) {
      if (!v.length) return el("span", "none recorded");
      var ul = el("ul");
      v.forEach(function (x) {
        var li = el("li");
        li.appendChild(render(x, depth + 1));
        ul.appendChild(li);
      });
      return ul;
    }
    if (isObj(v)) {
      var keys = Object.keys(v);
      if (!keys.length) return el("span", "none recorded");
      var dl = el("dl");
      keys.forEach(function (k) {
        dl.appendChild(el("dt", label(k)));
        var dd = el("dd");
        dd.appendChild(depth > 5 ? el("span", "(nested detail omitted)") : render(v[k], depth + 1));
        dl.appendChild(dd);
      });
      return dl;
    }
    return el("span", v);
  }

  function request(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (t) {
        var body = null, parsed = false;
        try { body = JSON.parse(t); parsed = true; } catch (e) { parsed = false; }
        if (!r.ok) {
          var d = parsed && isObj(body) && body.detail !== undefined ? body.detail : t;
          if (typeof d !== "string") d = flat(d);
          throw new Error("Core returned HTTP " + r.status + ": " + (d || r.statusText || "no detail"));
        }
        if (!parsed) throw new Error("Core response was not valid JSON.");
        return body;
      });
    });
  }
  function flat(d) {
    if (Array.isArray(d)) return d.map(flat).join("; ");
    if (isObj(d)) return d.msg ? String(d.msg) : Object.keys(d).map(function (k) { return k + ": " + flat(d[k]); }).join("; ");
    return String(d);
  }

  function setBusy(b) {
    busy = b;
    ids.forEach(function (i) { $(i).disabled = b || (!catalog && i !== "evaluate" ? false : false); });
    $("evaluate").disabled = b || !catalog;
  }

  function selectedSource() {
    var id = $("source").value;
    return (catalog.sources || []).filter(function (s) { return s.integration_id === id; })[0] || null;
  }
  function selectedDataset() {
    var id = $("dataset").value;
    return (catalog.datasets || []).filter(function (d) { return d.dataset_id === id; })[0] || null;
  }

  function invalidate() {
    seq++;
    var r = $("result");
    clear(r);
    r.textContent = "Inputs changed. Run an evaluation to see results for them.";
  }

  function showDetail() {
    var box = $("detail");
    clear(box);
    var d = selectedDataset(), s = selectedSource();
    if (!d || !s) { box.textContent = "Nothing selected."; return; }
    var p = el("p");
    p.appendChild(el("span", d.mode, "tag"));
    p.appendChild(document.createTextNode(" " + (d.mode === "REAL" ? "Real-market archive." : "Fixture data, not real-market coverage.")));
    box.appendChild(p);
    var view = {
      source: { name: s.name, category: s.category, status: s.status, environment: s.environment, notes: s.notes },
      dataset_id: d.dataset_id, provider: d.provider, symbols: d.symbols, resolution: d.resolution,
      start: d.start, end: d.end, rows: d.rows, reported_quality: d.quality, calendar: d.calendar,
      canonical_paths: d.canonical_paths && d.canonical_paths.length ? d.canonical_paths : "none recorded",
      raw_provenance: d.raw_provenance, license_use: d.license_use, known_gaps: d.known_gaps
    };
    box.appendChild(render(view, 0));
    if (catalog.limitations) {
      box.appendChild(el("h3", "Core limitations"));
      box.appendChild(render(catalog.limitations, 0));
    }
  }

  function toLocal(iso) {
    return typeof iso === "string" ? iso.slice(0, 16) : "";
  }
  function onDataset() {
    var d = selectedDataset();
    if (d) {
      $("symbols").value = (d.symbols || []).join(",");
      $("universe").value = (d.symbols || []).join(",");
      if (d.mode === "REAL" || d.mode === "FIXTURE") $("mode").value = d.mode;
      $("start").value = toLocal(d.start);
      $("end").value = toLocal(d.end);
    }
    invalidate();
    showDetail();
  }

  function fill(sel, items, val, txt) {
    clear(sel);
    items.forEach(function (x) {
      var o = el("option", txt(x));
      o.value = val(x);
      sel.appendChild(o);
    });
  }

  function load() {
    setBusy(true);
    request(CATALOG).then(function (c) {
      if (!isObj(c) || !Array.isArray(c.sources) || !Array.isArray(c.datasets)) {
        throw new Error("Core response lacked the expected sources and datasets lists.");
      }
      catalog = c;
      fill($("source"), c.sources, function (s) { return s.integration_id; },
        function (s) { return s.name + " (" + s.status + ")"; });
      fill($("dataset"), c.datasets, function (d) { return d.dataset_id; },
        function (d) { return "[" + d.mode + "] " + (d.symbols || []).join(",") + " " + d.resolution + " quality " + d.quality; });
      if (!c.datasets.length) {
        notice("Core listed no datasets. Nothing to evaluate.", "warn");
        setBusy(false);
        $("evaluate").disabled = true;
        return;
      }
      var local = c.sources.filter(function (s) { return s.integration_id === "local-canonical"; })[0];
      if (local) $("source").value = local.integration_id;
      notice("Live Core discovery loaded (policy " + (c.policy || "unreported") + "). Select a source and dataset, then evaluate.");
      setBusy(false);
      onDataset();
    }).catch(function (e) {
      catalog = null;
      notice("Core discovery unavailable: " + e.message + " No readiness conclusion is drawn.", "err");
      setBusy(false);
      $("evaluate").disabled = true;
    });
  }

  function iso(v) { return v ? v + ":00Z" : ""; }

  function evaluate(ev) {
    ev.preventDefault();
    if (busy || !catalog) return;
    var body = {
      integration_id: $("source").value,
      dataset_id: $("dataset").value,
      symbols: $("symbols").value.split(",").map(function (x) { return x.trim(); }).filter(Boolean),
      start: iso($("start").value),
      end: iso($("end").value),
      mode: $("mode").value,
      universe: $("universe").value.trim(),
      membership_rule: $("membership").value
    };
    if (!body.start || !body.end || !body.symbols.length) {
      notice("Enter symbols, a start and an end before evaluating.", "err");
      return;
    }
    var mine = ++seq;
    setBusy(true);
    notice("Evaluating (read-only)…");
    request(EVAL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (mine !== seq) return;
      if (!isObj(res) || !Object.keys(res).length || res.status === undefined) {
        throw new Error("Core returned no usable evaluation. Readiness is unknown.");
      }
      var r = $("result");
      clear(r);
      r.appendChild(el("h3", "Status: " + res.status));
      r.appendChild(el("p", "Evaluated inputs as submitted:"));
      r.appendChild(render(body, 0));
      r.appendChild(render(res, 0));
      notice("Evaluation returned by Core.");
      r.focus();
    }).catch(function (e) {
      if (mine !== seq) return;
      clear($("result"));
      $("result").textContent = "No result.";
      notice("Evaluation failed: " + e.message, "err");
    }).then(function () {
      if (mine === seq) setBusy(false);
    });
  }

  $("form").addEventListener("submit", evaluate);
  $("dataset").addEventListener("change", onDataset);
  $("source").addEventListener("change", function () { invalidate(); showDetail(); });
  ["symbols", "start", "end", "mode", "universe", "membership"].forEach(function (i) {
    $(i).addEventListener("input", invalidate);
  });
  load();
})();
