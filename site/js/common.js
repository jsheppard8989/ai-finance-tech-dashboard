/**
 * Shared site utilities: Deep Dive HTML + calendar-safe date formatting
 * (index, archive, pipeline-health).
 */
function formatSiteCalendarDate(isoOrStr, opts) {
  opts = opts || { month: 'short', day: 'numeric', year: 'numeric' };
  if (isoOrStr == null || isoOrStr === '') return '—';
  var s = String(isoOrStr).trim();
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:$|[^0-9])/);
  if (m) {
    var y = parseInt(m[1], 10);
    var mo = parseInt(m[2], 10) - 1;
    var d = parseInt(m[3], 10);
    return new Date(y, mo, d).toLocaleDateString('en-US', opts);
  }
  var dt = new Date(s);
  if (isNaN(dt.getTime())) return s;
  return dt.toLocaleDateString('en-US', opts);
}

function parseSiteDateForSort(isoOrStr) {
  if (isoOrStr == null || isoOrStr === '') return 0;
  var s = String(isoOrStr).trim();
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:$|[^0-9])/);
  if (m) {
    return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10)).getTime();
  }
  var dt = new Date(s);
  return isNaN(dt.getTime()) ? 0 : dt.getTime();
}

function escapeDeepDiveText(s) {
  if (s == null || s === '') return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function isDeepDiveV2(dd) {
  if (!dd) return false;
  if (Number(dd.schema_version) >= 2) return true;
  var kt = dd.key_takeaways_detailed;
  return !(Array.isArray(kt) && kt.length > 0);
}

function renderDeepDiveQuotes(ev) {
  return (
    '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(15,52,96,0.45); border: 1px solid rgba(0,212,255,0.25); border-radius: 8px;">' +
    '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">🎙️ From the source</h4>' +
    '<div style="color: #e8e8e8; line-height: 1.75; font-size: 0.92rem; white-space: pre-wrap;">' +
    escapeDeepDiveText(ev) + '</div></div>'
  );
}

function renderDeepDiveFalsifiers(fals) {
  if (!Array.isArray(fals) || fals.length === 0) return '';
  var falsHtml = fals.map(function(line) {
    return '<li style="margin-bottom: 0.5rem; line-height: 1.6; color: #e8e8e8;">' + escapeDeepDiveText(line) + '</li>';
  }).join('');
  return (
    '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(251,191,36,0.06); border: 1px solid rgba(251,191,36,0.25); border-radius: 8px;">' +
    '<h4 style="color: #fbbf24; margin-bottom: 0.75rem; font-size: 1.1rem;">🔭 What would change our view</h4>' +
    '<p style="color: #9ca3af; font-size: 0.82rem; margin: 0 0 0.6rem;">Concrete signals that would weaken or flip the thesis.</p>' +
    '<ul style="padding-left: 1.5rem; margin: 0;">' + falsHtml + '</ul></div>'
  );
}

function renderDeepDiveTickers(dd) {
  var allowedTickers = dd.key_tickers;
  if (!Array.isArray(allowedTickers) || allowedTickers.length === 0 || !dd.ticker_analysis) return '';
  var allowedSet = {};
  allowedTickers.forEach(function(t) { allowedSet[String(t).toUpperCase()] = true; });
  var tickerKeys = Object.keys(dd.ticker_analysis).filter(function(t) {
    return allowedSet[String(t).toUpperCase()];
  });
  if (tickerKeys.length === 0) return '';
  var v2 = isDeepDiveV2(dd);
  var tickersHtml = tickerKeys.map(function(ticker) {
    var a = dd.ticker_analysis[ticker] || {};
    if (v2) {
      var line = a.rationale || a.why || '';
      return '<div style="margin-bottom: 0.75rem; padding: 0.75rem 1rem; background: rgba(255,255,255,0.03); border-radius: 8px;">' +
        '<span style="background: rgba(0,212,255,0.2); color: #00d4ff; padding: 0.25rem 0.75rem; border-radius: 4px; font-weight: 600; font-size: 0.9rem;">' +
        escapeDeepDiveText(ticker) + '</span>' +
        '<p style="color: #e8e8e8; line-height: 1.5; margin: 0.5rem 0 0; font-size: 0.9rem;">' + escapeDeepDiveText(line) + '</p></div>';
    }
    return '<div style="margin-bottom: 1rem; padding: 1rem; background: rgba(255,255,255,0.03); border-radius: 8px;">' +
      '<div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">' +
      '<span style="background: rgba(0,212,255,0.2); color: #00d4ff; padding: 0.25rem 0.75rem; border-radius: 4px; font-weight: 600; font-size: 0.9rem;">' + ticker + '</span></div>' +
      '<p style="color: #e8e8e8; line-height: 1.5; margin-bottom: 0.5rem; font-size: 0.9rem;"><strong style="color: #00d4ff;">Rationale:</strong> ' + (a.rationale || 'N/A') + '</p>' +
      '<p style="color: #a8b2d1; line-height: 1.5; margin-bottom: 0.5rem; font-size: 0.9rem;"><strong>Positioning:</strong> ' + (a.positioning || 'N/A') + '</p>' +
      '<p style="color: #f44336; line-height: 1.5; font-size: 0.85rem;"><strong>Risk:</strong> ' + (a.risk || 'N/A') + '</p></div>';
  }).join('');
  return (
    '<div style="margin-bottom: 1.25rem;">' +
    '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.05rem;">📈 Tickers</h4>' + tickersHtml + '</div>'
  );
}

function generateDeepDiveHTML(dd) {
  if (!dd) return '';
  var sections = [];
  var v2 = isDeepDiveV2(dd);
  var ev = (dd.episode_evidence || '').trim();
  var fals = dd.falsification_tracks;

  if (v2) {
    if (dd.overview) {
      sections.push(
        '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(0,212,255,0.05); border-left: 3px solid #00d4ff; border-radius: 8px;">' +
        '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">✨ What&apos;s new</h4>' +
        '<p style="color: #9ca3af; font-size: 0.82rem; margin: 0 0 0.6rem;">Mechanisms and claims not already on the Insight card.</p>' +
        '<p style="color: #e8e8e8; line-height: 1.7; font-size: 0.95rem;">' + escapeDeepDiveText(dd.overview) + '</p></div>'
      );
    }
    if (ev) sections.push(renderDeepDiveQuotes(ev));
    sections.push(renderDeepDiveFalsifiers(fals));
    if (dd.investment_thesis) {
      var implBlock =
        '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(123,44,191,0.08); border: 1px solid rgba(123,44,191,0.25); border-radius: 8px;">' +
        '<h4 style="color: #c084fc; margin-bottom: 0.75rem; font-size: 1.1rem;">💡 Investment implication</h4>' +
        '<p style="color: #e8e8e8; line-height: 1.7; font-size: 0.95rem; margin-bottom: 0.75rem;">' +
        escapeDeepDiveText(dd.investment_thesis) + '</p>' +
        renderDeepDiveTickers(dd) + '</div>';
      sections.push(implBlock);
    }
    if (dd.catalysts && dd.catalysts.length > 0) {
      var watchHtml = dd.catalysts.map(function(c) {
        return '<li style="margin-bottom: 0.5rem; line-height: 1.6; color: #ffc107;">' + escapeDeepDiveText(c) + '</li>';
      }).join('');
      sections.push(
        '<div style="margin-bottom: 2rem;">' +
        '<h4 style="color: #ffc107; margin-bottom: 0.75rem; font-size: 1.1rem;">📅 Watchlist</h4>' +
        '<ul style="padding-left: 1.5rem; margin: 0;">' + watchHtml + '</ul></div>'
      );
    }
    return sections.join('');
  }

  // Legacy v1 layout (older deep dives with key_takeaways_detailed)
  if (ev) sections.push(renderDeepDiveQuotes(ev));
  sections.push(renderDeepDiveFalsifiers(fals));
  if (dd.overview) {
    sections.push(
      '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(0,212,255,0.05); border-left: 3px solid #00d4ff; border-radius: 8px;">' +
      '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">📋 Overview</h4>' +
      '<p style="color: #e8e8e8; line-height: 1.7; font-size: 0.95rem;">' + dd.overview + '</p></div>'
    );
  }
  if (dd.key_takeaways_detailed && dd.key_takeaways_detailed.length > 0) {
    var takeawaysHtml = dd.key_takeaways_detailed.map(function(t) {
      return '<li style="margin-bottom: 0.5rem; line-height: 1.6; color: #e8e8e8;">' + t + '</li>';
    }).join('');
    sections.push(
      '<div style="margin-bottom: 2rem;">' +
      '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">🎯 Key Takeaways</h4>' +
      '<ul style="padding-left: 1.5rem; margin: 0;">' + takeawaysHtml + '</ul></div>'
    );
  }
  if (dd.investment_thesis) {
    sections.push(
      '<div style="margin-bottom: 2rem;">' +
      '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">💡 Investment Thesis</h4>' +
      '<p style="color: #a8b2d1; line-height: 1.7; font-size: 0.95rem;">' + dd.investment_thesis + '</p></div>'
    );
  }
  var legacyTickers = renderDeepDiveTickers(dd);
  if (legacyTickers) {
    sections.push('<div style="margin-bottom: 2rem;">' + legacyTickers + '</div>');
  }
  if (dd.catalysts && dd.catalysts.length > 0) {
    var catalystsHtml = dd.catalysts.map(function(c) {
      return '<li style="margin-bottom: 0.5rem; line-height: 1.6; color: #ffc107;">' + c + '</li>';
    }).join('');
    sections.push(
      '<div style="margin-bottom: 2rem;">' +
      '<h4 style="color: #ffc107; margin-bottom: 0.75rem; font-size: 1.1rem;">📅 Catalysts & Timeline</h4>' +
      '<ul style="padding-left: 1.5rem; margin: 0;">' + catalystsHtml + '</ul></div>'
    );
  }
  return sections.join('');
}

function parseNotableQuotes(raw) {
  if (!raw) return [];
  if (typeof raw === 'string') {
    try { raw = JSON.parse(raw); } catch (e) { return []; }
  }
  if (!Array.isArray(raw)) return [];
  return raw.map(function(q) {
    if (!q) return null;
    if (typeof q === 'string') return { speaker: '', quote: q };
    return { speaker: q.speaker || q.name || '', quote: q.quote || q.text || '' };
  }).filter(function(q) { return q && q.quote; }).slice(0, 3);
}

function isInvestorFiller(text) {
  return /^\s*(?:[\w-]+\s+){0,3}investors?\s+(?:should|must|need to|may want to)\b/i.test(text || '');
}

/** Headline is the one-sentence thesis. Under it: recap paragraphs and named quotes. */
function renderInsightRecapHTML(item) {
  if (!item) return '';
  var html = '';
  if (item.title) {
    html += '<div class="insight-title" style="font-weight:600;color:#e8e8e8;margin-bottom:0.35rem;">' +
      escapeDeepDiveText(item.title) + '</div>';
  }
  var thesis = (item.key_takeaway || '').trim();
  if (thesis && !isInvestorFiller(thesis)) {
    html += '<p class="insight-thesis" style="color:#e8e8e8;line-height:1.55;margin:0 0 0.75rem;font-size:1rem;">' +
      escapeDeepDiveText(thesis) + '</p>';
  }
  var summary = item.summary || '';
  var paras = String(summary).split(/\n\s*\n/).map(function(p) { return p.trim(); }).filter(Boolean);
  if (!paras.length && String(summary).trim()) paras = [String(summary).trim()];
  if (paras.length) {
    html += '<div class="insight-recap">';
    paras.forEach(function(p) {
      html += '<p style="color:#c5cde0;line-height:1.65;margin:0 0 0.7rem;font-size:0.92rem;">' +
        escapeDeepDiveText(p) + '</p>';
    });
    html += '</div>';
  }
  var quotes = parseNotableQuotes(item.notable_quotes);
  if (quotes.length) {
    html += '<div class="insight-quotes" style="margin-top:0.15rem;">';
    quotes.forEach(function(q) {
      var who = q.speaker
        ? '<span style="color:#00d4ff;font-weight:600;">' + escapeDeepDiveText(q.speaker) + ':</span> '
        : '';
      html += '<blockquote style="margin:0.4rem 0;padding:0.3rem 0.7rem;border-left:2px solid rgba(0,212,255,0.45);color:#e8e8e8;font-size:0.9rem;line-height:1.5;">' +
        who + '&ldquo;' + escapeDeepDiveText(q.quote) + '&rdquo;</blockquote>';
    });
    html += '</div>';
  }
  return html;
}

