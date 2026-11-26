/**
 * Paper-trade record renderer (site/data/scoreboard.json, schema 2).
 *   Full page (trades.html): <section id="scoreboard" data-scoreboard="full">
 *   Home summary (index.html): <section id="scoreboard-summary" data-scoreboard="summary">
 * Every number comes from the JSON, which the box build ties to the paper book.
 * Marks turn red once they are older than 1 trading day (stale_after_ct).
 */
(function () {
  // Kit tag ids by name. Set trades to the numeric id of the Kit "trades" tag once it exists
  // on form 10236979; until then the forms subscribe without a tag.
  var KIT_TAG_IDS = { trades: null };

  var CSS = [
    '.sb{--sb-pos:#34d399;--sb-neg:#f87171;--sb-mut:#9aa7b6;--sb-line:rgba(255,255,255,.09);--sb-acc:#00d4ff}',
    '.sb .sb-h{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.4rem 1rem;margin:0 0 .75rem}',
    '.sb .sb-h h2{margin:0;font-size:1.15rem;color:var(--sb-acc)}',
    '.sb .sb-pill{display:inline-block;padding:.15rem .55rem;border-radius:999px;font-size:.68rem;font-weight:600;letter-spacing:.03em;background:rgba(0,212,255,.1);color:#7dd3fc;border:1px solid rgba(0,212,255,.28)}',
    '.sb .sb-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;margin:0 0 .6rem}',
    '.sb .sb-stat{padding:.6rem .75rem;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid var(--sb-line)}',
    '.sb .sb-stat-l{font-size:.68rem;color:var(--sb-mut);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .15rem}',
    '.sb .sb-stat-v{font-size:1.15rem;font-weight:700;color:#e6f1ff;font-variant-numeric:tabular-nums}',
    '.sb .sb-stat-s{font-size:.72rem;color:var(--sb-mut);margin-top:.1rem}',
    '.sb .sb-pos{color:var(--sb-pos)}.sb .sb-neg{color:var(--sb-neg)}.sb .sb-mut{color:var(--sb-mut)}',
    '.sb .sb-asof{font-size:.8rem;color:var(--sb-mut);margin:.15rem 0 .2rem}',
    '.sb .sb-asof b{color:#cbd5e1;font-weight:600}',
    '.sb .sb-stale,.sb .sb-stale b{color:var(--sb-neg)!important}',
    '.sb .sb-stale-note{font-weight:600}',
    '.sb .sb-sub{font-size:.95rem;font-weight:700;color:#cbd5e1;margin:1.3rem 0 .5rem}',
    '.sb .sb-park{margin:.9rem 0 0;padding:.65rem .8rem;border-radius:10px;border:1px dashed rgba(148,163,184,.35);background:rgba(148,163,184,.06);font-size:.84rem;line-height:1.5}',
    '.sb .sb-park-t{font-weight:700;color:#e2e8f0}',
    '.sb .sb-park-r{font-size:.74rem;color:var(--sb-mut);margin-top:.25rem}',
    '.sb .sb-bookline{font-size:.8rem;color:var(--sb-mut);margin:.5rem 0 0}',
    '.sb table.sb-t{width:100%;border-collapse:collapse;font-size:.8rem;font-variant-numeric:tabular-nums}',
    '.sb .sb-t th{text-align:left;font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;color:var(--sb-mut);padding:.45rem .5rem;border-bottom:1px solid rgba(255,255,255,.14);white-space:nowrap;vertical-align:bottom}',
    '.sb .sb-t td{padding:.55rem .5rem;border-bottom:1px solid var(--sb-line);vertical-align:top;color:#dbe4f3}',
    '.sb .sb-t td.n,.sb .sb-t th.n{text-align:right;white-space:nowrap}',
    '.sb .sb-t td.sb-first{min-width:190px}',
    '.sb .sb-tk{font-weight:700;font-size:.9rem;color:var(--sb-acc)}',
    '.sb .sb-own{font-size:.7rem;color:var(--sb-mut);margin-left:.3rem}',
    '.sb .sb-st{font-size:.74rem;color:#cbd5e1;margin-top:.1rem}',
    '.sb .sb-sm{font-size:.72rem;color:var(--sb-mut);margin-top:.1rem}',
    '.sb .sb-tog{margin-top:.35rem;background:none;border:1px solid rgba(0,212,255,.35);color:#7dd3fc;border-radius:6px;font:inherit;font-size:.7rem;padding:.15rem .5rem;cursor:pointer}',
    '.sb .sb-tog:hover{background:rgba(0,212,255,.1)}',
    '.sb .sb-tog:focus-visible{outline:2px solid var(--sb-acc);outline-offset:2px}',
    '.sb tr.sb-audit td{background:rgba(0,212,255,.04);padding:.6rem .75rem .8rem}',
    '.sb .sb-aud{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.6rem 1.2rem;font-size:.74rem;line-height:1.45}',
    '.sb .sb-aud h4{margin:0 0 .25rem;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#7dd3fc}',
    '.sb .sb-aud table{border-collapse:collapse;width:100%}',
    '.sb .sb-aud td,.sb .sb-aud th{padding:.15rem .35rem .15rem 0;border:0;font-size:.72rem;text-align:left;color:#cbd5e1;font-weight:400;text-transform:none;letter-spacing:0;white-space:normal}',
    '.sb .sb-aud th{color:var(--sb-mut)}',
    '.sb .sb-aud .sb-math{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.7rem;color:#e2e8f0;overflow-wrap:anywhere}',
    '.sb .sb-chart{margin:.4rem 0 0}',
    '.sb .sb-chart svg{width:100%;height:auto;display:block}',
    '.sb .sb-legend{display:flex;flex-wrap:wrap;gap:.4rem 1rem;font-size:.75rem;color:#cbd5e1;margin:.35rem 0 0}',
    '.sb .sb-legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:.35rem;vertical-align:middle}',
    '.sb .sb-note{font-size:.72rem;color:var(--sb-mut);margin:.35rem 0 0;line-height:1.45}',
    '.sb .sb-more{display:inline-block;margin-top:.7rem;font-size:.85rem;font-weight:600;color:var(--sb-acc);text-decoration:none}',
    '.sb .sb-more:hover{text-decoration:underline}',
    '.sb .sb-mini{list-style:none;margin:.4rem 0 0;padding:0}',
    '.sb .sb-mini li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.2rem .8rem;padding:.45rem 0;border-top:1px solid var(--sb-line);font-size:.82rem}',
    '@media(max-width:900px){.sb .sb-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}',
    '@media(max-width:760px){',
    '.sb table.sb-t,.sb .sb-t>tbody,.sb .sb-t>tbody>tr,.sb .sb-t>tbody>tr>td{display:block;width:100%}',
    '.sb .sb-t>thead{display:none}',
    '.sb .sb-t>tbody>tr.sb-row{margin:0 0 .6rem;padding:.55rem .7rem;border:1px solid var(--sb-line);border-radius:10px;background:rgba(255,255,255,.025)}',
    '.sb .sb-t>tbody>tr.sb-audit{margin:-.5rem 0 .7rem;border:1px solid var(--sb-line);border-top:0;border-radius:0 0 10px 10px}',
    '.sb .sb-t>tbody>tr.sb-audit[hidden]{display:none}',
    '.sb .sb-t>tbody>tr>td{border:0;padding:.18rem 0;display:flex;justify-content:space-between;gap:.75rem}',
    '.sb .sb-t>tbody>tr>td.n{text-align:right}',
    '.sb .sb-t>tbody>tr>td[data-l]::before{content:attr(data-l);color:var(--sb-mut);font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;flex:0 0 auto;text-align:left}',
    '.sb .sb-t>tbody>tr>td.sb-first{display:block;padding-bottom:.35rem}',
    '.sb .sb-t>tbody>tr>td.sb-wide{display:block}',
    '.sb .sb-t>tbody>tr>td.sb-wide::before{display:block;margin-bottom:.1rem}',
    '.sb .sb-t>tbody>tr.sb-audit>td{display:block;padding:.55rem .6rem .7rem}',
    '.sb .sb-t td>span.sb-v{text-align:right}',
    '.sb .sb-aud{grid-template-columns:1fr}',
    '}'
  ].join('');

  var root = document.querySelector('[data-scoreboard]');
  if (!root) return;
  var mode = root.getAttribute('data-scoreboard') || 'full';
  var style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);
  root.classList.add('sb');

  // Kit tag on any trade-alert form on the page.
  Array.prototype.forEach.call(document.querySelectorAll('form[data-kit-tag]'), function (f) {
    var id = KIT_TAG_IDS[f.getAttribute('data-kit-tag')];
    if (!id) return;
    var inp = document.createElement('input');
    inp.type = 'hidden'; inp.name = 'tags[]'; inp.value = String(id);
    f.appendChild(inp);
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(x, d) {
    return Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function money(x) { return (x < 0 ? '\u2212$' : '$') + num(Math.abs(x), 2); }
  function smoney(x) { return (x > 0 ? '+$' : x < 0 ? '\u2212$' : '$') + num(Math.abs(x), 2); }
  function spct(x, d) {
    if (x == null) return '\u2014';
    d = d == null ? 1 : d;
    return (x > 0 ? '+' : x < 0 ? '\u2212' : '') + num(Math.abs(x), d) + '%';
  }
  function cls(x) { return x > 0 ? 'sb-pos' : x < 0 ? 'sb-neg' : 'sb-mut'; }
  function isStale(staleAfter, fallback) {
    if (!staleAfter) return !!fallback;
    var t = Date.parse(staleAfter);
    return isNaN(t) ? !!fallback : Date.now() > t;
  }
  function asOf(label, staleAfter, fallback) {
    var stale = isStale(staleAfter, fallback);
    return '<span class="' + (stale ? 'sb-stale' : '') + '">Mark as of <b>' + esc(label) + '</b>' +
      (stale ? ' <span class="sb-stale-note">\u00b7 older than 1 trading day</span>' : '') + '</span>';
  }
  function writeup(r) {
    return r.writeup_url
      ? '<a href="' + esc(r.writeup_url) + '">Read</a>'
      : '<span class="sb-mut">No write-up yet</span>';
  }

  function legTable(legs) {
    if (!legs || !legs.length) return '';
    return '<table><thead><tr><th>Leg</th><th>Side</th><th>Bid</th><th>Ask</th><th>Fill</th></tr></thead><tbody>' +
      legs.map(function (l) {
        return '<tr><td>' + esc(l.leg) + (l.quote_label ? '<div class="sb-mut">' + esc(l.quote_label) + '</div>' : '') +
          '</td><td>' + esc(l.side) + '</td><td>' + num(l.bid, 2) + '</td><td>' + num(l.ask, 2) +
          '</td><td class="sb-math">' + esc(l.math) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function auditHtml(a, closed) {
    var e = a.entry || {}, x = closed ? (a.exit || {}) : (a.mark || {});
    return '<div class="sb-aud">' +
      '<div><h4>Entry \u00b7 ' + esc(e.at_label || '') + '</h4>' + legTable(e.legs) +
        '<div class="sb-math">' + esc(e.math || '') + '</div>' +
        (e.source ? '<div class="sb-mut">Source: ' + esc(e.source) + '</div>' : '') + '</div>' +
      '<div><h4>' + (closed ? 'Exit \u00b7 ' + esc(x.at_label || '') : 'Mark (closing side)') + '</h4>' + legTable(x.legs) +
        '<div class="sb-math">' + esc(x.math || '') + '</div>' +
        (x.pnl_math ? '<div class="sb-math">' + esc(x.pnl_math) + '</div>' : '') +
        (x.source ? '<div class="sb-mut">Source: ' + esc(x.source) + '</div>' : '') + '</div>' +
      '</div>';
  }
  function toggleBtn(id) {
    return '<button type="button" class="sb-tog" aria-expanded="false" aria-controls="aud-' + esc(id) + '">Show the math</button>';
  }
  function wireToggles(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll('.sb-tog'), function (b) {
      b.addEventListener('click', function () {
        var row = document.getElementById(b.getAttribute('aria-controls'));
        var open = b.getAttribute('aria-expanded') === 'true';
        b.setAttribute('aria-expanded', open ? 'false' : 'true');
        b.textContent = open ? 'Show the math' : 'Hide the math';
        if (row) row.hidden = open;
      });
    });
  }

  function stats(d) {
    var r = d.record, since = r.first_opened ? new Date(r.first_opened + 'T12:00:00') : null;
    var sinceLbl = since ? since.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
    return '<div class="sb-stats">' +
      '<div class="sb-stat"><div class="sb-stat-l">Closed trades</div><div class="sb-stat-v">' + r.wins + ' won \u00b7 ' + r.losses + ' lost</div>' +
        '<div class="sb-stat-s">' + r.closed_count + ' trades, ' + num(r.win_rate_pct, 1) + '% won</div></div>' +
      '<div class="sb-stat"><div class="sb-stat-l">Realized P&amp;L</div><div class="sb-stat-v ' + cls(r.realized_pnl) + '">' + smoney(r.realized_pnl) + '</div>' +
        '<div class="sb-stat-s">All closed trades since ' + esc(sinceLbl) + '</div></div>' +
      '<div class="sb-stat"><div class="sb-stat-l">Average closed trade</div><div class="sb-stat-v ' + cls(r.avg_pnl_pct_max_loss) + '">' + spct(r.avg_pnl_pct_max_loss) + '</div>' +
        '<div class="sb-stat-s">of max loss, per trade</div></div>' +
      '<div class="sb-stat"><div class="sb-stat-l">Open trades</div><div class="sb-stat-v">' + r.open_count + ' \u00b7 <span class="' + cls(r.open_pnl) + '">' + smoney(r.open_pnl) + '</span></div>' +
        '<div class="sb-stat-s">' + spct(r.open_pnl_pct_max_loss) + ' of ' + money(r.open_max_loss) + ' max loss</div></div>' +
      '</div>' +
      '<p class="sb-asof">Open trades: ' + asOf(r.open_mark_label, r.open_stale_after_ct, r.open_is_stale) + '</p>';
  }

  function parkHtml(d) {
    var p = d.cash_park, b = d.book;
    if (!p) return '';
    return '<div class="sb-park"><div><span class="sb-park-t">Cash park, not a trade: ' + esc(p.ticker) + '</span> \u00b7 ' +
      esc(p.entry_text) + ' (' + money(p.cost) + ') \u00b7 mark ' + esc(p.mark_text) + ' = ' + money(p.value) + ' \u00b7 <span class="' + cls(p.pnl) + '">' +
      smoney(p.pnl) + ' (' + spct(p.pnl_pct_max_loss, 2) + ' of cost)</span></div>' +
      '<div class="sb-asof">' + asOf(p.mark_label, p.stale_after_ct, p.is_stale) + '</div>' +
      '<div class="sb-park-r">' + esc(p.park_rule || '') + ' It is left out of the trade record above.</div></div>' +
      '<p class="sb-bookline">$100,000 paper book since the Nov 15 reset: <b>' + money(b.book_value) + '</b> (' +
      '<span class="' + cls(b.total_pnl) + '">' + smoney(b.total_pnl) + ', ' + spct(b.total_return_pct, 2) + '</span>) = ' +
      'open trades ' + smoney(b.trades_pnl) + ', cash park ' + smoney(b.park_pnl) + ', cash ' + money(b.cash) + '.</p>';
  }

  function openTable(rows) {
    if (!rows.length) return '<p class="sb-mut">No open trades.</p>';
    return '<table class="sb-t"><thead><tr><th>Trade</th><th>Opened</th><th class="n">Entry</th><th class="n">Max loss</th>' +
      '<th class="n">Mark</th><th class="n">P&amp;L</th><th class="n">% of max loss</th><th>Wrong if</th><th>Write-up</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr class="sb-row">' +
          '<td class="sb-first"><span class="sb-tk">' + esc(r.ticker) + '</span>' + (r.owner ? '<span class="sb-own">' + esc(r.owner) + '</span>' : '') +
            '<div class="sb-st">' + esc(r.structure) + '</div>' + toggleBtn(r.id) + '</td>' +
          '<td data-l="Opened"><span class="sb-v">' + esc(r.opened_label) + '</span></td>' +
          '<td class="n" data-l="Entry"><span class="sb-v">' + esc(r.entry_text) + '</span></td>' +
          '<td class="n" data-l="Max loss"><span class="sb-v">' + money(r.max_loss) + '</span></td>' +
          '<td class="n" data-l="Mark"><span class="sb-v">' + esc(r.mark_text) + ' = ' + money(r.value) +
            '<div class="sb-sm">' + asOf(r.mark_label, r.stale_after_ct, r.is_stale) + '</div></span></td>' +
          '<td class="n ' + cls(r.pnl) + '" data-l="P&amp;L"><span class="sb-v">' + smoney(r.pnl) + '</span></td>' +
          '<td class="n ' + cls(r.pnl) + '" data-l="% of max loss"><span class="sb-v">' + spct(r.pnl_pct_max_loss, 2) + '</span></td>' +
          '<td class="sb-wide" data-l="Wrong if">' + esc(r.wrong_if || '\u2014') + '</td>' +
          '<td data-l="Write-up"><span class="sb-v">' + writeup(r) + '</span></td>' +
          '</tr><tr class="sb-audit" id="aud-' + esc(r.id) + '" hidden><td colspan="9">' + auditHtml(r.audit, false) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function closedTable(rows) {
    if (!rows.length) return '<p class="sb-mut">No closed trades.</p>';
    return '<table class="sb-t"><thead><tr><th>Trade</th><th>Opened</th><th>Closed</th><th class="n">Max loss</th>' +
      '<th class="n">Exit value</th><th class="n">P&amp;L</th><th class="n">% of max loss</th><th>How it closed</th><th>Write-up</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr class="sb-row">' +
          '<td class="sb-first"><span class="sb-tk">' + esc(r.ticker) + '</span>' + (r.owner ? '<span class="sb-own">' + esc(r.owner) + '</span>' : '') +
            '<div class="sb-st">' + esc(r.structure) + '</div>' + toggleBtn(r.id) + '</td>' +
          '<td data-l="Opened"><span class="sb-v">' + esc(r.opened_label) + '</span></td>' +
          '<td data-l="Closed"><span class="sb-v">' + esc(r.closed_label) + '</span></td>' +
          '<td class="n" data-l="Max loss"><span class="sb-v">' + money(r.max_loss) + '</span></td>' +
          '<td class="n" data-l="Exit value"><span class="sb-v">' + money(r.exit_value) + '</span></td>' +
          '<td class="n ' + cls(r.pnl) + '" data-l="P&amp;L"><span class="sb-v">' + smoney(r.pnl) + '</span></td>' +
          '<td class="n ' + cls(r.pnl) + '" data-l="% of max loss"><span class="sb-v">' + spct(r.pnl_pct_max_loss, 2) + '</span></td>' +
          '<td class="sb-wide" data-l="How it closed">' + esc(r.status_label) + '<div class="sb-sm">' + esc(r.how_closed) +
            (r.owner_stated ? ' (owner-stated fill)' : '') + '</div></td>' +
          '<td data-l="Write-up"><span class="sb-v">' + writeup(r) + '</span></td>' +
          '</tr><tr class="sb-audit" id="aud-' + esc(r.id) + '" hidden><td colspan="9">' + auditHtml(r.audit, true) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function chart(c) {
    var pts = (c && c.points) || [];
    if (pts.length < 2) return '<p class="sb-mut">Not enough marks yet for a chart.</p>';
    var W = 640, H = 230, L = 58, R = 12, T = 12, B = 30;
    var vals = [];
    pts.forEach(function (p) { vals.push(p.book_value); if (p.spy_value != null) vals.push(p.spy_value); });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi - lo) * 0.12 || 500;
    lo -= pad; hi += pad;
    function x(i) { return L + (W - L - R) * (i / (pts.length - 1)); }
    function y(v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); }
    function line(key, color) {
      var d = '';
      pts.forEach(function (p, i) { if (p[key] != null) d += (d ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p[key]).toFixed(1); });
      var dots = pts.map(function (p, i) {
        return p[key] == null ? '' : '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(p[key]).toFixed(1) + '" r="3" fill="' + color + '"><title>' +
          esc(p.label + ': ' + money(p[key]) + (key === 'book_value' ? ' (' + (p.read_label || '') + ')' : ' (SPY ' + (p.spy_close || '') + ')')) + '</title></circle>';
      }).join('');
      return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.2"/>' + dots;
    }
    var ticks = '', k;
    for (k = 0; k <= 3; k++) {
      var v = lo + (hi - lo) * k / 3;
      ticks += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" stroke="rgba(255,255,255,.08)"/>' +
        '<text x="' + (L - 6) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="#9aa7b6">$' + num(v / 1000, 1) + 'k</text>';
    }
    var base = '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(100000).toFixed(1) + '" y2="' + y(100000).toFixed(1) + '" stroke="rgba(255,255,255,.25)" stroke-dasharray="4 4"/>';
    var xl = pts.map(function (p, i) {
      return '<text x="' + x(i).toFixed(1) + '" y="' + (H - 9) + '" text-anchor="middle" font-size="10.5" fill="#9aa7b6">' + esc(p.label.replace(' reset', '')) + '</text>';
    }).join('');
    var last = pts[pts.length - 1];
    return '<div class="sb-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Paper book value versus SPY since the Nov 15 reset">' +
      ticks + base + line('spy_value', '#94a3b8') + line('book_value', '#00d4ff') + xl + '</svg></div>' +
      '<div class="sb-legend"><span><i style="background:#00d4ff"></i>Paper book ' + money(last.book_value) + '</span>' +
      '<span><i style="background:#94a3b8"></i>$100,000 in SPY ' + (last.spy_value != null ? money(last.spy_value) : '') + '</span>' +
      '<span class="sb-mut">Last point ' + esc(last.label) + '</span></div>' +
      '<p class="sb-note">' + esc(c.note || '') + (c.gaps && c.gaps.length ? ' Gaps: ' + esc(c.gaps.join('; ')) + '.' : '') + '</p>';
  }

  function renderFull(d) {
    var head = root.querySelector('[data-sb="headline"]');
    var park = root.querySelector('[data-sb="park"]');
    var open = root.querySelector('[data-sb="open"]');
    var closed = root.querySelector('[data-sb="closed"]');
    var curve = document.querySelector('[data-sb="curve"]');
    if (head) head.innerHTML = stats(d);
    if (park) park.innerHTML = parkHtml(d);
    if (open) { open.innerHTML = openTable(d.open || []); wireToggles(open); }
    if (closed) { closed.innerHTML = closedTable(d.closed || []); wireToggles(closed); }
    if (curve) curve.innerHTML = chart(d.equity_curve);
    var gen = root.querySelector('[data-sb="generated"]');
    if (gen) gen.textContent = 'Built ' + (d.generated_at_label || '') + ' from the paper book and read-only Robinhood quotes.';
  }

  function renderSummary(d) {
    var r = d.record, p = d.cash_park;
    var box = root.querySelector('[data-sb="summary"]');
    if (!box) return;
    box.innerHTML = stats(d) +
      '<ul class="sb-mini">' + (d.open || []).map(function (o) {
        return '<li><span><span class="sb-tk">' + esc(o.ticker) + '</span> <span class="sb-mut">' + esc(o.structure) + '</span></span>' +
          '<span class="' + cls(o.pnl) + '">' + smoney(o.pnl) + ' (' + spct(o.pnl_pct_max_loss, 1) + ' of max loss)</span></li>';
      }).join('') +
      (p ? '<li><span class="sb-mut">Cash park, not a trade: ' + esc(p.ticker) + '</span><span class="' + cls(p.pnl) + '">' + smoney(p.pnl) + '</span></li>' : '') +
      '</ul><a class="sb-more" href="trades.html">See all ' + (r.closed_count + r.open_count) + ' trades, with the math</a>';
  }

  fetch('./data/scoreboard.json?v=' + Date.now(), { cache: 'no-store' })
    .then(function (resp) { if (!resp.ok) throw new Error('HTTP ' + resp.status); return resp.json(); })
    .then(function (d) { if (mode === 'summary') renderSummary(d); else renderFull(d); })
    .catch(function () {
      var slot = root.querySelector('[data-sb="headline"]') || root.querySelector('[data-sb="summary"]');
      if (slot) slot.innerHTML = '<p class="sb-mut">The trade record could not be loaded.</p>';
    });
})();
