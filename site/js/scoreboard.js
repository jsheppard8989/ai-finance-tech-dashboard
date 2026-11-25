/**
 * Paper-trade scoreboard renderer.
 * Full table:   <section id="scoreboard" data-scoreboard="full">…slots…</section>
 * Home summary: <section id="scoreboard-summary" data-scoreboard="summary">…slots…</section>
 * Reads ./data/scoreboard.json. Row tickers link to a thesis page only when research_url is set.
 */
(function () {
  var style = document.createElement('style');
  style.textContent = "#scoreboard, #scoreboard-summary {\n        margin: 1rem 0 1.25rem;\n        padding: 1rem 1.15rem;\n      }\n      .sb-header {\n        display: flex;\n        flex-wrap: wrap;\n        align-items: center;\n        justify-content: space-between;\n        gap: 0.5rem 1rem;\n        margin-bottom: 0.75rem;\n      }\n      .sb-title-row {\n        display: flex;\n        flex-wrap: wrap;\n        align-items: center;\n        gap: 0.55rem;\n      }\n      .sb-title-row h2 {\n        margin: 0;\n        font-size: 1.15rem;\n        color: #00d4ff;\n      }\n      .sb-pill {\n        display: inline-block;\n        padding: 0.18rem 0.55rem;\n        border-radius: 999px;\n        font-size: 0.68rem;\n        font-weight: 600;\n        letter-spacing: 0.03em;\n        background: rgba(0, 212, 255, 0.12);\n        color: #7dd3fc;\n        border: 1px solid rgba(0, 212, 255, 0.28);\n      }\n      .sb-pill-fallback {\n        background: rgba(251, 191, 36, 0.13);\n        color: #fcd34d;\n        border-color: rgba(251, 191, 36, 0.32);\n      }\n      .sb-pill-live {\n        background: rgba(52, 211, 153, 0.13);\n        color: #6ee7b7;\n        border-color: rgba(52, 211, 153, 0.32);\n      }\n      .sb-pill-stop {\n        background: rgba(248, 113, 113, 0.14);\n        color: #fca5a5;\n        border-color: rgba(248, 113, 113, 0.32);\n      }\n      .sb-pill-park {\n        background: rgba(148, 163, 184, 0.15);\n        color: #cbd5e1;\n        border-color: rgba(148, 163, 184, 0.3);\n      }\n      .sb-totals {\n        display: grid;\n        grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));\n        gap: 0.6rem;\n        margin-bottom: 0.9rem;\n      }\n      .sb-stat {\n        padding: 0.55rem 0.7rem;\n        border-radius: 8px;\n        background: rgba(255, 255, 255, 0.03);\n        border: 1px solid rgba(255, 255, 255, 0.08);\n      }\n      .sb-stat-label {\n        font-size: 0.68rem;\n        color: #9ca3af;\n        text-transform: uppercase;\n        letter-spacing: 0.04em;\n        margin-bottom: 0.2rem;\n      }\n      .sb-stat-val {\n        font-size: 1rem;\n        font-weight: 700;\n        color: #e6f1ff;\n      }\n      .sb-stat-sub {\n        font-size: 0.68rem;\n        color: #8892b0;\n        margin-top: 0.1rem;\n      }\n      .sb-pos { color: #34d399; }\n      .sb-neg { color: #f87171; }\n      .sb-muted { color: #9ca3af; }\n      .sb-subhead {\n        font-size: 0.85rem;\n        font-weight: 600;\n        color: #cbd5e1;\n        margin: 0.9rem 0 0.45rem;\n        display: flex;\n        align-items: center;\n        gap: 0.5rem;\n      }\n      .sb-table-wrap {\n        width: 100%;\n        overflow-x: auto;\n      }\n      .sb-table {\n        width: 100%;\n        border-collapse: collapse;\n        font-size: 0.8rem;\n      }\n      .sb-table th {\n        text-align: left;\n        font-size: 0.68rem;\n        text-transform: uppercase;\n        letter-spacing: 0.04em;\n        color: #9ca3af;\n        padding: 0.45rem 0.55rem;\n        border-bottom: 1px solid rgba(255, 255, 255, 0.12);\n        white-space: nowrap;\n      }\n      .sb-table td {\n        padding: 0.55rem 0.55rem;\n        border-bottom: 1px solid rgba(255, 255, 255, 0.06);\n        vertical-align: top;\n        color: #dbe4f3;\n      }\n      .sb-table tr:last-child td { border-bottom: none; }\n      .sb-ticker {\n        font-weight: 700;\n        font-size: 0.88rem;\n        color: #00d4ff;\n        text-decoration: none;\n      }\n      a.sb-ticker:hover { text-decoration: underline; }\n      .sb-cell-sub {\n        display: block;\n        font-size: 0.7rem;\n        color: #8892b0;\n        margin-top: 0.15rem;\n        line-height: 1.35;\n      }\n      .sb-cards { display: none; }\n      .sb-card {\n        padding: 0.7rem 0.75rem;\n        border-radius: 8px;\n        background: rgba(255, 255, 255, 0.03);\n        border: 1px solid rgba(255, 255, 255, 0.08);\n        margin-bottom: 0.55rem;\n      }\n      .sb-card-top {\n        display: flex;\n        justify-content: space-between;\n        align-items: flex-start;\n        gap: 0.5rem;\n        margin-bottom: 0.45rem;\n      }\n      .sb-card-grid {\n        display: grid;\n        grid-template-columns: repeat(2, minmax(0, 1fr));\n        gap: 0.4rem 0.75rem;\n        font-size: 0.76rem;\n      }\n      .sb-card-kv span {\n        display: block;\n        font-size: 0.64rem;\n        color: #9ca3af;\n        text-transform: uppercase;\n      }\n      .sb-card-wrong {\n        margin-top: 0.45rem;\n        padding-top: 0.4rem;\n        border-top: 1px solid rgba(255, 255, 255, 0.06);\n        font-size: 0.72rem;\n        color: #a8b2d1;\n      }\n      .sb-footnote {\n        margin-top: 0.75rem;\n        font-size: 0.7rem;\n        color: #8892b0;\n        line-height: 1.45;\n      }\n      @media (max-width: 780px) {\n        .sb-table-wrap { display: none; }\n        .sb-cards { display: block; }\n      }\n\n      #scoreboard, #scoreboard-summary {\n        margin: 1rem 0 1.25rem;\n        padding: 1rem 1.15rem;\n        background: rgba(255, 255, 255, 0.03);\n        border: 1px solid rgba(255, 255, 255, 0.1);\n        border-radius: 12px;\n      }\n      .sb-open-link {\n        display: inline-block;\n        margin-top: 0.65rem;\n        color: #00d4ff;\n        font-weight: 600;\n        text-decoration: none;\n      }\n      .sb-open-link:hover { text-decoration: underline; }\n      .sb-compact-list { list-style: none; margin: 0.35rem 0 0; padding: 0; }\n      .sb-compact-list li {\n        display: flex;\n        justify-content: space-between;\n        gap: 0.75rem;\n        padding: 0.35rem 0;\n        border-bottom: 1px solid rgba(255, 255, 255, 0.06);\n        font-size: 0.82rem;\n      }\n      .sb-compact-list li:last-child { border-bottom: none; }\n";
  document.head.appendChild(style);

  var root = document.querySelector('[data-scoreboard]') || document.getElementById('scoreboard') || document.getElementById('scoreboard-summary');
  if (!root) return;
  var mode = root.getAttribute('data-scoreboard') || (root.id === 'scoreboard-summary' ? 'summary' : 'full');
  var quoteMetaEl = document.getElementById('scoreboard-quote-meta');
  var totalsEl = document.getElementById('scoreboard-totals');
  var openWrapEl = document.getElementById('scoreboard-open-wrap');
  var closedWrapEl = document.getElementById('scoreboard-closed-wrap');
  var footEl = document.getElementById('scoreboard-footnote');

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtMoney(n, signed) {
    var num = Number(n);
    if (!isFinite(num)) return '—';
    var abs = Math.abs(num).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (num < 0) return '-$' + abs;
    if (signed && num > 0) return '+$' + abs;
    return '$' + abs;
  }

  function fmtPct(n) {
    var num = Number(n);
    if (!isFinite(num)) return '';
    return (num > 0 ? '+' : '') + num.toFixed(2) + '%';
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    var parts = String(iso).slice(0, 10).split('-');
    if (parts.length !== 3) return esc(iso);
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var y = parts[0], m = months[parseInt(parts[1], 10) - 1] || parts[1], d = parseInt(parts[2], 10);
    return y === '2026' ? (m + ' ' + d) : (m + ' ' + d + ', ' + y);
  }

  function pnlClass(n) {
    var num = Number(n);
    if (!isFinite(num) || num === 0) return 'sb-muted';
    return num > 0 ? 'sb-pos' : 'sb-neg';
  }

  function statusBadge(r) {
    var cls = 'sb-pill';
    if (r.is_cash_park) cls += ' sb-pill-park';
    else if (r.status === 'closed_stop') cls += ' sb-pill-stop';
    else if (r.status === 'open') cls += ' sb-pill-live';
    return '<span class="' + cls + '">' + esc(r.status_label || r.status || 'Open') + '</span>';
  }

  function tickerHtml(r) {
    var label = esc(r.ticker || '—');
    if (r.research_url) {
      return '<a class="sb-ticker" href="' + esc(r.research_url) + '">' + label + '</a>';
    }
    return '<span class="sb-ticker">' + label + '</span>';
  }

  function quoteBadgeHtml(r) {
    if (!r.quote_time_label && !r.quote_source) return '';
    var lbl = r.is_fallback_quote
      ? ('Saved quote · ' + (r.quote_time_label || r.quote_source))
      : (r.quote_time_label || r.quote_source);
    return '<span class="sb-cell-sub">' + esc(lbl) + '</span>';
  }

  function renderTotals(data) {
    if (!totalsEl) return;
    var t = data.totals || {};
    var uCls = pnlClass(t.unrealized_pnl);
    var rCls = pnlClass(t.realized_pnl_since_reset);
    var totCls = pnlClass(t.total_pnl_since_reset);
    var openSummary = (t.open_official_count || 0) + ' open'
      + (t.cash_park_count ? (' + ' + t.cash_park_count + ' cash park') : '');
    var closedSummary = (t.closed_since_reset_count || 0) + ' closed since Nov 15'
      + (t.historical_shown_count ? (' (+' + t.historical_shown_count + ' LRCX)') : '');
    totalsEl.innerHTML = [
      '<div class="sb-stat"><div class="sb-stat-label">Book Value</div><div class="sb-stat-val">' + fmtMoney(t.book_value) + '</div><div class="sb-stat-sub">Start: ' + fmtMoney(t.starting_cash) + '</div></div>',
      '<div class="sb-stat"><div class="sb-stat-label">Unrealized P&amp;L</div><div class="sb-stat-val ' + uCls + '">' + fmtMoney(t.unrealized_pnl, true) + '</div><div class="sb-stat-sub">Open value: ' + fmtMoney(t.open_value) + '</div></div>',
      '<div class="sb-stat"><div class="sb-stat-label">Total Since Nov 15</div><div class="sb-stat-val ' + totCls + '">' + fmtMoney(t.total_pnl_since_reset, true) + ' (' + fmtPct(t.total_return_pct) + ')</div><div class="sb-stat-sub ' + rCls + '">Realized: ' + fmtMoney(t.realized_pnl_since_reset, true) + '</div></div>',
      '<div class="sb-stat"><div class="sb-stat-label">Cash &amp; Trades</div><div class="sb-stat-val">' + fmtMoney(t.cash) + '</div><div class="sb-stat-sub">' + esc(openSummary + ' · ' + closedSummary) + '</div></div>'
    ].join('');
  }

  function renderOpen(rows) {
    if (!openWrapEl) return;
    if (!rows || !rows.length) {
      openWrapEl.innerHTML = '<div class="sb-subhead">Open Positions</div><p class="sb-muted" style="font-size:0.8rem;">No open paper positions.</p>';
      return;
    }
    var thead = '<thead><tr><th>Trade</th><th>Entry</th><th>Strike &amp; Expiry</th><th>Max Loss</th><th>Today&#39;s Mark</th><th>Unrealized P&amp;L</th><th>Wrong If</th></tr></thead>';
    var trs = rows.map(function (r) {
      var markTxt = r.current_mark != null ? ('$' + Number(r.current_mark).toFixed(2)) : '—';
      var expTxt = r.expiry ? fmtDate(r.expiry) : 'Cash park';
      var maxSub = r.breakeven != null ? ('BE $' + Number(r.breakeven).toFixed(2)) : '';
      return '<tr>'
        + '<td>' + tickerHtml(r) + ' ' + statusBadge(r) + '<span class="sb-cell-sub">' + esc(r.structure) + (r.owner && !r.is_cash_park ? ' · ' + esc(r.owner) : '') + '</span></td>'
        + '<td>' + esc(fmtDate(r.opened)) + '<span class="sb-cell-sub">' + esc(r.entry_detail || fmtMoney(r.cost)) + '</span></td>'
        + '<td>' + esc(r.strike || '—') + '<span class="sb-cell-sub">Exp: ' + esc(expTxt) + '</span></td>'
        + '<td>' + fmtMoney(r.max_loss) + (maxSub ? '<span class="sb-cell-sub">' + esc(maxSub) + '</span>' : '') + '</td>'
        + '<td>' + esc(markTxt) + '<span class="sb-cell-sub">Val ' + fmtMoney(r.current_value) + '</span>' + quoteBadgeHtml(r) + '</td>'
        + '<td class="' + pnlClass(r.unrealized_pnl) + '" style="font-weight:600;">' + fmtMoney(r.unrealized_pnl, true) + '<span class="sb-cell-sub">' + esc(fmtPct(r.return_pct)) + '</span></td>'
        + '<td style="max-width:240px;">' + esc(r.wrong_if || '—') + '</td>'
        + '</tr>';
    }).join('');

    var cards = rows.map(function (r) {
      var markTxt = r.current_mark != null ? ('$' + Number(r.current_mark).toFixed(2)) : '—';
      var expTxt = r.expiry ? fmtDate(r.expiry) : 'Cash park';
      return '<div class="sb-card">'
        + '<div class="sb-card-top"><div>' + tickerHtml(r) + ' ' + statusBadge(r) + '<span class="sb-cell-sub">' + esc(r.structure) + '</span></div>'
        + '<div class="' + pnlClass(r.unrealized_pnl) + '" style="text-align:right;font-weight:700;">' + fmtMoney(r.unrealized_pnl, true) + '<span class="sb-cell-sub">' + esc(fmtPct(r.return_pct)) + '</span></div></div>'
        + '<div class="sb-card-grid">'
        + '<div class="sb-card-kv"><span>Entry</span>' + esc(r.entry_detail || fmtMoney(r.cost)) + '</div>'
        + '<div class="sb-card-kv"><span>Strike &amp; Expiry</span>' + esc(r.strike || '—') + ' · ' + esc(expTxt) + '</div>'
        + '<div class="sb-card-kv"><span>Today&#39;s Mark</span>' + esc(markTxt) + ' (Val ' + fmtMoney(r.current_value) + ')' + quoteBadgeHtml(r) + '</div>'
        + '<div class="sb-card-kv"><span>Max Loss</span>' + fmtMoney(r.max_loss) + '</div>'
        + '</div>'
        + '<div class="sb-card-wrong"><strong>Wrong if:</strong> ' + esc(r.wrong_if || '—') + '</div>'
        + '</div>';
    }).join('');

    openWrapEl.innerHTML = '<div class="sb-subhead">Open Positions (' + rows.length + ')</div>'
      + '<div class="sb-table-wrap"><table class="sb-table">' + thead + '<tbody>' + trs + '</tbody></table></div>'
      + '<div class="sb-cards">' + cards + '</div>';
  }

  function renderClosed(rows) {
    if (!closedWrapEl) return;
    if (!rows || !rows.length) {
      closedWrapEl.innerHTML = '<div class="sb-subhead">Closed Trades</div><p class="sb-muted" style="font-size:0.8rem;">No closed trades yet since the Nov 15 reset.</p>';
      return;
    }
    var thead = '<thead><tr><th>Trade</th><th>Entry</th><th>Strike &amp; Expiry</th><th>Max Loss</th><th>Exit</th><th>Realized P&amp;L</th><th>Wrong If</th></tr></thead>';
    var trs = rows.map(function (r) {
      var preTag = r.pre_reset ? ' <span class="sb-pill sb-pill-park">Pre-reset</span>' : '';
      var expTxt = r.expiry ? fmtDate(r.expiry) : '—';
      if (r.expiry_note) expTxt += ' (' + r.expiry_note + ')';
      return '<tr>'
        + '<td>' + tickerHtml(r) + ' ' + statusBadge(r) + preTag + '<span class="sb-cell-sub">' + esc(r.structure) + '</span></td>'
        + '<td>' + esc(fmtDate(r.opened)) + '<span class="sb-cell-sub">' + esc(r.entry_detail || fmtMoney(r.cost)) + '</span></td>'
        + '<td>' + esc(r.strike || '—') + '<span class="sb-cell-sub">Exp: ' + esc(expTxt) + '</span></td>'
        + '<td>' + fmtMoney(r.max_loss) + '</td>'
        + '<td>' + esc(fmtDate(r.closed)) + '<span class="sb-cell-sub">' + esc(r.exit_detail || fmtMoney(r.exit_value)) + '</span></td>'
        + '<td class="' + pnlClass(r.realized_pnl) + '" style="font-weight:600;">' + fmtMoney(r.realized_pnl, true) + '<span class="sb-cell-sub">' + esc(fmtPct(r.return_pct)) + '</span></td>'
        + '<td style="max-width:240px;">' + esc(r.wrong_if || '—') + '</td>'
        + '</tr>';
    }).join('');

    var cards = rows.map(function (r) {
      var preTag = r.pre_reset ? ' <span class="sb-pill sb-pill-park">Pre-reset</span>' : '';
      var expTxt = r.expiry ? fmtDate(r.expiry) : '—';
      return '<div class="sb-card">'
        + '<div class="sb-card-top"><div>' + tickerHtml(r) + ' ' + statusBadge(r) + preTag + '<span class="sb-cell-sub">' + esc(r.structure) + '</span></div>'
        + '<div class="' + pnlClass(r.realized_pnl) + '" style="text-align:right;font-weight:700;">' + fmtMoney(r.realized_pnl, true) + '<span class="sb-cell-sub">' + esc(fmtPct(r.return_pct)) + '</span></div></div>'
        + '<div class="sb-card-grid">'
        + '<div class="sb-card-kv"><span>Entry</span>' + esc(r.entry_detail || fmtMoney(r.cost)) + '</div>'
        + '<div class="sb-card-kv"><span>Strike &amp; Expiry</span>' + esc(r.strike || '—') + ' · ' + esc(expTxt) + '</div>'
        + '<div class="sb-card-kv"><span>Exit</span>' + esc(r.exit_detail || fmtMoney(r.exit_value)) + '</div>'
        + '<div class="sb-card-kv"><span>Max Loss</span>' + fmtMoney(r.max_loss) + '</div>'
        + '</div>'
        + '<div class="sb-card-wrong"><strong>Wrong if:</strong> ' + esc(r.wrong_if || '—') + '</div>'
        + '</div>';
    }).join('');

    closedWrapEl.innerHTML = '<div class="sb-subhead">Closed Trades (since Nov 15 reset + LRCX)</div>'
      + '<div class="sb-table-wrap"><table class="sb-table">' + thead + '<tbody>' + trs + '</tbody></table></div>'
      + '<div class="sb-cards">' + cards + '</div>';
  }

  function renderSummary(data) {
    var t = data.totals || {};
    var rows = data.open || [];
    var items = rows.map(function (r) {
      var name = r.research_url
        ? ('<a class="sb-ticker" href="' + esc(r.research_url) + '">' + esc(r.ticker) + '</a>')
        : ('<span class="sb-ticker">' + esc(r.ticker) + '</span>');
      return '<li><span>' + name + ' ' + statusBadge(r) + '<span class="sb-cell-sub">' + esc(r.structure || '') + '</span></span>'
        + '<span class="' + pnlClass(r.unrealized_pnl) + '" style="font-weight:600;white-space:nowrap;">' + fmtMoney(r.unrealized_pnl, true) + '</span></li>';
    }).join('');
    if (openWrapEl) {
      openWrapEl.innerHTML = (items
        ? ('<div class="sb-subhead">Open now</div><ul class="sb-compact-list">' + items + '</ul>')
        : '<p class="sb-muted" style="font-size:0.8rem;">No open paper positions.</p>')
        + '<a class="sb-open-link" href="trades.html">Open the full scoreboard</a>';
    }
    if (closedWrapEl) closedWrapEl.innerHTML = '';
    if (footEl) {
      footEl.textContent = 'Marks as of ' + (data.quote_time_label || data.generated_at_label || '') + '. Paper only.';
    }
  }

  function setQuoteMeta(data) {
    if (!quoteMetaEl) return;
    quoteMetaEl.className = 'sb-pill ' + (data.is_fallback_quote ? 'sb-pill-fallback' : 'sb-pill-live');
    quoteMetaEl.textContent = data.is_fallback_quote
      ? ('Saved quote fallback · ' + (data.quote_time_label || data.quote_source || ''))
      : (data.quote_source || ('Robinhood quotes · ' + (data.quote_time_label || '')));
  }

  fetch('./data/scoreboard.json?v=' + Date.now(), { cache: 'no-store' })
    .then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    })
    .then(function (data) {
      setQuoteMeta(data);
      renderTotals(data);
      if (mode === 'summary') {
        renderSummary(data);
        return;
      }
      renderOpen(data.open || []);
      renderClosed(data.closed || []);
      if (footEl) {
        var t = data.totals || {};
        var priorTxt = t.prior_book_realized_pnl != null
          ? (' Prior pre-Nov 15 book: ' + fmtMoney(t.prior_book_realized_pnl, true) + ' realized (' + (t.prior_book_closed_wins || 0) + 'W/' + (t.prior_book_closed_losses || 0) + 'L on ' + fmtMoney(t.prior_book_starting_capital) + ').')
          : '';
        footEl.textContent = (data.fill_rule || '') + ' Updated ' + (data.generated_at_label || '') + '.' + priorTxt;
      }
    })
    .catch(function () {
      if (quoteMetaEl) quoteMetaEl.textContent = 'Scoreboard unavailable';
      if (totalsEl) totalsEl.innerHTML = '<div class="sb-muted" style="font-size:0.8rem;">Could not load live scoreboard data.</div>';
    });
})();
