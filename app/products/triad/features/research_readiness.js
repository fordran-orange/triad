(function () {
  'use strict';
  var CATALOG = '/api/core/research-readiness';
  var EVALUATE = '/api/core/research-readiness/evaluate';
  var SNAPSHOT_DATE = '2026-09-19';
  var SNAPSHOT = [
    { id: 'ITOT', name: 'HFDataLibrary ITOT 1m archive' },
    { id: 'QQQ', name: 'HFDataLibrary QQQ 1m archive' },
    { id: 'SPY', name: 'HFDataLibrary SPY 1m archive' }
  ];
  var SNAPSHOT_GAPS = [
    'Core requires UNADJUSTED prices; vendor documents adjusted prices',
    'Sessions incomplete or anomalous; Core requires complete regular sessions',
    'Core calendar supports 2026 only; archives span ten years',
    'Local vendor version, adjustment factors and interval-label convention not authenticated',
    'Local download license and vintage not supplied'
  ];
  var $ = function (id) { return document.getElementById(id); };
  var datasets = [];

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    if (cls) { n.className = cls; }
    return n;
  }

  function notice(text, kind) {
    var n = $('notice');
    n.textContent = text;
    n.setAttribute('data-kind', kind || 'info');
  }

  function label(key) { return String(key).replace(/_/g, ' '); }

  function render(value, depth) {
    if (value === null || value === undefined || value === '') { return el('span', 'none recorded'); }
    if (Array.isArray(value)) {
      if (!value.length) { return el('span', 'none'); }
      var ul = el('ul');
      value.forEach(function (v) {
        var li = el('li');
        li.appendChild(render(v, depth + 1));
        ul.appendChild(li);
      });
      return ul;
    }
    if (typeof value === 'object') {
      var keys = Object.keys(value);
      if (!keys.length) { return el('span', 'none'); }
      var dl = el('dl');
      keys.forEach(function (k) {
        dl.appendChild(el('dt', label(k)));
        var dd = el('dd');
        dd.appendChild(render(value[k], depth + 1));
        dl.appendChild(dd);
      });
      return dl;
    }
    var s = String(value);
    var cls = /^(FAIL|FAILED|MISSING)$/.test(s) ? 'fail' : (/^(PASS|PASSED)$/.test(s) ? 'ok' : '');
    return el('span', s, cls);
  }

  function section(title, value) {
    var s = el('section');
    s.appendChild(el('h2', title));
    s.appendChild(render(value, 0));
    return s;
  }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function errorText(body, status) {
    var d = body && (body.detail || body.error || body.message);
    if (typeof d === 'string') { return d; }
    if (Array.isArray(d)) {
      return d.map(function (e) { return e && e.msg ? e.msg : String(e); }).join('; ');
    }
    return 'Request failed (HTTP ' + status + ').';
  }

  function request(url, options) {
    return fetch(url, options).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (body) {
        if (!r.ok) { throw new Error(errorText(body, r.status)); }
        return body;
      });
    });
  }

  function renderSnapshot(reason) {
    var box = $('result');
    clear(box);
    var s = el('section');
    s.appendChild(el('h2', 'Supplied snapshot, not live Core output'));
    s.appendChild(el('p', 'Attribution: supplied current_data snapshot dated ' + SNAPSHOT_DATE + '. ' + reason + ' Core readiness is not established by this view and no pass or failure is inferred here.'));
    var ul = el('ul');
    SNAPSHOT.forEach(function (d) {
      ul.appendChild(el('li', d.name + ' (' + d.id + '): recorded REAL archive; reported quality FAIL; no canonical paths recorded.'));
    });
    s.appendChild(ul);
    s.appendChild(el('h3', 'Unresolved evidence gaps'));
    s.appendChild(render(SNAPSHOT_GAPS, 0));
    s.appendChild(el('p', 'Usable historical research coverage is not established by the supplied evidence. Data readiness is separate from strategy edge.'));
    box.appendChild(s);
  }

  function selected() {
    var id = $('dataset').value;
    for (var i = 0; i < datasets.length; i++) { if (datasets[i].dataset_id === id) { return datasets[i]; } }
    return null;
  }

  function onDataset() {
    var d = selected();
    if (!d) { return; }
    $('mode').value = d.mode;
    $('symbols').value = (d.symbols || []).join(', ');
    $('universe').value = (d.symbols || []).join(', ');
    $('start').value = String(d.start || '').slice(0, 16);
    $('end').value = String(d.end || '').slice(0, 16);
    var box = $('result');
    clear(box);
    var s = el('section');
    s.appendChild(el('h2', 'Selected dataset: ' + d.mode + ' / quality ' + d.quality));
    s.appendChild(render({
      provider: d.provider, symbols: d.symbols, resolution: d.resolution,
      start: d.start, end: d.end, rows: d.rows, calendar: d.calendar,
      canonical_paths: (d.canonical_paths && d.canonical_paths.length) ? d.canonical_paths : 'none recorded',
      raw_provenance: d.raw_provenance, license_use: d.license_use, known_gaps: d.known_gaps
    }, 0));
    box.appendChild(s);
  }

  function iso(v) { return v ? v + ':00Z'.slice(v.length > 16 ? 3 : 0) : ''; }

  function evaluate() {
    var d = selected();
    var src = $('source').value;
    if (!src || !d) { notice('Choose a source and a dataset first.', 'error'); return; }
    var symbols = $('symbols').value.split(',').map(function (x) { return x.trim().toUpperCase(); }).filter(Boolean);
    var body = {
      integration_id: src, dataset_id: d.dataset_id, symbols: symbols,
      start: iso($('start').value), end: iso($('end').value),
      mode: $('mode').value, universe: $('universe').value.trim(),
      membership_rule: $('membership').value
    };
    $('evaluate').disabled = true;
    notice('Evaluating (read-only)…');
    request(EVALUATE, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) {
        var box = $('result');
        clear(box);
        ['status', 'request', 'source', 'dataset', 'expected_coverage', 'missing', 'checks', 'independent_evidence', 'strategy_notice'].forEach(function (k) {
          if (r && k in r) { box.appendChild(section(label(k), r[k])); }
        });
        notice('Live Core evaluation complete. This reflects data readiness only.');
        box.focus();
      })
      .catch(function (e) { notice('Evaluation failed: ' + e.message, 'error'); })
      .then(function () { $('evaluate').disabled = false; });
  }

  function fill(select, items, text) {
    clear(select);
    items.forEach(function (it) {
      var o = el('option', text(it));
      o.value = it.value;
      select.appendChild(o);
    });
  }

  function load() {
    request(CATALOG).then(function (c) {
      var sources = (c && c.sources) || [];
      datasets = (c && c.datasets) || [];
      fill($('source'), sources.map(function (s) { return { value: s.integration_id, s: s }; }), function (i) {
        return i.s.name + ' [' + i.s.category + ', ' + i.s.status + ']';
      });
      fill($('dataset'), datasets.map(function (d) { return { value: d.dataset_id, d: d }; }), function (i) {
        return '[' + i.d.mode + '] ' + (i.d.symbols || []).join(',') + ' ' + i.d.resolution + ' quality ' + i.d.quality + ' - ' + i.d.dataset_id;
      });
      if (!datasets.length) {
        notice('Core reports no datasets.');
        renderSnapshot('Core returned an empty dataset list.');
        return;
      }
      notice('Live Core catalog loaded. Choose a dataset and evaluate; nothing is fetched or acquired.');
      onDataset();
    }).catch(function (e) {
      notice('Core catalog unavailable: ' + e.message, 'error');
      renderSnapshot('Live Core catalog could not be loaded.');
    });
  }

  $('dataset').addEventListener('change', onDataset);
  $('evaluate').addEventListener('click', evaluate);
  load();
}());
