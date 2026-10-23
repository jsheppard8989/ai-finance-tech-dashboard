/**
 * Morning note: one editorial reading of the board already on the homepage.
 * Uses dashboardData plus the same trap / overton files the page fetches.
 * No prices, yields, or quotes are invented here. Thin inputs say the feed is quiet.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root && typeof root.window !== 'undefined') {
    root.renderMorningNote = api.renderMorningNote;
  } else if (typeof window !== 'undefined') {
    window.renderMorningNote = api.renderMorningNote;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  var MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function decode(s) {
    return String(s == null ? '' : s)
      .replace(/<[^>]+>/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;|&apos;/g, "'")
      .replace(/&#(\d+);/g, function (_, n) { return String.fromCharCode(parseInt(n, 10)); })
      .replace(/\s+/g, ' ')
      .trim();
  }

  function localToday(now) {
    var d = now || new Date();
    return { y: d.getFullYear(), m: d.getMonth(), d: d.getDate() };
  }

  function formatDay(today) {
    var dt = new Date(today.y, today.m, today.d);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatIsoDate(iso) {
    var m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return '';
    var dt = new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function dateKey(iso) {
    var m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return 0;
    return Date.UTC(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
  }

  function parseMonthDay(label) {
    var m = String(label || '').match(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b/i);
    if (!m) return null;
    return { month: MONTHS[m[1].slice(0, 3).toLowerCase()], day: parseInt(m[2], 10) };
  }

  function daysUntil(monthDay, today) {
    if (!monthDay || !today) return null;
    var current = Date.UTC(today.y, today.m, today.d);
    function diffFor(year) {
      return Math.round((Date.UTC(year, monthDay.month, monthDay.day) - current) / 86400000);
    }
    var diff = diffFor(today.y);
    if (diff < -180) diff = diffFor(today.y + 1);
    else if (diff > 180) diff = diffFor(today.y - 1);
    return diff;
  }

  function spanInner(chunk, cls) {
    var open = new RegExp('<span class="' + cls + '">', 'i');
    var found = open.exec(chunk);
    if (!found) return '';
    var i = found.index + found[0].length;
    var depth = 1;
    var out = '';
    while (i < chunk.length && depth > 0) {
      var rest = chunk.slice(i);
      var lower = rest.slice(0, 6).toLowerCase();
      if (lower.indexOf('<span') === 0) {
        depth += 1;
        out += rest.slice(0, 5);
        i += 5;
        continue;
      }
      if (rest.slice(0, 7).toLowerCase() === '</span>') {
        depth -= 1;
        if (depth === 0) break;
        out += '</span>';
        i += 7;
        continue;
      }
      out += chunk.charAt(i);
      i += 1;
    }
    return out;
  }

  function parseTrapCards(html) {
    var cards = [];
    if (!html) return cards;
    var re = /<details class="ev" id="([^"]*)">([\s\S]*?)<\/details>/gi;
    var m;
    while ((m = re.exec(html))) {
      var chunk = m[2];
      cards.push({
        id: m[1],
        date: decode(spanInner(chunk, 'date')),
        name: decode(spanInner(chunk, 'name').replace(/<span class="pill[\s\S]*?<\/span>/gi, ' ')),
        lean: decode(spanInner(chunk, 'lean')),
        wrong: decode(spanInner(chunk, 'wrong'))
      });
    }
    return cards;
  }

  function selectInsights(data) {
    var list = (data && data.mainContent && data.mainContent.insights) || [];
    return list.filter(function (i) { return i && Number(i.display_on_main) === 1; }).sort(function (a, b) {
      var da = dateKey(a.episode_release_date || a.source_date || a.added_date);
      var db = dateKey(b.episode_release_date || b.source_date || b.added_date);
      return db - da;
    });
  }

  function selectOverton(data) {
    var list = (data && data.mainContent && data.mainContent.overton) || [];
    return list.filter(function (o) {
      return o && Number(o.display_on_main) === 1 && !o.is_established && o.term;
    }).sort(function (a, b) {
      return (Number(b.novelty_score) || 0) - (Number(a.novelty_score) || 0);
    });
  }

  function shortName(card, watch) {
    if (card && card.name) {
      return card.name.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
    }
    if (watch && watch.what) return watch.what;
    return 'This print';
  }

  function leanPlain(lean) {
    return decode(String(lean || '').replace(/^We expect:\s*/i, ''));
  }

  function releaseOmitsFalsifier(wrong) {
    return /may not include|may not even|won['’]t include|will not include|not in the release/i.test(wrong || '');
  }

  function formatPct(n) {
    var v = Number(n);
    if (!isFinite(v)) return '';
    var sign = v > 0 ? '+' : '';
    return sign + v.toFixed(2) + '%';
  }

  function norm(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function sameTest(a, b) {
    var na = norm(a);
    var nb = norm(b);
    if (!na || !nb) return false;
    return na.indexOf(nb) !== -1 || nb.indexOf(na) !== -1;
  }

  function cardForWatch(watch, cards) {
    if (!watch) return null;
    var id = String(watch.trap_id || '');
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].id === id) return cards[i];
    }
    return null;
  }

  function rankWatches(home, cards, today) {
    var watches = (home && home.upcoming_watches) || [];
    var ranked = [];
    watches.forEach(function (w) {
      var card = cardForWatch(w, cards);
      var md = parseMonthDay((card && card.date) || '') || parseMonthDay(w.date_label || '') || parseMonthDay(w.what || '');
      var days = md ? daysUntil(md, today) : null;
      if (days != null && days < 0) return;
      ranked.push({ watch: w, card: card, days: days });
    });
    ranked.sort(function (a, b) {
      if (a.days == null) return 1;
      if (b.days == null) return -1;
      return a.days - b.days;
    });
    return ranked;
  }

  function findDisagreement(portfolio, cards, home, primaryId) {
    var baskets = (portfolio && portfolio.baskets) || [];
    var watches = (home && home.upcoming_watches) || [];
    for (var b = 0; b < baskets.length; b++) {
      var basket = baskets[b];
      var names = basket.names || [];
      for (var n = 0; n < names.length; n++) {
        var holding = names[n];
        var ticker = String(holding.ticker || '').toLowerCase();
        if (!ticker) continue;
        var watch = null;
        for (var w = 0; w < watches.length; w++) {
          if (String(watches[w].trap_id || '').toLowerCase() === ticker) watch = watches[w];
        }
        var card = null;
        for (var c = 0; c < cards.length; c++) {
          if (String(cards[c].id || '').toLowerCase() === ticker) card = cards[c];
        }
        if (!watch && !card) continue;
        if (primaryId && String((watch && watch.trap_id) || (card && card.id) || '').toLowerCase() === String(primaryId).toLowerCase()) {
          continue;
        }
        var exitText = decode(holding.exit || '');
        var wrong = card ? decode(card.wrong || '') : '';
        if (!exitText || !wrong || sameTest(exitText, wrong)) continue;
        return { basket: basket, holding: holding, watch: watch, card: card, exitText: exitText, wrong: wrong };
      }
    }
    return null;
  }

  function whenWord(days) {
    if (days === 0) return 'today';
    if (days === 1) return 'tomorrow';
    return '';
  }

  function headlineForWatch(item) {
    var card = item.card;
    var watch = item.watch;
    var name = shortName(card, watch);
    var when = whenWord(item.days);
    var lean = (card && card.lean) || '';
    var wrong = (card && card.wrong) || '';
    var out = /outperform/i.test(lean);
    var under = /underperform/i.test(lean);
    var omit = releaseOmitsFalsifier(wrong);
    if (when && out && omit) {
      return name + ' is supposed to outperform ' + when + '. The number that would prove it wrong may not be in the release.';
    }
    if (when && under && omit) {
      return name + ' is supposed to disappoint ' + when + '. The number that would prove it wrong may not be in the release.';
    }
    if (when && out) {
      return name + ' is supposed to outperform ' + when + '. The trap already wrote down what would prove that wrong.';
    }
    if (when && under) {
      return name + ' is supposed to disappoint ' + when + '. The falsifier is already on the card.';
    }
    if (when) {
      return watch.what + ' is the event ' + when + '. The lean lives on the card.';
    }
    var label = watch.date_label || (card && card.date) || '';
    if (out) return name + ' is the next print the trap expects to outperform' + (label ? ' (' + label + ')' : '') + '.';
    if (under) return name + ' is the next print the trap expects to disappoint' + (label ? ' (' + label + ')' : '') + '.';
    return 'The next dated watch is ' + watch.what + (label ? ' (' + label + ')' : '') + '.';
  }

  function headlineFromInsight(insight) {
    var text = decode(insight.key_takeaway || insight.title || '');
    if (!text) return '';
    var sentence = text.split(/(?<=[.!?])\s/)[0];
    if (sentence.length <= 150) return sentence;
    var cut = sentence.slice(0, 140);
    var comma = cut.lastIndexOf(',');
    if (comma > 70) return cut.slice(0, comma) + '.';
    var sp = cut.lastIndexOf(' ');
    return (sp > 70 ? cut.slice(0, sp) : cut).replace(/[,:;]+$/, '') + '.';
  }

  function ledeForWatch(item, disagreement, insight) {
    var sentences = [];
    if (item.days === 0) {
      sentences.push('You have one event dated today: ' + item.watch.what + '.');
    } else if (item.days === 1) {
      sentences.push('Nothing on the board is dated today. The next event is tomorrow: ' + item.watch.what + '.');
    } else {
      var label = item.watch.date_label || 'undated';
      sentences.push('Nothing on the board is dated today. The next watch is ' + label + ': ' + item.watch.what + '.');
    }
    if (item.card && item.card.lean) {
      var lean = leanPlain(item.card.lean);
      if (releaseOmitsFalsifier(item.card.wrong || '')) {
        sentences.push('The trap\'s lean is that ' + lean + ', and the card already says the release may not include the figure that would prove that wrong.');
      } else if (item.card.wrong) {
        sentences.push('The trap\'s lean is that ' + lean + '. The falsifier is already written on the card.');
      }
    } else {
      sentences.push('The strip has the date. The falsifier did not load with it, so this note will not invent one.');
    }
    if (disagreement) {
      var other = shortName(disagreement.card, disagreement.watch);
      var when = (disagreement.watch && disagreement.watch.date_label) || 'the next print';
      var exitClause = disagreement.exitText
        .replace(/^Exit the basket if\s+/i, '')
        .split(/\s+or\s+/i)[0]
        .replace(/\s*\([^)]*\)\s*$/, '')
        .replace(/\.$/, '');
      sentences.push('The other clock is ' + when + '. Your ' + (disagreement.basket.title || 'portfolio') + ' basket exits if ' + exitClause + '. The ' + other + ' card falsifies on a different test: ' + disagreement.wrong);
    } else if (insight && insight.key_takeaway) {
      sentences.push('The newest takeaway is a different argument: ' + decode(insight.key_takeaway));
    }
    return sentences.join(' ');
  }

  function betArgument(item) {
    var card = item.card;
    var name = shortName(card, item.watch);
    var href = 'trap-map.html#' + encodeURIComponent(item.watch.trap_id || (card && card.id) || '');
    if (!card || !card.wrong) {
      return {
        kicker: 'The bet',
        text: item.watch.what + (item.watch.date_label ? ' (' + item.watch.date_label + ')' : '') + '. The home strip does not carry the falsifier. Open the card before you treat the headline as the test.',
        links: [{ href: href, label: name + ' card' }]
      };
    }
    var lean = leanPlain(card.lean);
    return {
      kicker: 'The bet',
      text: (lean ? 'Lean: ' + lean + '. ' : '') + 'What would prove it wrong: ' + decode(card.wrong),
      links: [{ href: href, label: name + ' card' }]
    };
  }

  function disagreementArgument(disagreement) {
    var basket = disagreement.basket;
    var pct = formatPct(basket.basket_change_pct);
    var since = basket.as_of_label ? ' since ' + basket.as_of_label : '';
    var lead = (basket.title || 'The basket') + (pct ? ' is ' + pct + since + '.' : '.');
    var other = shortName(disagreement.card, disagreement.watch);
    var href = 'trap-map.html#' + encodeURIComponent((disagreement.card && disagreement.card.id) || (disagreement.watch && disagreement.watch.trap_id) || '');
    return {
      kicker: 'The disagreement',
      text: lead + ' The exit written on the basket: ' + disagreement.exitText + ' The ' + other + ' trap falsifies on a different test: ' + disagreement.wrong,
      links: [
        { href: '#portfolio-card', label: (basket.title || 'Portfolio') + ' basket' },
        { href: href, label: other + ' card' }
      ]
    };
  }

  function insightArgument(insight, alongside) {
    var takeaway = decode(insight.key_takeaway || insight.title || '');
    var who = insight.guest_name ? insight.guest_name + ', ' : '';
    var source = who + (insight.source_name || 'the feed');
    var when = formatIsoDate(insight.episode_release_date || insight.source_date || insight.added_date);
    return {
      kicker: alongside ? 'The other bet' : 'The takeaway',
      text: (when ? when + '. ' : '') + source + ': ' + takeaway,
      links: [{ href: '#insight-' + insight.id, label: 'That insight' }]
    };
  }

  function latestIsoIn(obj) {
    var best = 0;
    var re = /(\d{4}-\d{2}-\d{2})/g;
    var blob = '';
    try { blob = JSON.stringify(obj || {}); } catch (e) { blob = ''; }
    var m;
    while ((m = re.exec(blob))) {
      var k = dateKey(m[1]);
      if (k > best) best = k;
    }
    return best;
  }

  function termKey(term) {
    return String(term || '').trim().toLowerCase();
  }

  function visiblePipelineTerms(overton, demoteTerms, today) {
    var demote = {};
    (demoteTerms || []).forEach(function (t) { if (t) demote[termKey(t)] = true; });
    var rows = (overton || []).filter(function (o) {
      return o && o.term && !o.is_established && !demote[termKey(o.term)];
    }).sort(function (a, b) {
      return (Number(b.novelty_score) || 0) - (Number(a.novelty_score) || 0);
    });
    var cutoff = Date.UTC(today.y, today.m, today.d) - 30 * 86400000;
    function isRecent(o) {
      var k = dateKey(o.first_detected_date);
      return k && k >= cutoff;
    }
    var shown = {};
    var recent = [];
    rows.forEach(function (o) {
      var k = termKey(o.term);
      if (recent.length < 2 && isRecent(o) && k && !shown[k]) {
        shown[k] = true;
        recent.push(o);
      }
    });
    var evergreen = [];
    rows.forEach(function (o) {
      var k = termKey(o.term);
      if (evergreen.length < 4 - recent.length && k && !shown[k]) {
        shown[k] = true;
        evergreen.push(o);
      }
    });
    return evergreen.concat(recent);
  }

  function pickWindowTerm(model) {
    var featured = (model.featured || []).filter(function (f) { return f && f.term && f.status !== 'inactive'; });
    featured.sort(function (a, b) { return (a.display_order || 999) - (b.display_order || 999); });
    if (featured.length && featured[0].status === 'active') {
      var f = featured[0];
      return {
        term: f.term,
        text: f.term + ' is pinned on the window. ' + decode(f.thesis || '') + (f.decisive_test ? ' Decisive test: ' + decode(f.decisive_test) : ''),
        href: f.id ? '#' + String(f.id).replace(/[^a-zA-Z0-9_-]/g, '') : '#overton-window-list'
      };
    }
    var curated = (model.curated || []).filter(function (c) { return c && c.term && c.status === 'active'; });
    if (curated.length) {
      curated.sort(function (a, b) {
        var db = latestIsoIn(b) - latestIsoIn(a);
        if (db) return db;
        return (a.display_order || 999) - (b.display_order || 999);
      });
      var c = curated[0];
      var desc = decode(c.description || '');
      var src = decode(c.first_source || '');
      return {
        term: c.term,
        text: c.term + ' is pinned on the window. ' + desc + (src ? ' Pinned from ' + src + '.' : ''),
        href: c.id ? '#' + String(c.id).replace(/[^a-zA-Z0-9_-]/g, '') : '#overton-window-list'
      };
    }
    var visible = visiblePipelineTerms(model.overton, model.demoteTerms, model.today || localToday());
    if (!visible.length) return null;
    var term = visible[0];
    var mentioned = formatIsoDate(term.last_mentioned_date);
    var speaker = term.last_mentioned_speaker ? ' by ' + term.last_mentioned_speaker : '';
    var sentence = decode(term.description || '').split(/(?<=[.!?])\s/)[0] || '';
    return {
      term: term.term,
      text: term.term + ' is the pipeline term the window is still willing to show.' +
        (mentioned ? ' Last mentioned ' + mentioned + speaker + '.' : '') +
        (sentence ? ' ' + sentence : ''),
      href: term.id != null ? '#overton-' + String(term.id).replace(/[^a-zA-Z0-9_-]/g, '') : '#overton-window-list'
    };
  }

  function termArgument(model) {
    var picked = pickWindowTerm(model);
    if (!picked) return null;
    return {
      kicker: 'The term',
      text: picked.text,
      links: [{ href: picked.href, label: picked.term }]
    };
  }

  function portfolioArgument(basket) {
    if (!basket) return null;
    var pct = formatPct(basket.basket_change_pct);
    var since = basket.as_of_label ? ' since ' + basket.as_of_label : '';
    var exit = '';
    var names = basket.names || [];
    for (var i = 0; i < names.length; i++) {
      if (names[i].exit) { exit = decode(names[i].exit); break; }
    }
    return {
      kicker: 'The basket',
      text: (basket.title || 'The basket') + (pct ? ' is ' + pct + since + '.' : ' is on the board.') +
        (basket.subtitle ? ' ' + decode(basket.subtitle) + '.' : '') +
        (exit ? ' Exit written on it: ' + exit : ''),
      links: [{ href: '#portfolio-card', label: (basket.title || 'Portfolio') + ' basket' }]
    };
  }

  function quietNote(today) {
    return {
      quiet: true,
      kicker: 'Morning note · ' + formatDay(today) + ' · not investment advice',
      headline: 'The feed is quiet.',
      lede: 'You are looking at a board with nothing dated, nothing freshly argued, and no term in the window. That is the feed being quiet, not a story. The sections below are still there if a later export fills them.',
      arguments: [],
      openThis: {
        href: 'pipeline-health.html',
        label: 'Data Status',
        why: 'So you can tell a missed export from an empty day.'
      },
      aside: ''
    };
  }

  function buildMorningNote(model) {
    var today = model.today || localToday();
    var ranked = rankWatches(model.trapHome, model.trapCards || [], today);
    var primary = ranked.length ? ranked[0] : null;
    var insights = model.insights || [];
    var insight = insights.length ? insights[0] : null;
    var overton = (model.overton && model.overton[0]) || null;
    var featured = (model.featured && model.featured.length) ? model.featured[0] : null;
    var baskets = (model.portfolio && model.portfolio.baskets) || [];
    var basket = baskets.length ? baskets[0] : null;
    var hasContent = !!(primary || insight || overton || featured || basket);

    if (!hasContent) return quietNote(today);

    var primaryId = primary ? (primary.watch.trap_id || (primary.card && primary.card.id)) : '';
    var disagreement = findDisagreement(model.portfolio, model.trapCards || [], model.trapHome, primaryId);

    var headline;
    var lede;
    var openThis;
    if (primary) {
      headline = headlineForWatch(primary);
      lede = ledeForWatch(primary, disagreement, insight);
      var openName = shortName(primary.card, primary.watch);
      var why;
      if (primary.days === 0 && primary.card && releaseOmitsFalsifier(primary.card.wrong || '')) {
        why = 'It is the only item with today\'s date, and it separates the release from the filing that can prove the lean wrong.';
      } else if (primary.days === 0) {
        why = 'It is the only item with today\'s date, and the falsifier is already written on the card.';
      } else if (primary.days === 1) {
        why = 'It is the next dated card, and the falsifier is already written there.';
      } else {
        why = 'It is the next watch with a date on the strip.';
      }
      openThis = {
        href: 'trap-map.html#' + encodeURIComponent(primary.watch.trap_id || ''),
        label: openName + ' card',
        why: why
      };
    } else if (insight) {
      headline = headlineFromInsight(insight);
      var who = insight.guest_name ? insight.guest_name : (insight.source_name || 'the feed');
      lede = 'You do not have a dated print today. The newest thing ' + who + ' left on the board is the claim in the headline, and the rest of the page is context around it.';
      if (disagreement) lede += ' ' + 'Your ' + disagreement.basket.title + ' basket and the ' + shortName(disagreement.card, disagreement.watch) + ' card still disagree about what failure looks like.';
      openThis = {
        href: '#insight-' + insight.id,
        label: 'that insight',
        why: 'It is the newest takeaway the export marked for the front page.'
      };
    } else if (featured || overton || (model.curated && model.curated.length)) {
      var pickedTerm = pickWindowTerm(model);
      var termName = pickedTerm ? pickedTerm.term : ((featured && featured.term) || (overton && overton.term));
      headline = termName + ' is the strongest term on the window, and the feed has not given you a print to test it against.';
      lede = 'You do not have a dated watch or a fresh takeaway. The window is the only thing still willing to name an idea.';
      openThis = {
        href: '#overton-window-list',
        label: 'the Overton window',
        why: 'It is the only argument the board is currently making.'
      };
    } else {
      var pct = formatPct(basket.basket_change_pct);
      headline = (basket.title || 'The basket') + (pct ? ' is ' + pct + ' since it was marked' : ' is the only position on the board') + '.';
      lede = 'You do not have a fresh takeaway or a dated trap. The basket is what the board is willing to show you, including the exit it already wrote down.';
      openThis = {
        href: '#portfolio-card',
        label: (basket.title || 'the portfolio') + ' basket',
        why: 'It is the only marked position, and the exit is on the card.'
      };
    }

    var args = [];
    if (primary) args.push(betArgument(primary));
    if (insight) args.push(insightArgument(insight, !!primary));
    else if (disagreement) args.push(disagreementArgument(disagreement));
    var termArg = termArgument(model);
    if (termArg) args.push(termArg);
    if (args.length < 3 && disagreement && insight) args.push(disagreementArgument(disagreement));
    if (args.length < 2 && basket && !disagreement) {
      var portArg = portfolioArgument(basket);
      if (portArg) args.push(portArg);
    }
    args = args.filter(Boolean).slice(0, 3);

    var aside = '';
    var exported = formatIsoDate(model.generatedAt);
    if (exported && exported !== formatIsoDate(today.y + '-' + String(today.m + 1).padStart(2, '0') + '-' + String(today.d).padStart(2, '0'))) {
      aside = 'Board export ' + exported + '.';
    }

    return {
      quiet: false,
      kicker: 'Morning note · ' + formatDay(today) + ' · not investment advice',
      headline: headline,
      lede: lede,
      arguments: args,
      openThis: openThis,
      aside: aside
    };
  }

  function renderLinks(links) {
    if (!links || !links.length) return '';
    return '<p class="note-links">' + links.map(function (link) {
      return '<a href="' + esc(link.href) + '">' + esc(link.label) + '</a>';
    }).join('<span class="note-link-gap"> · </span>') + '</p>';
  }

  function renderNoteHtml(note) {
    var args = (note.arguments || []).map(function (arg) {
      return '<li>' +
        '<span class="arg-kicker">' + esc(arg.kicker) + '</span>' +
        '<p class="arg-text">' + esc(arg.text) + '</p>' +
        renderLinks(arg.links) +
        '</li>';
    }).join('');
    var list = args ? '<ol class="arguments">' + args + '</ol>' : '';
    var open = note.openThis ? (
      '<p class="open-this"><span class="open-kicker">Open this</span> <a href="' + esc(note.openThis.href) + '">' + esc(note.openThis.label) + '</a></p>' +
      '<p class="open-why">' + esc(note.openThis.why) + '</p>'
    ) : '';
    var aside = note.aside ? '<p class="note-aside">' + esc(note.aside) + '</p>' : '';
    return '<p class="kicker">' + esc(note.kicker) + '</p>' +
      '<h2 class="note-headline">' + esc(note.headline) + '</h2>' +
      '<p class="lede">' + esc(note.lede) + '</p>' +
      list + open + aside;
  }

  function modelFromParts(parts) {
    parts = parts || {};
    var data = parts.data || null;
    var featuredList = parts.featuredList;
    if (!featuredList && parts.featured && parts.featured.featured) featuredList = parts.featured.featured;
    return {
      today: parts.today || localToday(parts.now),
      generatedAt: data && data.generatedAt || null,
      insights: selectInsights(data),
      overton: selectOverton(data),
      featured: featuredList || [],
      curated: parts.curated || [],
      demoteTerms: parts.demoteTerms || [],
      portfolio: (data && data.portfolio) || null,
      trapHome: parts.trapHome || null,
      trapCards: parts.trapCards || parseTrapCards(parts.trapHtml || ''),
      hasDataFile: !!data
    };
  }

  var started = null;

  function renderMorningNote() {
    if (started) return started;
    var mount = document.getElementById('morning-note');
    if (!mount) return Promise.resolve(null);
    started = collectModel().then(function (model) {
      var note = buildMorningNote(model);
      mount.innerHTML = renderNoteHtml(note);
      mount.setAttribute('data-note-state', note.quiet ? 'quiet' : 'live');
      return note;
    }).catch(function () {
      var note = quietNote(localToday());
      mount.innerHTML = renderNoteHtml(note);
      mount.setAttribute('data-note-state', 'quiet');
      return note;
    });
    return started;
  }

  function collectModel() {
    var data = (typeof dashboardData !== 'undefined') ? dashboardData : null;
    function getJson(url) {
      return fetch(url, { cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    }
    function getText(url) {
      return fetch(url, { cache: 'no-cache' }).then(function (r) { return r.ok ? r.text() : ''; }).catch(function () { return ''; });
    }
    return Promise.all([
      getJson('./data/trap_map_home.json'),
      getText('./trap-map.html'),
      getJson('./data/featured_overton.json'),
      getJson('./data/curated_overton.json'),
      getJson('./data/overton_demote.json')
    ]).then(function (res) {
      var demote = [];
      var demoteFile = res[4] && (res[4].demote || res[4].terms || res[4]);
      if (Array.isArray(demoteFile)) {
        demoteFile.forEach(function (row) {
          if (typeof row === 'string') demote.push(row);
          else if (row && row.term) demote.push(row.term);
        });
      }
      var curated = (res[3] && res[3].curated) || [];
      curated.forEach(function (c) { if (c && c.term) demote.push(c.term); });
      return modelFromParts({
        data: data,
        trapHome: res[0],
        trapHtml: res[1],
        featured: res[2],
        curated: curated,
        demoteTerms: demote,
        today: localToday()
      });
    });
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', function () {
      renderMorningNote();
    });
  }

  return {
    buildMorningNote: buildMorningNote,
    parseTrapCards: parseTrapCards,
    modelFromParts: modelFromParts,
    renderMorningNote: renderMorningNote,
    renderNoteHtml: renderNoteHtml
  };
});
