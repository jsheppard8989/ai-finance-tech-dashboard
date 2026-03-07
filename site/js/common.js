/**
 * Shared script for index.html and archive.html.
 * Provides generateDeepDiveHTML(dd) for Deep Dive modal content.
 */
function generateDeepDiveHTML(dd) {
  if (!dd) return '';
  var sections = [];

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

  if (dd.ticker_analysis && Object.keys(dd.ticker_analysis).length > 0) {
    var tickersHtml = Object.keys(dd.ticker_analysis).map(function(ticker) {
      var a = dd.ticker_analysis[ticker];
      return '<div style="margin-bottom: 1rem; padding: 1rem; background: rgba(255,255,255,0.03); border-radius: 8px;">' +
        '<div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">' +
        '<span style="background: rgba(0,212,255,0.2); color: #00d4ff; padding: 0.25rem 0.75rem; border-radius: 4px; font-weight: 600; font-size: 0.9rem;">' + ticker + '</span></div>' +
        '<p style="color: #e8e8e8; line-height: 1.5; margin-bottom: 0.5rem; font-size: 0.9rem;"><strong style="color: #00d4ff;">Rationale:</strong> ' + (a.rationale || 'N/A') + '</p>' +
        '<p style="color: #a8b2d1; line-height: 1.5; margin-bottom: 0.5rem; font-size: 0.9rem;"><strong>Positioning:</strong> ' + (a.positioning || 'N/A') + '</p>' +
        '<p style="color: #f44336; line-height: 1.5; font-size: 0.85rem;"><strong>Risk:</strong> ' + (a.risk || 'N/A') + '</p></div>';
    }).join('');
    sections.push(
      '<div style="margin-bottom: 2rem;">' +
      '<h4 style="color: #00d4ff; margin-bottom: 0.75rem; font-size: 1.1rem;">📈 Ticker Analysis</h4>' + tickersHtml + '</div>'
    );
  }

  if (dd.positioning_guidance) {
    sections.push(
      '<div style="margin-bottom: 2rem; padding: 1.25rem; background: rgba(76,175,80,0.05); border: 1px solid rgba(76,175,80,0.2); border-radius: 8px;">' +
      '<h4 style="color: #4caf50; margin-bottom: 0.75rem; font-size: 1.1rem;">🎯 Positioning Guidance</h4>' +
      '<p style="color: #e8e8e8; line-height: 1.7; font-size: 0.95rem;">' + dd.positioning_guidance + '</p></div>'
    );
  }

  if (dd.risk_factors && dd.risk_factors.length > 0) {
    var risksHtml = dd.risk_factors.map(function(r) {
      return '<li style="margin-bottom: 0.5rem; line-height: 1.6; color: #f44336;">' + r + '</li>';
    }).join('');
    sections.push(
      '<div style="margin-bottom: 2rem;">' +
      '<h4 style="color: #f44336; margin-bottom: 0.75rem; font-size: 1.1rem;">⚠️ Risk Factors</h4>' +
      '<ul style="padding-left: 1.5rem; margin: 0;">' + risksHtml + '</ul></div>'
    );
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
