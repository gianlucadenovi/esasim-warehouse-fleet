// ── EsaSim block ──────────────────────────────────────────────────────
// Fleet sweep view (ws-fleet-sweep-view) · version 1 · view, JavaScript: function render(ctx)
// How many robots? The fleet-size sweep drawn as it runs: orders per hour and cost per order against the fleet, with the cheapest fleet that keeps up.
// Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
// Saved: 2026-11-08
//
// Inputs   ctx.input("id") gives { files, stream }; ctx.rows("id"), ctx.json("id"), ctx.text("id")
//   data        Stream                    Data · several · The Fleet-size sweep block's telemetry
// Settings ctx.params.key
//   (none)
// EsaSim rewrites these lines from the block's definition each time it is saved: change the definition, not them.
// ── end of EsaSim block header ────────────────────────────────────────

/* Fleet sweep view: what the fleet-size sweep found, drawn as it runs.
 * Left: orders per hour against the number of robots, one line per order rate, with the demand as a dashed line.
 * Right: cost per order against the number of robots; the cheapest fleet that meets the demand is marked.
 * Input: the sweep's live telemetry (channel sweep) or its results table (fleet_sweep.csv). */
function render(ctx) {
  var el = ctx.el, P = ctx.params;
  el.innerHTML = '';
  el.style.background = '#0c1016';
  var css = document.createElement('style');
  css.textContent = [
    '.fs{position:absolute;inset:0;display:flex;flex-direction:column;gap:10px;padding:14px;font:13px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#e8edf5;overflow:auto}',
    '.fs .head{display:flex;gap:12px;align-items:center;flex-wrap:wrap}',
    '.fs h2{margin:0;font-size:16px;font-weight:650}',
    '.fs .badge{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(255,255,255,.08)}',
    '.fs .badge i{width:7px;height:7px;border-radius:50%;background:#94a3b8}',
    '.fs .badge.nvidia{color:#86efac}.fs .badge.nvidia i{background:#76b900}',
    '.fs .badge.tenstorrent{color:#c4b5fd}.fs .badge.tenstorrent i{background:#8b5cf6}',
    '.fs .muted{opacity:.62}',
    '.fs .prog{height:4px;border-radius:2px;background:rgba(255,255,255,.08);overflow:hidden;flex:1;min-width:120px;max-width:320px}',
    '.fs .prog b{display:block;height:100%;background:linear-gradient(90deg,#0ea5e9,#22d3ee);transition:width .4s}',
    '.fs .stats{display:flex;gap:10px;flex-wrap:wrap}',
    '.fs .stat{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:8px 12px;min-width:130px}',
    '.fs .stat span{display:block;font-size:11px;opacity:.6;text-transform:uppercase;letter-spacing:.5px}',
    '.fs .stat b{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}',
    '.fs .charts{display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:1;min-height:260px}',
    '.fs .panel{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;min-height:240px}',
    '.fs .panel h3{margin:0 0 6px;font-size:12.5px;font-weight:600;opacity:.85}',
    '.fs .panel canvas{flex:1;width:100%;min-height:200px}',
    '.fs .picks{display:flex;gap:10px;flex-wrap:wrap}',
    '.fs .pick{flex:1;min-width:200px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-left:3px solid var(--c);border-radius:10px;padding:8px 12px}',
    '.fs .pick b{font-size:15px}',
    '.fs .legend{display:flex;gap:12px;font-size:12px;flex-wrap:wrap}',
    '.fs .legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:5px;vertical-align:3px}',
    '@media (max-width:760px){.fs .charts{grid-template-columns:1fr}}'
  ].join('\n');
  el.appendChild(css);
  var root = document.createElement('div'); root.className = 'fs'; el.appendChild(root);
  root.innerHTML =
    '<div class="head"><h2>How many robots?</h2><span class="badge" data-k="badge"><i></i><span>waiting for the sweep</span></span><span class="muted" data-k="what"></span><div class="prog"><b data-k="bar" style="width:0"></b></div></div>' +
    '<div class="stats">' +
    '<div class="stat"><span>Scenarios</span><b data-k="sc">–</b></div>' +
    '<div class="stat"><span>Simulated robot-hours</span><b data-k="rh">–</b></div>' +
    '<div class="stat"><span>Time on this machine</span><b data-k="wall">–</b></div>' +
    '<div class="stat"><span>Speed</span><b data-k="speed">–</b></div>' +
    '</div>' +
    '<div class="legend" data-k="legend"></div>' +
    '<div class="charts"><div class="panel"><h3>Orders per hour delivered</h3><canvas data-k="c1"></canvas></div><div class="panel"><h3 data-k="costT">Robot cost per order</h3><canvas data-k="c2"></canvas></div></div>' +
    '<div class="picks" data-k="picks"></div>';
  var $ = function (k) { return root.querySelector('[data-k="' + k + '"]'); };
  var COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#f472b6', '#a78bfa', '#f87171'];
  var state = { rows: [], meta: null, run: null, done: null };

  function fmt(n, d) { return n == null || isNaN(n) ? '–' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
  function mmss(s) { s = Math.max(0, Math.round(s)); var m = Math.floor(s / 60); return m + ':' + ('0' + (s % 60)).slice(-2); }
  function money(v) { return v == null ? '–' : (v < 1 ? '$' + v.toFixed(3) : '$' + v.toFixed(2)); }

  function load() {
    var st = ctx.input('data').stream || [];
    var items = st.filter(function (i) { return i.channel === 'sweep' && i.data; });
    if (items.length) {
      state.meta = null; state.run = null; state.done = null;
      items.forEach(function (i) {
        var d = i.data;
        if (d.phase === 'start') { state.meta = d; state.done = null; state.rows = []; }
        if (d.phase === 'running') { state.run = d; if (d.rows) state.rows = d.rows; }
        if (d.phase === 'done') { state.done = d; state.rows = d.rows; }
      });
      draw();
      return;
    }
    ctx.rows('data').then(function (rows) {
      state.rows = rows.filter(function (r) { return r.fleet != null && r.orders_h != null; }).map(function (r) {
        return { fleet: +r.fleet, order_rate: +r.order_rate, orders_h: +r.orders_h, served_pct: +r.served_pct, avg_order_s: +r.avg_order_s, cost_per_order: r.cost_per_order === '' || r.cost_per_order == null ? null : +r.cost_per_order, utilization: +r.utilization };
      });
      draw();
    });
  }

  function best(rate) {
    var rs = state.rows.filter(function (r) { return r.order_rate === rate; });
    var ok = rs.filter(function (r) { return r.served_pct >= 98 && r.cost_per_order != null; });
    if (ok.length) return { r: ok.reduce(function (a, b) { return b.cost_per_order < a.cost_per_order ? b : a; }), ok: true };
    if (!rs.length) return null;
    return { r: rs.reduce(function (a, b) { return b.orders_h > a.orders_h ? b : a; }), ok: false };
  }

  function chart(canvas, key, opts) {
    var dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (w < 10 || h < 10) return;
    canvas.width = w * dpr; canvas.height = h * dpr;
    var g = canvas.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    var rows = state.rows.filter(function (r) { return r[key] != null && isFinite(r[key]); });
    var rates = Array.from(new Set(state.rows.map(function (r) { return r.order_rate; }))).sort(function (a, b) { return a - b; });
    var fleets = Array.from(new Set(state.rows.map(function (r) { return r.fleet; }))).sort(function (a, b) { return a - b; });
    var L = 52, R = 14, T = 10, B = 30;
    var xmax = fleets.length ? fleets[fleets.length - 1] : 50, xmin = 0;
    var ys = rows.map(function (r) { return r[key]; });
    if (opts.demand) ys = ys.concat(rates);
    var ymax = ys.length ? Math.max.apply(null, ys) * 1.08 : 1, ymin = 0;
    if (opts.cap) ymax = Math.min(ymax, opts.cap(rows));
    function X(v) { return L + (v - xmin) / (xmax - xmin || 1) * (w - L - R); }
    function Y(v) { return h - B - (v - ymin) / (ymax - ymin || 1) * (h - T - B); }
    // grid
    g.strokeStyle = 'rgba(255,255,255,.07)'; g.fillStyle = 'rgba(232,237,245,.55)'; g.font = '11px system-ui,sans-serif'; g.lineWidth = 1;
    var step = niceStep(ymax / 5);
    for (var v = 0; v <= ymax + 1e-9; v += step) { g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(w - R, Y(v)); g.stroke(); g.textAlign = 'right'; g.fillText(opts.fmt(v), L - 6, Y(v) + 4); }
    var xs = niceStep(xmax / 8);
    g.textAlign = 'center';
    for (v = 0; v <= xmax + 1e-9; v += xs) { g.fillText(String(v), X(v), h - B + 15); }
    g.fillText('robots', X(xmax / 2), h - 2);
    // demand lines
    if (opts.demand) rates.forEach(function (r, i) {
      g.strokeStyle = COLORS[i % COLORS.length]; g.globalAlpha = 0.45; g.setLineDash([5, 5]);
      g.beginPath(); g.moveTo(L, Y(r)); g.lineTo(w - R, Y(r)); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
    });
    // series
    rates.forEach(function (r, i) {
      var c = COLORS[i % COLORS.length], pts = rows.filter(function (q) { return q.order_rate === r; }).sort(function (a, b) { return a.fleet - b.fleet; });
      if (!pts.length) return;
      g.strokeStyle = c; g.lineWidth = 2.2; g.beginPath();
      pts.forEach(function (q, j) { var y = Math.min(q[key], ymax); if (j) g.lineTo(X(q.fleet), Y(y)); else g.moveTo(X(q.fleet), Y(y)); });
      g.stroke();
      // soft fill under the throughput lines
      if (opts.fill) { g.lineTo(X(pts[pts.length - 1].fleet), Y(0)); g.lineTo(X(pts[0].fleet), Y(0)); g.closePath(); var gr = g.createLinearGradient(0, T, 0, h - B); gr.addColorStop(0, c + '33'); gr.addColorStop(1, c + '00'); g.fillStyle = gr; g.fill(); }
      pts.forEach(function (q) { g.fillStyle = '#0c1016'; g.strokeStyle = c; g.lineWidth = 2; g.beginPath(); g.arc(X(q.fleet), Y(Math.min(q[key], ymax)), 3.2, 0, 6.283); g.fill(); g.stroke(); });
      var b = best(r);
      if (b && b.ok && b.r[key] != null) {
        var bx = X(b.r.fleet), by = Y(Math.min(b.r[key], ymax));
        g.strokeStyle = c; g.lineWidth = 2; g.beginPath(); g.arc(bx, by, 8, 0, 6.283); g.stroke();
        g.fillStyle = c; g.font = '600 11px system-ui,sans-serif'; g.textAlign = 'left';
        g.fillText(b.r.fleet + ' robots', bx + 11, by - 8);
      }
    });
    if (!rows.length) { g.fillStyle = 'rgba(232,237,245,.5)'; g.textAlign = 'center'; g.font = '12px system-ui,sans-serif'; g.fillText(state.meta ? 'Warming up the scenarios…' : 'Run the sweep: the curves appear here as it goes', w / 2, h / 2); }
  }
  function niceStep(x) { if (!(x > 0)) return 1; var p = Math.pow(10, Math.floor(Math.log10(x))), m = x / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }

  function draw() {
    var m = state.meta || {}, run = state.run || {}, done = state.done;
    var kind = (done && done.kind) || run.kind || m.kind, backend = (done && done.backend) || run.backend || m.backend;
    var b = $('badge'); b.className = 'badge ' + (kind || ''); b.querySelector('span').textContent = backend ? 'On ' + backend : (state.rows.length ? 'Results' : 'waiting for the sweep');
    $('what').textContent = m.scenarios ? m.fleets.length + ' fleet sizes × ' + m.rates.length + ' order rates × ' + m.seeds + ' seeds · ' + m.hours + ' simulated hours each' : '';
    $('costT').textContent = 'Robot cost per order' + (m.robot_cost_h ? ' (at $' + Number(m.robot_cost_h).toFixed(2) + ' per robot-hour)' : '');
    $('bar').style.width = done ? '100%' : run.steps ? (100 * run.step / run.steps).toFixed(1) + '%' : '0';
    $('bar').parentNode.style.display = done || !m.scenarios ? 'none' : '';
    var sum = done && done.summary;
    $('sc').textContent = m.scenarios ? fmt(m.scenarios) : '–';
    $('rh').textContent = m.scenarios ? fmt(m.fleets.reduce(function (a, f) { return a + f; }, 0) * m.rates.length * m.seeds * (sum ? m.hours : (run.sim_h || 0))) : '–';
    $('wall').textContent = sum ? (sum.wall_seconds < 120 ? fmt(sum.wall_seconds, 1) + ' s' : mmss(sum.wall_seconds)) : run.elapsed_s != null ? fmt(run.elapsed_s, 0) + ' s' : '–';
    var sps = sum ? sum.robot_steps_per_s : run.robot_steps_s;
    $('speed').textContent = sps ? (sps > 1e6 ? fmt(sps / 1e6, 2) + ' M' : fmt(sps / 1e3, 0) + ' k') + ' robot-steps/s' : '–';
    var rates = Array.from(new Set(state.rows.map(function (r) { return r.order_rate; }))).sort(function (a, b) { return a - b; });
    $('legend').innerHTML = rates.map(function (r, i) { return '<span><i style="background:' + COLORS[i % COLORS.length] + '"></i>' + fmt(r) + ' orders/h ordered</span>'; }).join('') + (rates.length ? '<span class="muted">dashed: the demand · ring: cheapest fleet that keeps up</span>' : '');
    chart($('c1'), 'orders_h', { demand: true, fill: true, fmt: function (v) { return fmt(v); } });
    chart($('c2'), 'cost_per_order', { fmt: function (v) { return '$' + v.toFixed(v < 0.1 ? 3 : 2); }, cap: function (rows) { var c = rows.map(function (r) { return r.cost_per_order; }).sort(function (a, b) { return a - b; }); return c.length ? c[Math.floor(c.length * 0.85)] * 1.3 : 1; } });
    $('picks').innerHTML = rates.map(function (r, i) {
      var bb = best(r); if (!bb) return '';
      var q = bb.r;
      return '<div class="pick" style="--c:' + COLORS[i % COLORS.length] + '"><span class="muted">' + fmt(r) + ' orders per hour</span><br>' +
        (bb.ok ? '<b>' + q.fleet + ' robots</b> keep up: ' + fmt(q.orders_h) + '/h, ' + money(q.cost_per_order) + ' per order, ' + mmss(q.avg_order_s) + ' per order on average'
          : '<b>Not reached</b>: at most ' + fmt(q.orders_h) + '/h with ' + q.fleet + ' robots. The layout is the limit: more robots only wait.') + '</div>';
    }).join('');
  }
  ctx.on('update', load);
  ctx.on('resize', draw);
  load();
}
