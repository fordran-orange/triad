(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var catalog = null;

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function notice(msg, isErr) {
    var n = $("notice");
    n.textContent = msg;
    n.className = "card" + (isErr ? " err" : "");
  }
  function label(k) { return String(k).replace(/_/g, " "); }

  // Render any value as readable nested definition lists / bullet lists.
  function render(v, parent) {
    if (v === null || v === undefined) { parent.appendChild(el("span", "not provided")); return; }
    if (Array.isArray(v)) {
      if (!v.length) { parent.appendChild(el("span", "none listed")); return; }
      var ul = el("ul");
      v.forEach(function (x) { var li = el("li"); render(x, li); ul.appendChild(li); });
      parent.appendChild(ul);
    } else if (typeof v === "object") {
      var dl = el("dl");
      Object.keys(v).forEach(function (k) {
        dl.appendChild(el("dt", label(k)));
        var dd = el("dd"); render(v[k], dd); dl.appendChild(dd);
      });
      parent.appendChild(dl);
    } else {
      parent.appendChild(el("span", v));
    }
  }
  function card(title, value) {
    var c = el("div", null, "card");
    c.appendChild(el("h3", title));
    render(value, c);
    return c;
  }

  function getJson(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (t) {
        var body = null;
        try { body = t ? JSON.parse(t) : null; } catch (e) { body = null; }
        if (!r.ok) {
          var d = body && (body.detail || body.error || body.message);
          if (d && typeof d !== "string") {
            d = Array.isArray(d) ? d.map(function (x) { return x && x.msg ? x.msg : String(x); }).join("; ") : "see request details";
          }
          throw new Error("HTTP " + r.status + ": " + (d || t.slice(0, 300) || "no detail"));
        }
        return body;
      });
    });
  }

  function fill(sel, items, valueOf, textOf) {
    clear(sel);
    items.forEach(function (i) {
      var o = el("option", textOf(i)); o.value = valueOf(i); sel.appendChild(o);
    });
  }

  function currentDataset() {
    var id = $("dataset").value;
    var l = (catalog && catalog.datasets) || [];
    for (var i = 0; i < l.length; i++) if (l[i].dataset_id === id) return l[i];
    return null;
  }

  function showDataset() {
    var box = $("dsinfo");
    clear(box);
    var d = currentDataset();
    if (!d) { box.appendChild(el("p", "No dataset selected. Nothing is verified.")); return; }
    box.appendChild(el("h2", "Selected dataset"));
    var m = el("span", d.mode, "tag");
    var q = el("span", "quality " + d.quality, "tag");
    box.appendChild(m); box.appendChild(document.createTextNode(" ")); box.appendChild(q);
    var cp = d.canonical_paths || [];
    if (!cp.length) box.appendChild(el("p", "No canonical paths recorded: this archive is not loadable as validated Core research input."));
    if (d.mode === "REAL" && d.quality !== "PASS") box.appendChild(el("p", "Quality is not PASS. This is not a readiness pass."));
    if (d.mode === "FIXTURE") box.appendChild(el("p", "FIXTURE data is synthetic and says nothing about real-market coverage."));
    render({
      provider: d.provider, symbols: d.symbols, timeframe: d.resolution,
      start: d.start, end: d.end, rows: d.rows, calendar: d.calendar,
      version: d.version, checksum: d.checksum, canonical_paths: cp,
      required_fields: "Open, High, Low, Close, Volume (checked by Core on evaluation)",
      raw_provenance: d.raw_provenance, license_use: d.license_use,
      known_gaps: d.known_gaps
    }, box);
    $("symbols").value = (d.symbols || []).join(",");
    $("mode").value = d.mode === "FIXTURE" ? "FIXTURE" : "REAL";
    if (d.mode === "FIXTURE") { $("start").value = d.start || ""; $("end").value = d.end || ""; }
  }

  function showSource() {
    var id = $("source").value;
    var l = (catalog && catalog.sources) || [];
    for (var i = 0; i < l.length; i++) if (l[i].integration_id === id) {
      var s = l[i];
      notice("Source " + s.name + ": status " + s.status + "; category " + s.category +
        ". Capability status does not establish usable coverage.");
      return;
    }
  }

  function evaluate() {
    var btn = $("evaluate");
    var res = $("result");
    var symbols = $("symbols").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    var body = {
      integration_id: $("source").value, dataset_id: $("dataset").value,
      symbols: symbols, start: $("start").value.trim(), end: $("end").value.trim(),
      mode: $("mode").value, universe: $("universe").value.trim(),
      membership_rule: $("membership").value
    };
    if (!body.dataset_id || !symbols.length || !body.start || !body.end) {
      clear(res);
      res.appendChild(card("Missing input", "Select a dataset and provide symbols, start and end."));
      res.firstChild.className += " err";
      return;
    }
    btn.disabled = true;
    clear(res);
    res.appendChild(el("p", "Evaluating…"));
    getJson("/api/core/research-readiness/evaluate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) {
      clear(res);
      if (!r) { res.appendChild(card("Empty response", "Core returned no evidence. Readiness is unverified.")); return; }
      var head = el("div", null, "card");
      head.appendChild(el("h2", "Status: " + (r.status === undefined ? "not reported" : r.status)));
      head.appendChild(el("p", "Only Core-reported status is shown. Missing evidence is unverified, not a confirmed failure."));
      res.appendChild(head);
      [["request", "Request"], ["source", "Source"], ["dataset", "Dataset"],
       ["expected_coverage", "Expected coverage"], ["missing", "Missing"],
       ["checks", "Checks"], ["independent_evidence", "Independent evidence"],
       ["strategy_notice", "Strategy notice"]].forEach(function (p) {
        res.appendChild(card(p[1], r[p[0]]));
      });
    }).catch(function (e) {
      clear(res);
      var c = card("Evaluation failed", e.message);
      c.className += " err";
      res.appendChild(c);
    }).then(function () { btn.disabled = false; });
  }

  $("source").addEventListener("change", showSource);
  $("dataset").addEventListener("change", showDataset);
  $("evaluate").addEventListener("click", evaluate);

  getJson("/api/core/research-readiness").then(function (c) {
    catalog = c || {};
    var s = catalog.sources || [], d = catalog.datasets || [];
    fill($("source"), s, function (x) { return x.integration_id; },
      function (x) { return x.name + " (" + x.status + ")"; });
    fill($("dataset"), d, function (x) { return x.dataset_id; },
      function (x) { return x.mode + " " + (x.symbols || []).join("/") + " " + x.resolution + " quality " + x.quality; });
    var lim = (catalog.limitations || []).join(" | ");
    if (!s.length && !d.length) notice("Core returned no sources or datasets. Readiness is unverified.");
    else { showSource(); if (lim) $("notice").textContent += " Limits: " + lim; }
    showDataset();
    $("evaluate").disabled = !d.length;
  }).catch(function (e) {
    notice("Could not load Core catalog: " + e.message + ". Readiness is unverified, not confirmed failed.", true);
  });
})();
